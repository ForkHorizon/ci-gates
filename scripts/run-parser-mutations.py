#!/usr/bin/env python3
"""Run focused, dependency-free parser mutations and require every one to be killed."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MUTATION_TIMEOUT_SECONDS = 120
UNITTEST_DRIVER = (
    "import io,sys,unittest;"
    "suite=unittest.defaultTestLoader.loadTestsFromName(sys.argv[1]);"
    "result=unittest.TextTestRunner(stream=io.StringIO(),verbosity=0).run(suite);"
    "code=0 if result.testsRun>0 and result.wasSuccessful() else 10 if result.failures and not result.errors else 11;"
    "raise SystemExit(code)"
)


def unittest_command(module: str) -> tuple[str, ...]:
    return ("{python}", "-c", UNITTEST_DRIVER, module, "-q")


@dataclass(frozen=True)
class Mutation:
    name: str
    relative_path: str
    old: str
    new: str
    command: tuple[str, ...]

    @property
    def test_module(self) -> str:
        return self.command[3]


class MutationError(RuntimeError):
    pass


MUTATIONS = (
    Mutation(
        "json-depth-boundary",
        "scripts/code_linter/json_safety.py",
        "if depth > MAX_JSON_DEPTH:\n                return True",
        "if depth >= MAX_JSON_DEPTH:\n                return True",
        unittest_command("tests.linter.syntax_nesting.test_linter_json_recursion_safety"),
    ),
    Mutation(
        "raw-string-masking",
        "scripts/code_linter/scanner.py",
        "if state.raw_terminator:\n            index = consume_active_raw(line, index, state)",
        "if False and state.raw_terminator:\n            index = consume_active_raw(line, index, state)",
        unittest_command("tests.linter.syntax_nesting.test_linter_raw_strings"),
    ),
    Mutation(
        "specialized-syntax-dispatch",
        "scripts/code_linter/syntax.py",
        "return checker(relative, text) if checker else c_style_syntax_issues(relative, text, language)",
        "return c_style_syntax_issues(relative, text, language)",
        unittest_command("tests.linter.coverage.test_linter_language_dispatch"),
    ),
    Mutation(
        "syntax-only-routing",
        "scripts/code_linter/runner.py",
        "if language in SYNTAX_ONLY_LANGUAGES:\n        return issues",
        "if False and language in SYNTAX_ONLY_LANGUAGES:\n        return issues",
        unittest_command("tests.linter.coverage.test_linter_language_dispatch"),
    ),
    Mutation(
        "template-interpolation-state",
        "scripts/code_linter/scanner.py",
        "if state.template_stack:\n        context = state.template_stack[-1]",
        "if False and state.template_stack:\n        context = state.template_stack[-1]",
        unittest_command("tests.linter.syntax_nesting.test_linter_template_interpolations_f10"),
    ),
    Mutation(
        "yaml-duplicate-key",
        "scripts/code_linter/yaml.py",
        'if key in scope["keys"]:\n            return [Issue(relative, line_number, "duplicate_key", f"Duplicate YAML key {key!r}.")]',
        'if False and key in scope["keys"]:\n            return [Issue(relative, line_number, "duplicate_key", f"Duplicate YAML key {key!r}.")]',
        unittest_command("tests.linter.yaml.test_linter_yaml_duplicates"),
    ),
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="List mutation names without running them.")
    parser.add_argument("--mutation", action="append", help="Run only this mutation; may be repeated.")
    return parser.parse_args(argv)


def apply_mutation(root: Path, mutation: Mutation) -> None:
    target = (root / mutation.relative_path).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise MutationError(f"mutation path escapes repository: {mutation.relative_path}") from exc
    try:
        source = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise MutationError(f"unable to read mutation target {mutation.relative_path}: {exc}") from exc
    occurrences = source.count(mutation.old)
    if occurrences != 1:
        raise MutationError(
            f"mutation {mutation.name} expected one source site in {mutation.relative_path}, found {occurrences}"
        )
    target.write_text(source.replace(mutation.old, mutation.new, 1), encoding="utf-8")


def run_focused_tests(root: Path, command_template: tuple[str, ...]) -> tuple[str, str]:
    valid_command = not (
        len(command_template) != 5
        or command_template[:3] != ("{python}", "-c", UNITTEST_DRIVER)
        or not command_template[3].startswith("tests.")
        or command_template[4] != "-q"
    )
    status = "error"
    detail = "unexpected focused unittest command"
    if valid_command:
        command = [sys.executable if item == "{python}" else item for item in command_template]
        try:
            result = subprocess.run(
                command,
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
                timeout=MUTATION_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            detail = f"focused tests timed out after {exc.timeout}s"
        except (OSError, UnicodeError) as exc:
            detail = f"focused tests could not execute or decode output: {exc}"
        else:
            if result.returncode == 0:
                status, detail = "passed", ""
            elif result.returncode == 10:
                status, detail = "failed", ""
            else:
                detail = f"focused unittest driver returned status {result.returncode}"
    return status, detail


def run_mutation(root: Path, mutation: Mutation) -> tuple[str, str]:
    ignore = shutil.ignore_patterns(".git", ".coverage", ".ruff_cache", "graphify-out", "__pycache__")
    with tempfile.TemporaryDirectory(prefix="parser-mutation-") as directory:
        worktree = Path(directory) / "repo"
        shutil.copytree(root, worktree, ignore=ignore)
        apply_mutation(worktree, mutation)
        status, detail = run_focused_tests(worktree, mutation.command)
        if status == "passed":
            return "survived", ""
        if status == "failed":
            return "killed", ""
        return "error", detail


def selected_mutations(names: list[str] | None) -> tuple[Mutation, ...]:
    if not names:
        return MUTATIONS
    by_name = {mutation.name: mutation for mutation in MUTATIONS}
    unknown = [name for name in names if name not in by_name]
    if unknown:
        raise MutationError(f"Unknown mutation: {unknown[0]}")
    if len(names) != len(set(names)):
        raise MutationError("Duplicate mutation selection")
    return tuple(by_name[name] for name in names)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.list:
        for mutation in MUTATIONS:
            print(mutation.name)
        return 0
    try:
        mutations = selected_mutations(args.mutation)
    except MutationError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    killed = 0
    baselines: set[tuple[str, ...]] = set()
    for mutation in mutations:
        if mutation.command not in baselines:
            status, detail = run_focused_tests(ROOT, mutation.command)
            if status != "passed":
                print(f"{mutation.name}: baseline error: {detail}", file=sys.stderr)
                return 1
            baselines.add(mutation.command)
        try:
            status, detail = run_mutation(ROOT, mutation)
        except MutationError as exc:
            print(f"{mutation.name}: error: {exc}", file=sys.stderr)
            return 1
        print(f"{mutation.name}: {status}")
        if status == "killed":
            killed += 1
        elif detail:
            print(detail, file=sys.stderr)
    if killed != len(mutations):
        print(f"Parser mutation testing failed: {killed}/{len(mutations)} killed.", file=sys.stderr)
        return 1
    print(f"Parser mutation testing passed: {killed}/{len(mutations)} killed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
