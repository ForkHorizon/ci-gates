#!/usr/bin/env python3
"""Portable Unity C# quality gate.

Compiles the Unity-generated Assembly-CSharp project with
Microsoft.Unity.Analyzers attached and fails on analyzer or compiler
warnings in first-party code (Assets/, excluding Assets/Plugins and other
configured third-party roots). Generates the csproj via Unity batchmode when
the checkout doesn't have one. Stdlib-only, like the other ci-gates scripts.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path
from collections.abc import Sequence

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

DEFAULT_PACKAGE_CONFIG = {
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
    if args.repo_url:
        root = sync_workspace(args.repo_url, args.sha, args.slug)
    else:
        progress("unity", current=1, total=5, detail="Preparing workspace")
        root = Path(args.root).resolve()
    config = load_config(root / args.config, is_pkg=is_unity_package(root))

    progress("unity", current=2, total=5, detail="Preparing project files")
    build_root, target_project = ensure_csproj(root, config, slug=args.slug)
    progress("unity", current=3, total=5, detail="Loading analyzers")
    analyzer = ensure_analyzers()
    progress("unity", current=4, total=5, detail="Compiling C#")
    warnings = build_and_collect(build_root, target_project, analyzer)
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
    base = DEFAULT_PACKAGE_CONFIG if is_pkg else DEFAULT_CONFIG
    config = {key: (list(value) if isinstance(value, list) else value) for key, value in base.items()}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            fail(f"Invalid JSON config {path.name}: {exc}")
        if not isinstance(loaded, dict):
            fail(f"{path.name} must be a JSON object.")
        if is_pkg and loaded.get("include_paths") == ["Assets/"]:
            # If a package config copied the default Unity project template, ensure Runtime/Editor are included
            loaded["include_paths"] = ["Runtime/", "Editor/"]
        config.update(loaded)
    return config


def sync_workspace(repo_url: str, sha: str, slug: str) -> Path:
    """Persistent per-repo clone so the multi-GB Unity repo and its Library
    survive between CI runs; each run only fetches the new objects."""
    if not sha or not slug:
        fail("--repo-url requires --sha and --slug.")
    progress("unity", current=1, total=5, detail="Syncing workspace")
    workspace = CACHE_DIR / "unity-workspaces" / slug.replace("/", "__")
    workspace.parent.mkdir(parents=True, exist_ok=True)
    if not (workspace / ".git").exists():
        print(f"Priming Unity workspace cache at {workspace} (one-time full clone)...", flush=True)
        run_checked(["git", "clone", repo_url, str(workspace)], cwd=workspace.parent)
    # the token embedded in repo_url is per-job, so refresh the remote every run
    run_checked(["git", "-C", str(workspace), "remote", "set-url", "origin", repo_url], cwd=workspace)
    run_checked(["git", "-C", str(workspace), "fetch", "--force", "origin", sha], cwd=workspace)
    run_checked(["git", "-C", str(workspace), "checkout", "--force", sha], cwd=workspace)
    # -fd without -x: drops stray untracked files but keeps gitignored state
    # (Library/, generated csproj) that makes incremental runs fast.
    run_checked(["git", "-C", str(workspace), "clean", "-fdq"], cwd=workspace)
    print(f"Workspace ready at {workspace} @ {sha[:12]}")
    return workspace


def run_checked(command: list[str], cwd: Path) -> None:
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        fail(f"{' '.join(command[:3])}... failed: {(result.stderr or result.stdout).strip()[-1500:]}")


def ensure_csproj(root: Path, config: dict, slug: str = "") -> tuple[Path, str]:
    if is_unity_package(root):
        return ensure_package_harness(root, config, slug=slug)

    target_project = config.get("project") or "Assembly-CSharp.csproj"
    if (root / target_project).exists():
        return root, target_project

    unity = unity_binary(root, config)
    print(
        f"{target_project} not found; generating via Unity batchmode (first run imports the Library and can take a while)...",
        flush=True,
    )
    result = subprocess.run(
        [
            unity,
            "-batchmode",
            "-nographics",
            "-quit",
            "-projectPath",
            str(root),
            "-executeMethod",
            "Packages.Rider.Editor.RiderScriptEditor.SyncSolution",
            "-logFile",
            str(root / "unity-sync.log"),
        ],
        check=False,
    )
    if result.returncode != 0 or not (root / target_project).exists():
        tail = ""
        log = root / "unity-sync.log"
        if log.exists():
            tail = log.read_text(encoding="utf-8", errors="replace")[-2000:]
        fail(f"Unity batchmode project generation failed (exit {result.returncode}).\n{tail}")
    return root, target_project


def ensure_package_harness(root: Path, config: dict, slug: str = "") -> tuple[Path, str]:
    key = slug.replace("/", "__") if slug else root.name
    harness_dir = CACHE_DIR / "unity-package-harnesses" / key
    harness_dir.mkdir(parents=True, exist_ok=True)
    unity = unity_binary(root, config)

    if not (harness_dir / "ProjectSettings").exists():
        print(f"Creating Unity harness project at {harness_dir}...", flush=True)
        res = subprocess.run(
            [unity, "-batchmode", "-nographics", "-quit", "-createProject", str(harness_dir), "-logFile", str(harness_dir / "create.log")],
            check=False,
        )
        if res.returncode != 0:
            tail = ""
            log = harness_dir / "create.log"
            if log.exists():
                tail = log.read_text(encoding="utf-8", errors="replace")[-2000:]
            fail(f"Failed to create Unity package harness at {harness_dir}:\n{tail}")

    manifest_path = harness_dir / "Packages" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {"dependencies": {}}
    pkg_json = json.loads((root / "package.json").read_text(encoding="utf-8"))
    pkg_name = pkg_json.get("name") or root.name

    manifest.setdefault("dependencies", {})[pkg_name] = f"file:{root}"
    for dep, ver in pkg_json.get("dependencies", {}).items():
        manifest["dependencies"][dep] = ver
    manifest["dependencies"]["com.unity.ide.rider"] = "3.0.38"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print(f"Syncing solution for package {pkg_name} via Unity Rider...", flush=True)
    res = subprocess.run(
        [
            unity,
            "-batchmode",
            "-nographics",
            "-quit",
            "-projectPath",
            str(harness_dir),
            "-executeMethod",
            "Packages.Rider.Editor.RiderScriptEditor.SyncSolution",
            "-logFile",
            str(harness_dir / "unity-sync.log"),
        ],
        check=False,
    )
    if res.returncode != 0:
        tail = ""
        log = harness_dir / "unity-sync.log"
        if log.exists():
            tail = log.read_text(encoding="utf-8", errors="replace")[-2000:]
        fail(f"Unity harness solution sync failed (exit {res.returncode}):\n{tail}")

    sln_files = list(harness_dir.glob("*.sln"))
    if sln_files:
        return harness_dir, sln_files[0].name

    csproj_files = list(harness_dir.glob("*.csproj"))
    if csproj_files:
        return harness_dir, csproj_files[0].name

    fail(f"No solution or csproj files generated in {harness_dir}.")


def unity_binary(root: Path, config: dict) -> str:
    configured = str(config.get("unity_path") or "").strip()
    if configured:
        return configured
    version_file = root / "ProjectSettings" / "ProjectVersion.txt"
    if version_file.exists():
        match = re.search(r"m_EditorVersion:\s*(\S+)", version_file.read_text(encoding="utf-8"))
        if not match:
            fail("Could not read m_EditorVersion from ProjectVersion.txt.")
        binary = Path(f"/Applications/Unity/Hub/Editor/{match.group(1)}/Unity.app/Contents/MacOS/Unity")
        if not binary.exists():
            fail(f"Unity {match.group(1)} is not installed at {binary}. Install it or set unity_path in the config.")
        return str(binary)

    if is_unity_package(root):
        req_ver = ""
        try:
            pkg_data = json.loads((root / "package.json").read_text(encoding="utf-8"))
            req_ver = str(pkg_data.get("unity") or "").strip()
        except Exception:
            pass
        hub_dir = Path("/Applications/Unity/Hub/Editor")
        if hub_dir.exists():
            installed = sorted([p.name for p in hub_dir.iterdir() if (p / "Unity.app").exists()], reverse=True)
            if req_ver:
                prefix = req_ver.split(".")[0]
                for v in installed:
                    if v.startswith(prefix):
                        return str(hub_dir / v / "Unity.app/Contents/MacOS/Unity")
            if installed:
                return str(hub_dir / installed[0] / "Unity.app/Contents/MacOS/Unity")

    fail("Not a Unity project or package: ProjectSettings/ProjectVersion.txt is missing and no compatible Unity installation found.")


def ensure_analyzers() -> Path:
    dll = CACHE_DIR / "microsoft-unity-analyzers" / "Microsoft.Unity.Analyzers.dll"
    if dll.exists():
        return dll
    dll.parent.mkdir(parents=True, exist_ok=True)
    archive = dll.parent / "package.nupkg"
    print("Downloading Microsoft.Unity.Analyzers from NuGet...", flush=True)
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


def build_and_collect(build_root: Path, target_project: str, analyzer: Path) -> list[dict]:
    props = build_root / "Directory.Build.props"
    props_existed = props.exists()
    if not props_existed:
        props.write_text(
            f'<Project>\n  <ItemGroup>\n    <Analyzer Include="{analyzer}" />\n  </ItemGroup>\n</Project>\n',
            encoding="utf-8",
        )
    else:
        print("::notice::Directory.Build.props already exists; assuming it wires analyzers itself.")

    try:
        command = ["dotnet", "build", target_project, "-v", "q", "--nologo"]
        print("$ " + " ".join(command), flush=True)
        result = subprocess.run(command, cwd=build_root, text=True, capture_output=True, check=False)
        output = result.stdout + result.stderr
        print(output, flush=True)
        if result.returncode != 0:
            fail(f"dotnet build failed with exit code {result.returncode}.")
    finally:
        if not props_existed:
            props.unlink(missing_ok=True)

    warnings, seen = [], set()
    for line in output.splitlines():
        match = WARNING_RE.match(line.strip())
        if not match:
            continue
        key = (match["path"], match["line"], match["code"])
        if key in seen:
            continue
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
    if not any(rel.startswith(prefix) for prefix in config["include_paths"]):
        return False
    return not any(rel.startswith(prefix) for prefix in config["exclude_paths"])


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
