from __future__ import annotations

import argparse
from collections.abc import Iterable, Sequence
from pathlib import Path

from _progress import progress

from .config import (
    LIMIT_DEFAULTS,
    MAX_FILE_BYTES,
    SYNTAX_ONLY_LANGUAGES,
    config_error,
    language_for_path,
    load_config,
)
from .coverage import CoverageGap, PathInventory
from .functions import function_lengths
from .model import Issue
from .nesting import check_nesting_depth
from .paths import collect_path_inventory, matches_ignore_pattern, to_relative
from .structure import check_comment_blocks, check_types_per_file
from .syntax import check_syntax


def main(argv: Sequence[str]) -> int:
    args = parse_args(argv)
    root = Path(args.root).resolve()
    config_path = (root / args.config).resolve()
    if not config_path.is_relative_to(root):
        config_error(config_path, "Code Linter config must be inside the repository.")
    if not config_path.is_file():
        config_error(config_path, "Code Linter config does not exist.")
    config = load_config(config_path)

    inventory = collect_path_inventory(root, config, args)
    if not inventory.selected:
        progress("lint", detail="No matching source files")
    issues = check_paths(root, inventory.selected, config)
    coverage_mode = getattr(args, "coverage_mode", None) or config["coverage_mode"]
    coverage_issues = strict_coverage_issues(inventory, config) if coverage_mode == "strict" else []
    report_config = {**config, "coverage_mode": coverage_mode}
    print_report(
        [*issues, *coverage_issues],
        len(inventory.selected),
        args.mode,
        inventory,
        report_config,
    )
    return 1 if issues or coverage_issues else 0


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check code structure: file and function length, nesting, parameters, comments, types."
    )
    parser.add_argument("--mode", choices=("all", "changed"), default="all")
    parser.add_argument("--base", default="origin/main", help="Base ref for changed mode.")
    parser.add_argument("--head", default="HEAD", help="Head ref for changed mode.")
    parser.add_argument("--config", default=".code-linter.json")
    parser.add_argument("--root", default=".")
    parser.add_argument("--coverage-mode", choices=("report", "strict"), default=None)
    return parser.parse_args(argv)


def read_source(path: Path, relative: Path) -> tuple[str | None, Issue | None]:
    try:
        size = path.stat().st_size
    except OSError as exc:
        return None, Issue(relative, 1, "file_read", f"Unable to stat file: {exc}.")
    if isinstance(size, int) and size > MAX_FILE_BYTES:
        message = f"File is {size} bytes; safety limit is {MAX_FILE_BYTES}."
        return None, Issue(relative, 1, "file_size", message)
    try:
        return path.read_text(encoding="utf-8"), None
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace"), None
    except OSError as exc:
        return None, Issue(relative, 1, "file_read", f"Unable to read file: {exc}.")


def function_issues(relative: Path, text: str, language: str | None, limits: dict[str, int]) -> list[Issue]:
    issues = []
    for name, start_line, length, param_count in function_lengths(text, language):
        if length > limits["max_function_lines"]:
            message = f"{name} has {length} lines; function/method limit is {limits['max_function_lines']}."
            issues.append(Issue(relative, start_line, "function_length", message))
        if param_count > limits["max_parameters"]:
            message = f"Function '{name}' has {param_count} parameters; limit is {limits['max_parameters']}."
            issues.append(Issue(relative, start_line, "max_parameters", message))
    return issues


def source_issues(relative: Path, text: str, language: str | None, limits: dict[str, int]) -> list[Issue]:
    issues = []
    line_count = len(text.splitlines())
    if line_count > limits["max_file_lines"]:
        message = f"File has {line_count} lines; limit is {limits['max_file_lines']}."
        issues.append(Issue(relative, 1, "file_length", message))
    syntax = check_syntax(relative, text, language or "")
    issues.extend(syntax)
    if syntax:
        return issues
    if language in SYNTAX_ONLY_LANGUAGES:
        return issues
    issues.extend(function_issues(relative, text, language, limits))
    issues.extend(check_nesting_depth(relative, text, language, limits["max_nesting_depth"]))
    issues.extend(
        check_comment_blocks(
            relative,
            text,
            language,
            limits["max_comment_lines"],
            limits["max_doc_comment_lines"],
        )
    )
    issues.extend(check_types_per_file(relative, text, language, limits["max_types_per_file"]))
    return issues


