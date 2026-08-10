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


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    start_directory = Path(args.start_directory).resolve()
    if not start_directory.is_dir():
        print(
            f"Test discovery failed: start directory does not exist: {args.start_directory}",
            file=sys.stderr,
        )
        return 1

    expected = {
        path.relative_to(start_directory).as_posix() for path in start_directory.rglob(args.pattern) if path.is_file()
    }
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
