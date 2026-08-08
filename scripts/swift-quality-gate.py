#!/usr/bin/env python3
"""Portable Swift quality gate installed by CI Scope.

The checker intentionally uses only Python's standard library so it can be
copied into Swift repositories without requiring a package manager for the
Python side of the workflow.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from collections.abc import Sequence

from _progress import progress
from swift_quality_support import (
    collect_swift_paths,
    detect_project,
    ensure_periphery,
    error,
    github_path,
    run,
    swift_format_config,
    xcodebuild_base_command,
)


DEFAULT_IGNORE = [
    ".git",
    ".svn",
    ".hg",
    ".build",
    ".dart_tool",
    ".gradle",
    ".next",
    ".nuxt",
    ".pytest_cache",
    ".tox",
    ".venv",
    "DerivedData",
    "Pods",
    "bin",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "obj",
    "out",
    "target",
    "vendor",
    "*.designer.swift",
    "*.generated.*",
    "*.g.swift",
    "*.gen.*",
    "*.snap",
    "*.snapshot",
]

DEFAULT_CONFIG = {
    "ignore": DEFAULT_IGNORE,
    "xcode_workspace": "",
    "xcode_project": "",
    "xcode_scheme": "",
    "xcode_destination": "generic/platform=macOS",
    "xcode_configuration": "Debug",
    "swift_format_config": ".swift-format",
    "fallback_swift_format_config": ".ci-scope-swift-format.json",
    "dead_code_enabled": True,
    "dead_code_install_periphery": True,
    "periphery_arguments": [],
}


def main(argv: Sequence[str]) -> int:
    args = parse_args(argv)
    root = Path(args.root).resolve()
    config = load_config(root / args.config)

    if args.stage == "all":
        stages = ("build", "format", "dead-code")
        for index, stage in enumerate(stages, start=1):
            progress("quality", current=index, total=len(stages), detail=stage)
            run_stage(stage, root, config, args)
        return 0

    run_stage(args.stage, root, config, args)
    return 0


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Swift build, format, and dead-code gates.")
    parser.add_argument("--stage", choices=("all", "build", "format", "dead-code"), default="all")
    parser.add_argument("--mode", choices=("all", "changed"), default="all")
    parser.add_argument("--base", default="origin/main", help="Base ref for changed mode.")
    parser.add_argument("--head", default="HEAD", help="Head ref for changed mode.")
    parser.add_argument("--config", default=".swift-quality-gate.json")
    parser.add_argument("--root", default=".")
    return parser.parse_args(argv)


def run_stage(stage: str, root: Path, config: dict, args: argparse.Namespace) -> None:
    title = {
        "build": "Build",
        "format": "Format",
        "dead-code": "DeadCodeGate",
    }[stage]
    print(f"::group::{title}", flush=True)
    try:
        if stage == "build":
            run_build(root, config)
        elif stage == "format":
            run_format(root, config, args)
        elif stage == "dead-code":
            run_dead_code(root, config)
    finally:
        print("::endgroup::", flush=True)


def load_config(path: Path) -> dict:
    config = dict(DEFAULT_CONFIG)
    config["ignore"] = list(DEFAULT_IGNORE)
    config["periphery_arguments"] = []

    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            error(github_path(path), 1, "invalid_config", f"Invalid JSON config: {exc}")
            sys.exit(2)
        if not isinstance(loaded, dict):
            error(github_path(path), 1, "invalid_config", "Swift quality gate config must be a JSON object.")
            sys.exit(2)
        config.update(loaded)

    config["ignore"] = list(config.get("ignore", []))
    config["periphery_arguments"] = list(config.get("periphery_arguments", []))
    return config


def run_build(root: Path, config: dict) -> None:
    project = detect_project(root, config)
    if project.kind == "spm":
        run(["swift", "build"], root)
        return

    cmd = xcodebuild_base_command(project)
    cmd.append("build")
    run(cmd, root)


def run_format(root: Path, config: dict, args: argparse.Namespace) -> None:
    swift_files = collect_swift_paths(root, config, args)
    if not swift_files:
        print(f"Swift format skipped: no Swift files in {args.mode} mode.")
        return

    formatter = ["xcrun", "swift-format", "lint", "--strict", "--parallel"]
    format_config = swift_format_config(root, config)
    if format_config is not None:
        formatter.extend(["--configuration", str(format_config)])
    formatter.extend([str(path) for path in swift_files])
    run(formatter, root)


def run_dead_code(root: Path, config: dict) -> None:
    if not bool(config.get("dead_code_enabled", True)):
        print("DeadCodeGate skipped: dead_code_enabled is false.")
        return
    if not collect_swift_paths(root, config, argparse.Namespace(mode="all", base="", head="")):
        print("DeadCodeGate skipped: no Swift files found.")
        return

    periphery = ensure_periphery(config)
    project = detect_project(root, config)
    cmd = [periphery, "scan", "--format", "xcode", "--strict", "--clean-build"]
    cmd.extend(str(arg) for arg in config.get("periphery_arguments", []))

    if project.kind == "xcode-workspace":
        cmd.extend(["--workspace", project.project_path or "", "--schemes", project.scheme or ""])
    elif project.kind == "xcode-project":
        cmd.extend(["--project", project.project_path or "", "--schemes", project.scheme or ""])

    xcode_args = []
    if project.kind.startswith("xcode"):
        if project.destination:
            xcode_args.extend(["-destination", project.destination])
        if project.configuration:
            xcode_args.extend(["-configuration", project.configuration])
        xcode_args.append("CODE_SIGNING_ALLOWED=NO")
    if xcode_args:
        cmd.append("--")
        cmd.extend(xcode_args)

    run(cmd, root)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
