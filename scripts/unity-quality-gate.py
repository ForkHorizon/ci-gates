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


def main(argv: Sequence[str]) -> int:
    args = parse_args(argv)
    root = sync_workspace(args.repo_url, args.sha, args.slug) if args.repo_url else Path(args.root).resolve()
    config = load_config(root / args.config)

    ensure_csproj(root, config)
    analyzer = ensure_analyzers()
    warnings = build_and_collect(root, config, analyzer)
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


def load_config(path: Path) -> dict:
    config = {key: (list(value) if isinstance(value, list) else value) for key, value in DEFAULT_CONFIG.items()}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            fail(f"Invalid JSON config {path.name}: {exc}")
        if not isinstance(loaded, dict):
            fail(f"{path.name} must be a JSON object.")
        config.update(loaded)
    return config


def sync_workspace(repo_url: str, sha: str, slug: str) -> Path:
    """Persistent per-repo clone so the multi-GB Unity repo and its Library
    survive between CI runs; each run only fetches the new objects."""
    if not sha or not slug:
        fail("--repo-url requires --sha and --slug.")
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


def ensure_csproj(root: Path, config: dict) -> None:
    if (root / config["project"]).exists():
        return
    unity = unity_binary(root, config)
    print(
        f"{config['project']} not found; generating via Unity batchmode (first run imports the Library and can take a while)...",
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
    if result.returncode != 0 or not (root / config["project"]).exists():
        tail = ""
        log = root / "unity-sync.log"
        if log.exists():
            tail = log.read_text(encoding="utf-8", errors="replace")[-2000:]
        fail(f"Unity batchmode project generation failed (exit {result.returncode}).\n{tail}")


def unity_binary(root: Path, config: dict) -> str:
    configured = str(config.get("unity_path") or "").strip()
    if configured:
        return configured
    version_file = root / "ProjectSettings" / "ProjectVersion.txt"
    if not version_file.exists():
        fail("Not a Unity project: ProjectSettings/ProjectVersion.txt is missing.")
    match = re.search(r"m_EditorVersion:\s*(\S+)", version_file.read_text(encoding="utf-8"))
    if not match:
        fail("Could not read m_EditorVersion from ProjectVersion.txt.")
    binary = Path(f"/Applications/Unity/Hub/Editor/{match.group(1)}/Unity.app/Contents/MacOS/Unity")
    if not binary.exists():
        fail(f"Unity {match.group(1)} is not installed at {binary}. Install it or set unity_path in the config.")
    return str(binary)


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


def build_and_collect(root: Path, config: dict, analyzer: Path) -> list[dict]:
    props = root / "Directory.Build.props"
    props_existed = props.exists()
    if not props_existed:
        props.write_text(
            f'<Project>\n  <ItemGroup>\n    <Analyzer Include="{analyzer}" />\n  </ItemGroup>\n</Project>\n',
            encoding="utf-8",
        )
    else:
        print("::notice::Directory.Build.props already exists; assuming it wires analyzers itself.")

    try:
        command = ["dotnet", "build", config["project"], "-v", "q", "--nologo"]
        print("$ " + " ".join(command), flush=True)
        result = subprocess.run(command, cwd=root, text=True, capture_output=True, check=False)
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
        return Path(path).resolve().relative_to(root).as_posix()
    except ValueError:
        return path


def fail(message: str) -> None:
    print(f"::error::{escape(message)}", file=sys.stderr)
    sys.exit(2)


def escape(message: str) -> str:
    return message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
