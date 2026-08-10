from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from git_paths import git_output_text, split_git_paths


@dataclass(frozen=True)
class SwiftProject:
    kind: str
    project_path: str | None = None
    scheme: str | None = None
    destination: str = ""
    configuration: str = "Debug"


def detect_project(root: Path, config: dict) -> SwiftProject:
    configuration = str(config.get("xcode_configuration") or "Debug")
    destination = str(config.get("xcode_destination") or "")
    scheme = stripped(config.get("xcode_scheme"))
    workspace = stripped(config.get("xcode_workspace"))
    project = stripped(config.get("xcode_project"))

    if workspace:
        workspace_path = root / workspace
        require_path(workspace_path, "xcode_workspace")
        return SwiftProject(
            "xcode-workspace",
            workspace,
            scheme or detect_scheme(root, "-workspace", workspace),
            destination,
            configuration,
        )

    if project:
        project_path = root / project
        require_path(project_path, "xcode_project")
        return SwiftProject(
            "xcode-project", project, scheme or detect_scheme(root, "-project", project), destination, configuration
        )

    workspaces = sorted(path for path in root.glob("*.xcworkspace") if path.is_dir())
    projects = sorted(path for path in root.glob("*.xcodeproj") if path.is_dir())

    if len(workspaces) == 1:
        rel = workspaces[0].relative_to(root).as_posix()
        return SwiftProject(
            "xcode-workspace", rel, scheme or detect_scheme(root, "-workspace", rel), destination, configuration
        )
    if len(projects) == 1:
        rel = projects[0].relative_to(root).as_posix()
        return SwiftProject(
            "xcode-project", rel, scheme or detect_scheme(root, "-project", rel), destination, configuration
        )
    if not workspaces and not projects and (root / "Package.swift").exists():
        return SwiftProject("spm")

    if len(workspaces) + len(projects) > 1:
        fail(
            "Multiple Xcode projects/workspaces found. Set xcode_workspace or xcode_project in .swift-quality-gate.json."
        )
    fail("No SwiftPM package or root Xcode project/workspace found.")


def detect_scheme(root: Path, flag: str, project_path: str) -> str:
    result = subprocess.run(
        ["xcodebuild", "-list", "-json", flag, project_path],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        fail(trimmed_error(result.stdout + result.stderr, f"Unable to inspect schemes for {project_path}."))
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        fail(f"Unable to parse xcodebuild scheme list for {project_path}.")

    container_key = "workspace" if flag == "-workspace" else "project"
    schemes = payload.get(container_key, {}).get("schemes", [])
    if len(schemes) == 1:
        return str(schemes[0])
    if not schemes:
        fail(f"No shared schemes found for {project_path}. Set xcode_scheme in .swift-quality-gate.json.")
    fail(
        f"Multiple schemes found for {project_path}: {', '.join(map(str, schemes))}. Set xcode_scheme in .swift-quality-gate.json."
    )


def xcodebuild_base_command(project: SwiftProject) -> list[str]:
    cmd = ["xcodebuild"]
    if project.kind == "xcode-workspace":
        cmd.extend(["-workspace", project.project_path or ""])
    else:
        cmd.extend(["-project", project.project_path or ""])
    cmd.extend(["-scheme", project.scheme or ""])
    if project.configuration:
        cmd.extend(["-configuration", project.configuration])
    if project.destination:
        cmd.extend(["-destination", project.destination])
    cmd.append("CODE_SIGNING_ALLOWED=NO")
    return cmd


def swift_format_config(root: Path, config: dict) -> Path | None:
    preferred = stripped(config.get("swift_format_config"))
    fallback = stripped(config.get("fallback_swift_format_config"))
    if preferred and (root / preferred).exists():
        return root / preferred
    if fallback and (root / fallback).exists():
        return root / fallback
    return None


def ensure_periphery(config: dict) -> str:
    periphery = shutil.which("periphery")
    if periphery:
        return periphery

    if not bool(config.get("dead_code_install_periphery", True)):
        fail("DeadCodeGate requires periphery, but it was not found on PATH.")

    brew = shutil.which("brew")
    if not brew:
        fail("DeadCodeGate requires periphery. Homebrew is not available, so CI Scope cannot install it automatically.")

    print("periphery not found; installing with Homebrew...")
    run([brew, "install", "periphery"], Path.cwd())
    periphery = shutil.which("periphery")
    if not periphery:
        fail("Homebrew completed, but periphery is still not available on PATH.")
    return periphery


def collect_swift_paths(root: Path, config: dict, args: argparse.Namespace) -> list[Path]:
    candidates = changed_paths(root, args.base, args.head) if args.mode == "changed" else all_repo_paths(root)

    paths = []
    for path in candidates:
        if path.suffix != ".swift" or not path.is_file():
            continue
        relative = to_relative(root, path)
        if should_ignore(relative, config.get("ignore", [])):
            continue
        paths.append(path)
    return sorted(paths)


def changed_paths(root: Path, base: str, head: str) -> list[Path]:
    attempts = [
        ["git", "diff", "-z", "--name-only", "--diff-filter=ACMRT", f"{base}...{head}"],
        ["git", "diff", "-z", "--name-only", "--diff-filter=ACMRT", base, head],
    ]
    for command in attempts:
        result = subprocess.run(command, cwd=root, text=False, capture_output=True, check=False)
        if result.returncode == 0:
            return [root / path for path in split_git_paths(result.stdout)]
    fail(
        trimmed_error(
            git_output_text(result.stdout) + git_output_text(result.stderr), "Unable to collect changed files."
        )
    )


def all_repo_paths(root: Path) -> list[Path]:
    result = subprocess.run(["git", "ls-files", "-z"], cwd=root, text=False, capture_output=True, check=False)
    if result.returncode == 0:
        return [root / path for path in split_git_paths(result.stdout)]

    paths = []
    for current_root, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name != ".git"]
        for filename in filenames:
            paths.append(Path(current_root) / filename)
    return paths


def should_ignore(relative_path: str, patterns: Sequence[str]) -> bool:
    parts = relative_path.split("/")
    basename = parts[-1]
    for pattern in patterns:
        normalized = str(pattern).strip().replace("\\", "/")
        if not normalized:
            continue
        if "/" not in normalized:
            if any(part == normalized for part in parts):
                return True
            if fnmatch.fnmatch(basename, normalized):
                return True
            continue
        if fnmatch.fnmatch(relative_path, normalized):
            return True
        if fnmatch.fnmatch(relative_path, f"**/{normalized}"):
            return True
    return False


def require_path(path: Path, key: str) -> None:
    if not path.exists():
        fail(f"{key} points to a missing path: {path}")


def run(command: Sequence[str], cwd: Path) -> None:
    print("$ " + " ".join(shell_display(arg) for arg in command), flush=True)
    result = subprocess.run(command, cwd=cwd, text=True, check=False)
    if result.returncode != 0:
        sys.exit(result.returncode)


def fail(message: str) -> None:
    print(f"::error::{escape_github_message(message)}", file=sys.stderr)
    sys.exit(2)


def error(path: str, line: int, title: str, message: str) -> None:
    print(f"::error file={path},line={line},title={title}::{escape_github_message(message)}")


def stripped(value: object) -> str:
    return str(value or "").strip()


def trimmed_error(message: str, fallback: str) -> str:
    text = message.strip()
    return text if text else fallback


def shell_display(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_@%+=:,./-]+", value):
        return value
    return "'" + value.replace("'", "'\\''") + "'"


def escape_github_message(message: str) -> str:
    return message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def to_relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root).as_posix()


def github_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.as_posix()