def check_path(root: Path, path: Path, config: dict) -> list[Issue]:
    relative = to_relative(root, path)
    text, error = read_source(path, relative)
    if error:
        return [error]
    language = language_for_path(path)
    limits = limits_for_language(config, language or "")
    return source_issues(relative, text or "", language, limits)


def check_paths(root: Path, paths: Iterable[Path], config: dict) -> list[Issue]:
    issues: list[Issue] = []
    listed_paths = list(paths)
    for index, path in enumerate(listed_paths, start=1):
        relative = to_relative(root, path)
        progress("lint", current=index, total=len(listed_paths), detail=str(relative))
        issues.extend(check_path(root, path, config))
    return issues


def limits_for_language(config: dict, language: str) -> dict[str, int]:
    limits = {key: int(config.get(key, fallback)) for key, fallback in LIMIT_DEFAULTS.items()}
    override = config.get("language_overrides", {}).get(language, {})
    if isinstance(override, dict):
        for key in limits:
            if key in override:
                limits[key] = int(override[key])
    return limits


def strict_coverage_issues(inventory: PathInventory, config: dict) -> list[Issue]:
    issues = []
    for gap in unapproved_gaps(inventory.gaps, config):
        issues.append(
            Issue(
                gap.path,
                1,
                "coverage_gap",
                coverage_issue_message(gap),
            )
        )
    return issues


def unapproved_gaps(gaps: Sequence[CoverageGap], config: dict) -> list[CoverageGap]:
    exceptions = config.get("coverage_exceptions", [])
    return [
        gap
        for gap in gaps
        if gap.category in {"ignored_source", "excluded_extension"}
        or not any(matches_ignore_pattern(gap.path, exception["pattern"]) for exception in exceptions)
    ]


def coverage_issue_message(gap: CoverageGap) -> str:
    if gap.category in {"ignored_source", "excluded_extension"}:
        return f"{gap.message} Strict mode does not accept exclusions for structurally supported source."
    return f"{gap.message} Add support or an explicit coverage_exceptions entry with a reason."


def print_coverage_report(inventory: PathInventory, config: dict, coverage_mode: str) -> None:
    if not inventory.gaps:
        print(f"Code Linter coverage: all {len(inventory.selected)} selected source file(s) are covered.")
        return

    approved = len(inventory.gaps) - len(unapproved_gaps(inventory.gaps, config))
    counts: dict[str, int] = {}
    for gap in inventory.gaps:
        counts[gap.category] = counts.get(gap.category, 0) + 1
    breakdown = ", ".join(f"{category}={count}" for category, count in sorted(counts.items()))
    print(
        f"Code Linter coverage: {len(inventory.gaps)} gap(s) ({breakdown}); "
        f"{approved} approved exclusion(s), {len(inventory.selected)} selected file(s)."
    )

    gaps = unapproved_gaps(inventory.gaps, config)
    if coverage_mode == "strict":
        return
    for gap in gaps[:50]:
        print(f"::warning file={gap.path},line=1,title=coverage_gap::{escape_github_message(gap.message)}")
    if len(gaps) > 50:
        print(f"::notice::Code Linter suppressed {len(gaps) - 50} additional coverage gap annotation(s).")


def print_report(
    issues: Sequence[Issue],
    checked_count: int,
    mode: str,
    inventory: PathInventory | None = None,
    config: dict | None = None,
) -> None:
    if inventory is not None:
        settings = config or {"coverage_exceptions": [], "coverage_mode": "report"}
        print_coverage_report(inventory, settings, settings["coverage_mode"])
    if not issues:
        print(f"Code Linter passed: scanned {checked_count} file(s) in {mode} mode.")
        return

    for issue in issues:
        print(f"::error file={issue.path},line={issue.line},title={issue.kind}::{escape_github_message(issue.message)}")

    print(f"Code Linter failed: {len(issues)} issue(s) across {checked_count} scanned file(s) in {mode} mode.")


def escape_github_message(message: str) -> str:
    return message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
