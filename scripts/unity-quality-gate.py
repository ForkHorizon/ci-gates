#!/usr/bin/env python3
"""Portable Unity C# quality gate for projects and UPM packages."""

from __future__ import annotations

import argparse
import contextlib
import json
import re
import subprocess
import sys
import urllib.request
import zipfile
from collections.abc import Sequence
from pathlib import Path

from _progress import progress

ANALYZERS_URL = "https://www.nuget.org/api/v2/package/Microsoft.Unity.Analyzers"
CACHE_DIR = Path.home() / "Library/Caches/ci-gates"
WARNING_RE = re.compile(
    r"^(?P<path>/[^(]+)\((?P<line>\d+),\d+\): warning (?P<code>[A-Z]+\d+): (?P<message>.*?)(?: \[[^\]]*\])?$"
)
DEFAULT_CONFIG = {
    "project": "Assembly-CSharp.csproj",
    "unity_path": "",
    "include_paths": ["Assets/"],
    "exclude_paths": ["Assets/Plugins/", "Assets/Libs/", "Assets/TextMesh Pro/", "Assets/ThirdParty/"],
    "warning_exclude_codes": [],
}
DEFAULT_PKG_CONFIG = {
    "project": "",
    "unity_path": "",
    "include_paths": ["Runtime/", "Editor/"],
    "exclude_paths": ["Tests~/", "tools~/", "Plugins/"],
    "warning_exclude_codes": [],
}


def is_unity_package(root: Path) -> bool:
    return (root / "package.json").exists() and not (root / "ProjectSettings" / "ProjectVersion.txt").exists()


def main(argv: Sequence[str]) -> int:
    args = parse_args(argv)
    root = sync_workspace(args.repo_url, args.sha, args.slug) if args.repo_url else Path(args.root).resolve()
    config = load_config(root / args.config, is_pkg=is_unity_package(root))

    progress("unity", current=2, total=5, detail="Preparing project files")
    build_root, target = ensure_csproj(root, config, slug=args.slug)
    progress("unity", current=3, total=5, detail="Loading analyzers")
    analyzer = ensure_analyzers()
    progress("unity", current=4, total=5, detail="Compiling C#")
    warnings = build_and_collect(build_root, target, analyzer)
    offending = [
        w
        for w in warnings
        if is_first_party(root, w["path"], config) and w["code"] not in config["warning_exclude_codes"]
    ]
    if offending:
        for w in offending[:20]:
            print(
                f"::error file={relative(root, w['path'])},line={w['line']},title={w['code']}::{escape(w['message'])}"
            )
        if len(offending) > 20:
            print(f"::notice::Unity Quality Gate suppressed {len(offending) - 20} additional annotations.")
        print(f"::error::Unity Quality Gate failed: {len(offending)} warning(s) in first-party code.")
        return 1
    print(f"Unity Quality Gate passed: build clean, {len(warnings)} third-party/excluded warning(s) ignored.")
    return 0


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compile Unity C# with analyzers and fail on first-party warnings.")
    parser.add_argument("--config", default=".unity-quality-gate.json")
    parser.add_argument("--root", default=".")
    parser.add_argument("--repo-url", default="", help="Clone URL; enables the persistent cached workspace.")
    parser.add_argument("--sha", default="", help="Commit to check out in the cached workspace.")
    parser.add_argument("--slug", default="", help="owner/repo, used as the cache workspace key.")
    return parser.parse_args(argv)


def load_config(path: Path, is_pkg: bool = False) -> dict:
    base = DEFAULT_PKG_CONFIG if is_pkg else DEFAULT_CONFIG
    config = {k: (list(v) if isinstance(v, list) else v) for k, v in base.items()}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            fail(f"Invalid JSON config {path.name}: {exc}")
        if not isinstance(loaded, dict):
            fail(f"{path.name} must be a JSON object.")
        if is_pkg and loaded.get("include_paths") == ["Assets/"]:
            loaded["include_paths"] = ["Runtime/", "Editor/"]
        config.update(loaded)
    return config


def sync_workspace(repo_url: str, sha: str, slug: str) -> Path:
    if not sha or not slug:
        fail("--repo-url requires --sha and --slug.")
    progress("unity", current=1, total=5, detail="Syncing workspace")
    workspace = CACHE_DIR / "unity-workspaces" / slug.replace("/", "__")
    workspace.parent.mkdir(parents=True, exist_ok=True)
    if not (workspace / ".git").exists():
        run_cmd(["git", "clone", repo_url, str(workspace)], cwd=workspace.parent)
    run_cmd(["git", "-C", str(workspace), "remote", "set-url", "origin", repo_url])
    run_cmd(["git", "-C", str(workspace), "fetch", "--force", "origin", sha])
    run_cmd(["git", "-C", str(workspace), "checkout", "--force", sha])
    run_cmd(["git", "-C", str(workspace), "clean", "-fdq"])
    return workspace


def run_cmd(command: list[str], cwd: Path | None = None, log_file: Path | None = None) -> str:
    res = subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)
    output = res.stdout + res.stderr
    if res.returncode != 0:
        tail = log_file.read_text(encoding="utf-8", errors="replace")[-2000:] if log_file and log_file.exists() else ""
        fail(f"{' '.join(command[:3])}... failed (exit {res.returncode}):\n{(tail or output).strip()[-1500:]}")
    return output


def _sync_rider(unity: str, project_dir: Path) -> None:
    log = project_dir / "unity-sync.log"
    cmd = [
        unity,
        "-batchmode",
        "-nographics",
        "-quit",
        "-projectPath",
        str(project_dir),
        "-executeMethod",
        "Packages.Rider.Editor.RiderScriptEditor.SyncSolution",
        "-logFile",
        str(log),
    ]
    run_cmd(cmd, log_file=log)


