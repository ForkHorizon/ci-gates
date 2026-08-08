#!/usr/bin/env python3
"""Portable Swift compile gate installed by CI Scope.

The checker intentionally uses only Python's standard library so it can be
copied into Swift repositories without requiring package-manager setup.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from re import Pattern
from collections.abc import Sequence

from swift_compile_common import (
    as_string_list,
    emit_error,
    emit_file_error,
    github_path,
    truncate,
)
from swift_compile_output import annotate_critical_warnings, run_and_collect
from swift_compile_project import detect_project, xcodebuild_base_command
from swift_compile_result import WarningPolicy


DEFAULT_IGNORE = [
    ".git",
    ".svn",
    ".hg",
    ".build",
    ".build/**",
    "DerivedData",
    "DerivedData/**",
    "Pods",
    "Pods/**",
    "Carthage",
    "Carthage/**",
    "build",
    "build/**",
    "vendor",
    "vendor/**",
    "node_modules",
    "node_modules/**",
    "*.designer.swift",
    "*.generated.*",
    "*.g.swift",
    "*.gen.*",
]

DEFAULT_CRITICAL_WARNING_PATTERNS = [
    r"will be an error in Swift 6",
    r"\bSendable\b",
    r"\bnon[- ]?sendable\b",
    r"\bactor[- ]isolated\b",
    r"\bMainActor\b",
    r"\bdata race\b",
    r"\bconcurrently[- ]executing\b",
]

DEFAULT_CONFIG = {
    "ignore": DEFAULT_IGNORE,
    "xcode_workspace": "",
    "xcode_project": "",
    "xcode_scheme": "",
    "xcode_destination": "generic/platform=macOS",
    "xcode_configuration": "Debug",
    "xcode_code_signing_allowed": False,
    "xcodebuild_arguments": [],
    "swift_build_arguments": [],
    "fail_on_any_warning": False,
    "critical_warning_patterns": DEFAULT_CRITICAL_WARNING_PATTERNS,
    "critical_warning_exclude_patterns": [],
}


def main(argv: Sequence[str]) -> int:
    args = parse_args(argv)
    root = Path(args.root).resolve()
    config_path = root / args.config
    config = load_config(config_path)
    policy = warning_policy(config, config_path)
    command = build_command(root, config)

    result = run_and_collect(command, root, config, policy)
    if result.exit_code != 0:
        emit_error(f"Swift Compile Gate failed: compile command exited with code {result.exit_code}.")
        return result.exit_code

    if result.critical_warnings:
        annotate_critical_warnings(root, result.critical_warnings)
        first = truncate(result.critical_warnings[0].summary(), 240)
        emit_error(
            f"Swift Compile Gate failed: found {len(result.critical_warnings)} critical warning(s). First: {first}"
        )
        return 1

    print("Swift Compile Gate passed: compile completed with no blocking warnings.")
    return 0


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compile a Swift project and fail on configured critical warnings.")
    parser.add_argument("--config", default=".swift-compile-gate.json")
    parser.add_argument("--root", default=".")
    return parser.parse_args(argv)


def load_config(path: Path) -> dict:
    config = dict(DEFAULT_CONFIG)
    config["ignore"] = list(DEFAULT_IGNORE)
    config["xcodebuild_arguments"] = []
    config["swift_build_arguments"] = []
    config["critical_warning_patterns"] = list(DEFAULT_CRITICAL_WARNING_PATTERNS)
    config["critical_warning_exclude_patterns"] = []

    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            emit_file_error(github_path(path), 1, "invalid_config", f"Invalid JSON config: {exc}")
            sys.exit(2)
        if not isinstance(loaded, dict):
            emit_file_error(github_path(path), 1, "invalid_config", "Swift Compile Gate config must be a JSON object.")
            sys.exit(2)
        config.update(loaded)

    config["ignore"] = as_string_list(config.get("ignore"))
    config["xcodebuild_arguments"] = as_string_list(config.get("xcodebuild_arguments"))
    config["swift_build_arguments"] = as_string_list(config.get("swift_build_arguments"))
    config["critical_warning_patterns"] = as_string_list(config.get("critical_warning_patterns"))
    config["critical_warning_exclude_patterns"] = as_string_list(config.get("critical_warning_exclude_patterns"))
    return config


def warning_policy(config: dict, config_path: Path) -> WarningPolicy:
    return WarningPolicy(
        fail_on_any_warning=bool(config.get("fail_on_any_warning", False)),
        include_patterns=compile_patterns(
            config["critical_warning_patterns"], "critical_warning_patterns", config_path
        ),
        exclude_patterns=compile_patterns(
            config["critical_warning_exclude_patterns"],
            "critical_warning_exclude_patterns",
            config_path,
        ),
    )


def compile_patterns(patterns: Sequence[str], key: str, config_path: Path) -> list[Pattern[str]]:
    compiled = []
    for index, pattern in enumerate(patterns, start=1):
        try:
            compiled.append(re.compile(pattern, re.IGNORECASE))
        except re.error as exc:
            emit_file_error(
                github_path(config_path),
                1,
                "invalid_regex",
                f"{key}[{index}] is not a valid regular expression: {exc}",
            )
            sys.exit(2)
    return compiled


def build_command(root: Path, config: dict) -> list[str]:
    project = detect_project(root, config)
    if project.kind == "spm":
        return ["swift", "build", *config["swift_build_arguments"]]

    command = xcodebuild_base_command(project, config)
    command.extend(config["xcodebuild_arguments"])
    command.append("build")
    return command


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
