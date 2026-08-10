#!/usr/bin/env python3
"""Fail when unittest discovery skips a matching test module."""

from __future__ import annotations

import argparse
import sys
import unittest
from collections.abc import Iterable
from pathlib import Path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-directory", default="tests")
    parser.add_argument("--pattern", default="test_*.py")
    return parser.parse_args(argv)


def iter_test_cases(suite: unittest.TestSuite) -> Iterable[unittest.TestCase]:
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from iter_test_cases(item)
        else:
            yield item


def module_path(module_name: str) -> Path:
    return Path(*module_name.split(".")).with_suffix(".py")


def validate_pattern(pattern: str) -> str | None:
    if not pattern or Path(pattern).is_absolute() or "/" in pattern or "\\" in pattern:
        return "pattern must be a non-empty relative filename glob"
    index = 0
    while index < len(pattern):
        if pattern[index] != "[":
            index += 1
            continue
        index += 1
        if index < len(pattern) and pattern[index] == "!":
            index += 1
        if index < len(pattern) and pattern[index] == "]":
            index += 1
        while index < len(pattern) and pattern[index] != "]":
            index += 1
        if index == len(pattern):
            return "pattern contains an unmatched character-class bracket"
        index += 1
    if ".." in Path(pattern).parts:
        return "pattern must not contain a parent directory"
    return None


def inventory_test_files(start_directory: Path, pattern: str) -> set[str] | None:
    try:
        expected = {
            path.relative_to(start_directory).as_posix() for path in start_directory.rglob(pattern) if path.is_file()
        }
    except (NotImplementedError, OSError, ValueError) as exc:
        print(f"Test discovery failed while inventorying pattern {pattern!r}: {exc}", file=sys.stderr)
        return None
    if not expected:
        print(f"Test discovery failed: pattern matched no files: {pattern!r}", file=sys.stderr)
        return None
    return expected


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    pattern_error = validate_pattern(args.pattern)
    if pattern_error:
        print(f"Test discovery failed: {pattern_error}: {args.pattern!r}", file=sys.stderr)
        return 1
    start_directory = Path(args.start_directory).resolve()
    if not start_directory.is_dir():
        print(
            f"Test discovery failed: start directory does not exist: {args.start_directory}",
            file=sys.stderr,
        )
        return 1

    expected = inventory_test_files(start_directory, args.pattern)
    if expected is None:
        return 1
    try:
        suite = unittest.TestLoader().discover(str(start_directory), pattern=args.pattern)
    except Exception as exc:  # pragma: no cover - defensive public-entrypoint guard
        print(f"Test discovery failed while importing modules: {exc}", file=sys.stderr)
        return 1

    cases = list(iter_test_cases(suite))
    discovered = {
        module_path(case.__class__.__module__).as_posix()
        for case in cases
        if case.__class__.__module__ != "unittest.loader"
    }
    missing = sorted(expected - discovered)
    unexpected = sorted(discovered - expected)
    if missing or unexpected:
        print(
            f"Test discovery failed: discovered {len(discovered)}/{len(expected)} matching test module(s).",
            file=sys.stderr,
        )
        if missing:
            print("Missing discovered module(s):", file=sys.stderr)
            for path in missing:
                print(f"- {start_directory / path}", file=sys.stderr)
        if unexpected:
            print("Unexpected discovered module(s):", file=sys.stderr)
            for path in unexpected:
                print(f"- {start_directory / path}", file=sys.stderr)
        return 1

    print(f"Test discovery: {len(discovered)}/{len(expected)} test module(s), {len(cases)} test case(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