def ensure_csproj(root: Path, config: dict, slug: str = "") -> tuple[Path, str]:
    if is_unity_package(root):
        return ensure_package_harness(root, config, slug=slug)
    target = config.get("project") or "Assembly-CSharp.csproj"
    if not (root / target).exists():
        _sync_rider(unity_binary(root, config), root)
    if not (root / target).exists():
        fail(f"Project file {target} not generated in {root}.")
    return root, target


def ensure_package_harness(root: Path, config: dict, slug: str = "") -> tuple[Path, str]:
    key = slug.replace("/", "__") if slug else root.name
    harness = CACHE_DIR / "unity-package-harnesses" / key
    harness.mkdir(parents=True, exist_ok=True)
    unity = unity_binary(root, config)
    if not (harness / "ProjectSettings").exists():
        log = harness / "create.log"
        run_cmd(
            [unity, "-batchmode", "-nographics", "-quit", "-createProject", str(harness), "-logFile", str(log)],
            log_file=log,
        )
    _configure_harness_manifest(harness, root)
    _sync_rider(unity, harness)
    sln_files = list(harness.glob("*.sln")) or list(harness.glob("*.csproj"))
    if not sln_files:
        fail(f"No solution or csproj files generated in {harness}.")
    return harness, sln_files[0].name


def _configure_harness_manifest(harness: Path, root: Path) -> None:
    manifest_path = harness / "Packages" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {"dependencies": {}}
    pkg_json = json.loads((root / "package.json").read_text(encoding="utf-8"))
    pkg_name = pkg_json.get("name") or root.name
    deps = manifest.setdefault("dependencies", {})
    deps[pkg_name] = f"file:{root}"
    for dep, ver in pkg_json.get("dependencies", {}).items():
        deps[dep] = ver
    deps["com.unity.ide.rider"] = "3.0.38"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def unity_binary(root: Path, config: dict) -> str:
    if config.get("unity_path"):
        return str(config["unity_path"]).strip()
    version_file = root / "ProjectSettings" / "ProjectVersion.txt"
    if version_file.exists():
        match = re.search(r"m_EditorVersion:\s*(\S+)", version_file.read_text(encoding="utf-8"))
        if match:
            bin_path = Path(f"/Applications/Unity/Hub/Editor/{match.group(1)}/Unity.app/Contents/MacOS/Unity")
            if bin_path.exists():
                return str(bin_path)
    if is_unity_package(root):
        found = _find_installed_unity(root)
        if found:
            return found
    fail("Not a Unity project or package: missing ProjectSettings/ProjectVersion.txt and no Unity editor found.")


def _find_installed_unity(root: Path) -> str | None:
    req_ver = ""
    with contextlib.suppress(Exception):
        req_ver = str(json.loads((root / "package.json").read_text(encoding="utf-8")).get("unity") or "").strip()
    hub_dir = Path("/Applications/Unity/Hub/Editor")
    if not hub_dir.exists():
        return None
    installed = sorted([p.name for p in hub_dir.iterdir() if (p / "Unity.app").exists()], reverse=True)
    if req_ver:
        prefix = req_ver.split(".")[0]
        for v in installed:
            if v.startswith(prefix):
                return str(hub_dir / v / "Unity.app/Contents/MacOS/Unity")
    return str(hub_dir / installed[0] / "Unity.app/Contents/MacOS/Unity") if installed else None


def ensure_analyzers() -> Path:
    dll = CACHE_DIR / "microsoft-unity-analyzers" / "Microsoft.Unity.Analyzers.dll"
    if dll.exists():
        return dll
    dll.parent.mkdir(parents=True, exist_ok=True)
    archive = dll.parent / "package.nupkg"
    urllib.request.urlretrieve(ANALYZERS_URL, archive)
    with zipfile.ZipFile(archive) as bundle:
        for name in bundle.namelist():
            if name.endswith("analyzers/dotnet/cs/Microsoft.Unity.Analyzers.dll"):
                dll.write_bytes(bundle.read(name))
                break
    archive.unlink(missing_ok=True)
    if not dll.exists():
        fail("Could not extract Microsoft.Unity.Analyzers.dll from the NuGet package.")
    return dll


def build_and_collect(build_root: Path, target: str, analyzer: Path) -> list[dict]:
    props = build_root / "Directory.Build.props"
    props_existed = props.exists()
    if not props_existed:
        props.write_text(
            f'<Project>\n  <ItemGroup>\n    <Analyzer Include="{analyzer}" />\n  </ItemGroup>\n</Project>\n',
            encoding="utf-8",
        )
    try:
        output = run_cmd(["dotnet", "build", target, "-v", "q", "--nologo"], cwd=build_root)
        print(output, flush=True)
    finally:
        if not props_existed:
            props.unlink(missing_ok=True)

    warnings, seen = [], set()
    for line in output.splitlines():
        match = WARNING_RE.match(line.strip())
        if match:
            key = (match["path"], match["line"], match["code"])
            if key not in seen:
                seen.add(key)
                warnings.append(
                    {
                        "path": match["path"],
                        "line": int(match["line"]),
                        "code": match["code"],
                        "message": match["message"].strip(),
                    }
                )
    return warnings


def is_first_party(root: Path, path: str, config: dict) -> bool:
    rel = relative(root, path)
    return any(rel.startswith(p) for p in config["include_paths"]) and not any(
        rel.startswith(p) for p in config["exclude_paths"]
    )


def relative(root: Path, path: str) -> str:
    try:
        return Path(path).resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path


def fail(message: str) -> None:
    print(f"::error::{escape(message)}", file=sys.stderr)
    sys.exit(2)


def escape(message: str) -> str:
    return message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
