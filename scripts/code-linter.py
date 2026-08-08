#!/usr/bin/env python3
"""Portable Code Linter for humans and AI coding agents.

The checker intentionally uses only Python's standard library so this file can
be copied between repositories and run from GitHub Actions without setup.
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import io
import json
import os
import re
import subprocess
import sys
import tokenize
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Iterable, Sequence

from _progress import progress


LANGUAGE_BY_EXTENSION = {
    ".swift": "swift",
    ".cs": "csharp",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".py": "python",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".go": "go",
    ".rs": "rust",
    ".php": "php",
    ".rb": "ruby",
}

DEFAULT_IGNORE = [
    ".ci-gates",
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
]

LIMIT_DEFAULTS = {
    "max_file_lines": 300,
    "max_function_lines": 50,
    "max_nesting_depth": 4,
    "max_parameters": 5,
    "max_comment_lines": 5,
    "max_doc_comment_lines": 50,
    "max_types_per_file": 2,
}
LIMIT_MAXIMUMS = {
    "max_file_lines": 2_000,
    "max_function_lines": 500,
    "max_nesting_depth": 20,
    "max_parameters": 50,
    "max_comment_lines": 200,
    "max_doc_comment_lines": 500,
    "max_types_per_file": 50,
}

MAX_FILE_BYTES = 1_000_000

DEFAULT_CONFIG = {
    **LIMIT_DEFAULTS,
    "include_extensions": sorted(LANGUAGE_BY_EXTENSION),
    "ignore": DEFAULT_IGNORE,
    "language_overrides": {},
}

CONTROL_WORDS = {
    "catch",
    "do",
    "else",
    "for",
    "foreach",
    "guard",
    "if",
    "lock",
    "repeat",
    "switch",
    "try",
    "using",
    "when",
    "while",
    "with",
}

RUBY_BLOCK_START = re.compile(
    r"^\s*(class|module|if|unless|case|begin|for|while|until)\b|(^|[^A-Za-z0-9_])do\b"
)
RUBY_DEF_PATTERN = re.compile(
    r"\s*def\s+((?:[A-Za-z_][A-Za-z0-9_]*(?:::|\.))?"
    r"(?:[A-Za-z_][A-Za-z0-9_]*[!?=]?|\[\]=?|[-+*/%<>=~&|^`]+))"
)

# Keywords whose `{` adds a level of logical nesting. `else` is included so an
# if/else chain keeps both branches at the same depth. Anchored at the start of
# the statement (a leading `}` is allowed, for `} else {`) so the `try` in
# `let x = try foo()` isn't read as opening a block.
NESTING_KEYWORD = re.compile(
    r"^\s*(?:\}\s*)*"
    r"(?:[A-Za-z_][A-Za-z0-9_]*:\s*)?(?:await\s+)?"
    r"\b(?:if|else|for|foreach|while|switch|try|catch|guard|do|repeat|when|"
    r"lock|using|synchronized|loop|match|select|defer)\b"
)

# Documentation comments use their own, more generous bounded block limit.
DOC_LINE_PREFIXES = ("///", "//!")


@dataclass(frozen=True)
class Issue:
    path: str
    line: int
    kind: str
    message: str


@dataclass
class FunctionBlock:
    name: str
    start_line: int
    parent_depth: int
    param_count: int = 0


@dataclass
class CStyleScanState:
    block_depth: int = 0
    quote: str | None = None


@dataclass
class BraceEvent:
    kind: str  # "trigger", "open" or "close"
    line: int
    triggered: bool = False
    match: re.Match[str] | None = None


def main(argv: Sequence[str]) -> int:
    args = parse_args(argv)
    root = Path(args.root).resolve()
    config_path = (root / args.config).resolve()
    if not config_path.is_relative_to(root):
        config_error(config_path, "Code Linter config must be inside the repository.")
    if not config_path.is_file():
        config_error(config_path, "Code Linter config does not exist.")
    config = load_config(config_path)

    paths = collect_paths(root, config, args)
    if not paths:
        progress("lint", detail="No matching source files")
    issues = check_paths(root, paths, config)
    print_report(issues, len(paths), args.mode)
    return 1 if issues else 0


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check code structure: file and function length, nesting, parameters, comments, types."
    )
    parser.add_argument("--mode", choices=("all", "changed"), default="all")
    parser.add_argument(
        "--base", default="origin/main", help="Base ref for changed mode."
    )
    parser.add_argument("--head", default="HEAD", help="Head ref for changed mode.")
    parser.add_argument("--config", default=".code-linter.json")
    parser.add_argument("--root", default=".")
    return parser.parse_args(argv)


def load_config(path: Path) -> dict:
    config = dict(DEFAULT_CONFIG)
    config["ignore"] = list(DEFAULT_IGNORE)
    config["include_extensions"] = list(DEFAULT_CONFIG["include_extensions"])
    config["language_overrides"] = {}

    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(
                f"::error file={github_path(path)}::Invalid JSON config: {exc}",
                file=sys.stderr,
            )
            sys.exit(2)
        if not isinstance(loaded, dict):
            print(
                f"::error file={github_path(path)}::Code Linter config must be a JSON object",
                file=sys.stderr,
            )
            sys.exit(2)
        unknown = sorted(set(loaded) - set(DEFAULT_CONFIG))
        if unknown:
            config_error(path, f"Unknown config key(s): {', '.join(unknown)}.")
        loaded_ignore = loaded.get("ignore")
        config.update(loaded)
        if loaded_ignore is not None:
            config["ignore"] = merge_ignore(loaded_ignore, path)
            reject_blanket_ignores(config["ignore"], path)

    for key, fallback in LIMIT_DEFAULTS.items():
        config[key] = config_int(config, key, fallback, path)
    config["include_extensions"] = [
        (ext if ext.startswith(".") else f".{ext}").lower()
        for ext in config_list(
            config, "include_extensions", LANGUAGE_BY_EXTENSION, path
        )
    ]
    unsupported = sorted(set(config["include_extensions"]) - set(LANGUAGE_BY_EXTENSION))
    if unsupported:
        config_error(
            path,
            f"Unsupported source extension(s): {', '.join(unsupported)}.",
        )
    if not config["include_extensions"]:
        config_error(path, "'include_extensions' must not be empty.")
    overrides = config.get("language_overrides", {})
    if not isinstance(overrides, dict):
        config_error(path, "'language_overrides' must be a JSON object.")
    valid_languages = set(LANGUAGE_BY_EXTENSION.values())
    validated_overrides = {}
    for language, values in overrides.items():
        if language not in valid_languages:
            config_error(path, f"Unknown language override: {language!r}.")
        if not isinstance(values, dict):
            config_error(path, f"Override for {language!r} must be a JSON object.")
        unknown = sorted(set(values) - set(LIMIT_DEFAULTS))
        if unknown:
            config_error(
                path,
                f"Unknown {language!r} override key(s): {', '.join(unknown)}.",
            )
        validated_overrides[language] = {
            key: config_int(values, key, LIMIT_DEFAULTS[key], path) for key in values
        }
    config["language_overrides"] = validated_overrides
    return config


def config_error(path: Path, message: str) -> None:
    print(f"::error file={github_path(path)}::{message}", file=sys.stderr)
    sys.exit(2)


def merge_ignore(loaded_ignore: object, path: Path) -> list[str]:
    if not isinstance(loaded_ignore, list) or not all(
        isinstance(item, str) for item in loaded_ignore
    ):
        config_error(path, "'ignore' must be a JSON array of strings.")
    merged = list(DEFAULT_IGNORE)
    for item in loaded_ignore:  # type: ignore[union-attr]
        if item not in merged:
            merged.append(item)
    return merged


def reject_blanket_ignores(patterns: Sequence[str], path: Path) -> None:
    forbidden = {"*", "**", "**/*"}
    for extension in LANGUAGE_BY_EXTENSION:
        forbidden.update({f"*{extension}", f"**{extension}", f"**/*{extension}"})
    invalid = []
    for pattern in patterns:
        normalized = (
            pattern.strip().replace("\\", "/").removeprefix("./").removeprefix("/")
        )
        if normalized in forbidden:
            invalid.append(pattern)
    if invalid:
        config_error(
            path,
            f"Blanket source ignore pattern(s) are not allowed: {', '.join(invalid)}.",
        )


def config_list(
    config: dict, key: str, fallback: Iterable[str], path: Path
) -> list[str]:
    value = config.get(key, fallback)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        config_error(path, f"'{key}' must be a JSON array of strings.")
    return list(value)  # type: ignore[arg-type]


def config_int(config: dict, key: str, fallback: int, path: Path) -> int:
    value = config.get(key, fallback)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        config_error(path, f"'{key}' must be a positive integer, got {value!r}.")
    if value > LIMIT_MAXIMUMS[key]:
        config_error(
            path, f"'{key}' must not exceed {LIMIT_MAXIMUMS[key]}, got {value}."
        )
    return value


def collect_paths(root: Path, config: dict, args: argparse.Namespace) -> list[Path]:
    candidates = (
        changed_paths(root, args.base, args.head)
        if args.mode == "changed"
        else all_repo_paths(root)
    )
    if args.mode == "changed":
        config_relative = Path(args.config).as_posix().removeprefix("./")
        changed = {to_relative(root, path) for path in candidates}
        policy_changed = config_relative in changed or any(
            path.startswith(".github/workflows/") for path in changed
        )
        if policy_changed:
            candidates = all_repo_paths(root)

    include_extensions = set(config["include_extensions"])
    paths = []
    for path in candidates:
        if path.suffix.lower() not in include_extensions:
            continue
        if path.is_symlink():
            config_error(path, "Source symlinks are not allowed.")
        if not path.is_file():
            continue
        relative = to_relative(root, path)
        if should_ignore(relative, config["ignore"]):
            continue
        paths.append(path)
    return sorted(paths)


def changed_paths(root: Path, base: str, head: str) -> list[Path]:
    diff_args = [
        "git",
        "diff",
        "-z",
        "--name-only",
        "--diff-filter=ACMRT",
        f"{base}...{head}",
    ]
    result = subprocess.run(
        diff_args, cwd=root, text=True, capture_output=True, check=False
    )
    if result.returncode != 0:
        diff_args = [
            "git",
            "diff",
            "-z",
            "--name-only",
            "--diff-filter=ACMRT",
            base,
            head,
        ]
        result = subprocess.run(
            diff_args, cwd=root, text=True, capture_output=True, check=False
        )
    if result.returncode != 0:
        stderr = result.stderr.strip() or result.stdout.strip()
        print(f"::error::Unable to collect changed files: {stderr}", file=sys.stderr)
        sys.exit(2)
    return [root / path for path in result.stdout.split("\0") if path]


def all_repo_paths(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode == 0:
        return [root / path for path in result.stdout.split("\0") if path]

    paths = []
    for current_root, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name != ".git"]
        for filename in filenames:
            paths.append(Path(current_root) / filename)
    return paths


def check_paths(root: Path, paths: Iterable[Path], config: dict) -> list[Issue]:
    issues: list[Issue] = []
    paths = list(paths)
    for index, path in enumerate(paths, start=1):
        relative = to_relative(root, path)
        progress("lint", current=index, total=len(paths), detail=str(relative))
        language = LANGUAGE_BY_EXTENSION.get(path.suffix.lower())

        try:
            size = path.stat().st_size
        except OSError as exc:
            issues.append(
                Issue(relative, 1, "file_read", f"Unable to stat file: {exc}.")
            )
            continue
        if isinstance(size, int) and size > MAX_FILE_BYTES:
            issues.append(
                Issue(
                    relative,
                    1,
                    "file_size",
                    f"File is {size} bytes; safety limit is {MAX_FILE_BYTES}.",
                )
            )
            continue

        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            issues.append(
                Issue(relative, 1, "file_read", f"Unable to read file: {exc}.")
            )
            continue

        lines = text.splitlines()
        limits = limits_for_language(config, language or "")
        max_file_lines = limits["max_file_lines"]
        max_function_lines = limits["max_function_lines"]
        max_nesting_depth = limits["max_nesting_depth"]
        max_parameters = limits["max_parameters"]
        max_comment_lines = limits["max_comment_lines"]
        max_doc_comment_lines = limits["max_doc_comment_lines"]
        max_types_per_file = limits["max_types_per_file"]

        if len(lines) > max_file_lines:
            issues.append(
                Issue(
                    path=relative,
                    line=1,
                    kind="file_length",
                    message=f"File has {len(lines)} lines; limit is {max_file_lines}.",
                )
            )

        syntax = check_syntax(relative, text, language or "")
        issues.extend(syntax)
        if syntax:
            continue

        for name, start_line, length, param_count in function_lengths(text, language):
            if length > max_function_lines:
                issues.append(
                    Issue(
                        path=relative,
                        line=start_line,
                        kind="function_length",
                        message=(
                            f"{name} has {length} lines; function/method limit is {max_function_lines}."
                        ),
                    )
                )
            if param_count > max_parameters:
                issues.append(
                    Issue(
                        path=relative,
                        line=start_line,
                        kind="max_parameters",
                        message=(
                            f"Function '{name}' has {param_count} parameters; limit is {max_parameters}."
                        ),
                    )
                )

        issues.extend(check_nesting_depth(relative, text, language, max_nesting_depth))
        issues.extend(
            check_comment_blocks(
                relative,
                text,
                language,
                max_comment_lines,
                max_doc_comment_lines,
            )
        )
        issues.extend(
            check_types_per_file(relative, text, language, max_types_per_file)
        )
    return issues


def limits_for_language(config: dict, language: str) -> dict[str, int]:
    limits = {
        key: int(config.get(key, fallback)) for key, fallback in LIMIT_DEFAULTS.items()
    }
    override = config.get("language_overrides", {}).get(language, {})
    if isinstance(override, dict):
        for key in limits:
            if key in override:
                limits[key] = int(override[key])
    return limits


def check_syntax(relative: str, text: str, language: str) -> list[Issue]:
    if language == "python":
        try:
            ast.parse(text)
        except SyntaxError as exc:
            return [
                Issue(
                    relative,
                    exc.lineno or 1,
                    "syntax_error",
                    f"Python syntax error: {exc.msg}.",
                )
            ]
        return []
    if language == "ruby":
        return ruby_syntax_issues(relative, text)
    return c_style_syntax_issues(relative, text, language)


def c_style_syntax_issues(relative: str, text: str, language: str) -> list[Issue]:
    state = CStyleScanState()
    depth = 0
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        clean, _ = scan_c_style_line(raw_line, language, state)
        for char in clean:
            depth += char == "{"
            depth -= char == "}"
            if depth < 0:
                return [
                    Issue(
                        relative,
                        line_number,
                        "syntax_error",
                        "Unexpected closing brace.",
                    )
                ]
    if state.block_depth or state.quote:
        return [
            Issue(
                relative,
                max(1, len(text.splitlines())),
                "syntax_error",
                "Unterminated comment or string.",
            )
        ]
    if depth:
        return [
            Issue(
                relative,
                max(1, len(text.splitlines())),
                "syntax_error",
                f"File has {depth} unclosed brace(s).",
            )
        ]
    return []


def function_lengths(text: str, language: str) -> list[tuple[str, int, int, int]]:
    if language == "python":
        return python_function_lengths(text)
    if language == "ruby":
        return ruby_function_lengths(text)
    return brace_function_lengths(text, language)


def python_function_lengths(text: str) -> list[tuple[str, int, int, int]]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []

    results = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end_line = getattr(node, "end_lineno", node.lineno)
            pos_args = getattr(node.args, "posonlyargs", [])
            pcount = (
                len(pos_args)
                + len(node.args.args)
                + len(node.args.kwonlyargs)
                + (1 if node.args.vararg else 0)
                + (1 if node.args.kwarg else 0)
            )
            results.append((node.name, node.lineno, end_line - node.lineno + 1, pcount))
    return results


def ruby_code_lines(text: str) -> list[tuple[int, str]]:
    lines = []
    heredoc_end: str | None = None
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        if heredoc_end:
            if raw_line.strip() == heredoc_end:
                heredoc_end = None
            lines.append((line_number, ""))
            continue
        match = re.search(r"<<[-~]?(?:['\"])?([A-Z][A-Za-z0-9_]*)", raw_line)
        if match:
            heredoc_end = match.group(1)
        lines.append((line_number, strip_ruby_comment(raw_line)))
    return lines


def ruby_block_start(line: str) -> bool:
    stripped = line.strip()
    if re.match(r"(?:class|module)\b", stripped):
        return True
    match = RUBY_DEF_PATTERN.match(stripped)
    if match:
        return not is_endless_ruby_method(stripped[match.end() :])
    return RUBY_BLOCK_START.search(line) is not None


def ruby_syntax_issues(relative: str, text: str) -> list[Issue]:
    stack: list[int] = []
    for line_number, line in ruby_code_lines(text):
        if ruby_block_start(line):
            stack.append(line_number)
        for _ in re.finditer(r"(^|[^A-Za-z0-9_])end([^A-Za-z0-9_]|$)", line):
            if not stack:
                return [
                    Issue(
                        relative, line_number, "syntax_error", "Unexpected Ruby 'end'."
                    )
                ]
            stack.pop()
    if stack:
        return [
            Issue(relative, stack[-1], "syntax_error", "Ruby block is missing 'end'.")
        ]
    return []


def ruby_parameter_count(signature: str, name: str, first_line: str) -> int:
    after_name = first_line[first_line.find(name) + len(name) :].strip()
    if after_name.startswith("("):
        return count_params_in_signature(signature, name)
    if not after_name or is_endless_ruby_method(after_name):
        return 0
    return count_params_in_signature(f"({after_name})")


def ruby_function_lengths(text: str) -> list[tuple[str, int, int, int]]:
    stack: list[tuple[str, str, int, int]] = []
    results = []
    source_lines = text.splitlines()

    for line_number, line in ruby_code_lines(text):
        stripped = line.strip()
        if not stripped:
            continue

        def_match = RUBY_DEF_PATTERN.match(line)
        if def_match:
            name = def_match.group(1)
            signature = "\n".join(source_lines[line_number - 1 :])
            pcount = ruby_parameter_count(signature, name, line)
            if is_endless_ruby_method(line[def_match.end() :]):
                results.append((name, line_number, 1, pcount))
            else:
                stack.append(("def", name, line_number, pcount))
            continue

        if RUBY_BLOCK_START.search(line):
            stack.append(("block", "", line_number, 0))

        end_count = len(re.findall(r"(^|[^A-Za-z0-9_])end([^A-Za-z0-9_]|$)", line))
        for _ in range(end_count):
            if not stack:
                break
            kind, name, start_line, pcount = stack.pop()
            if kind == "def":
                results.append((name, start_line, line_number - start_line + 1, pcount))

    for kind, name, start_line, pcount in reversed(stack):
        if kind == "def":
            results.append(
                (name, start_line, len(source_lines) - start_line + 1, pcount)
            )
    return results


def is_endless_ruby_method(after_name: str) -> bool:
    """`def foo = 1` is a one-liner; `def foo(a = 1)` is not — the `=` in a
    default argument sits inside the parameter list, so skip that first."""
    rest = after_name.lstrip()
    if rest.startswith("("):
        depth = 0
        for index, char in enumerate(rest):
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    rest = rest[index + 1 :]
                    break
        else:
            return False
    rest = rest.lstrip()
    return rest.startswith("=") and not rest.startswith(("==", "=~"))


def brace_function_lengths(text: str, language: str) -> list[tuple[str, int, int, int]]:
    results = []
    active: list[FunctionBlock] = []
    pending: tuple[str, int, int, bool] | None = None
    pending_sig: list[str] = []
    brace_depth = 0
    for line_number, (raw_line, clean, _) in enumerate(
        scan_c_style_lines(text, language), start=1
    ):
        stripped = clean.strip()
        depth_before = brace_depth

        detected = detect_brace_function(stripped, language)
        if detected:
            pending_sig = [clean]
            pcount = count_params_in_signature(clean, detected, language)
            is_arrow_candidate = bool(
                language in {"javascript", "typescript"}
                and "=>" not in clean
                and re.search(r"\b(?:const|let|var)\s+\w+\s*=", clean)
            )
            pending = (detected, line_number, pcount, is_arrow_candidate)
        elif pending:
            pending_sig.append(clean)
            full_sig = "\n".join(pending_sig)
            pcount = count_params_in_signature(full_sig, pending[0], language)
            pending = (pending[0], pending[1], pcount, pending[3])

        opens = clean.count("{")
        closes = clean.count("}")
        full_sig = "\n".join(pending_sig)
        pending_confirmed = pending is not None and (not pending[3] or "=>" in full_sig)

        if pending and pending_confirmed and opens:
            name, start_line, pcount, _ = pending
            active.append(
                FunctionBlock(
                    name=name,
                    start_line=start_line,
                    parent_depth=depth_before,
                    param_count=pcount,
                )
            )
            pending = None
            pending_sig = []

        if (
            pending
            and pending_confirmed
            and opens == 0
            and closes == 0
            and ("=" in stripped or "=>" in stripped)
        ):
            if not (
                stripped.endswith(",")
                or (len(pending_sig) > 1 and not stripped.endswith(";"))
            ):
                name, start_line, pcount, _ = pending
                results.append((name, start_line, 1, pcount))
                pending = None
                pending_sig = []

        if pending and stripped.endswith(";"):
            name, start_line, pcount, _ = pending
            declaration = (
                language in {"csharp", "java"}
                and re.search(r"\b(?:abstract|extern|native)\b", full_sig)
            ) or (
                language == "typescript"
                and re.search(r"\bdeclare\s+function\b", full_sig)
            )
            if declaration:
                results.append((name, start_line, line_number - start_line + 1, pcount))
            pending = None
            pending_sig = []

        if pending and closes and not opens:
            name, start_line, pcount, _ = pending
            results.append((name, start_line, max(1, line_number - start_line), pcount))
            pending = None
            pending_sig = []

        brace_depth += opens - closes
        brace_depth = max(brace_depth, 0)

        while active and brace_depth <= active[-1].parent_depth:
            block = active.pop()
            results.append(
                (
                    block.name,
                    block.start_line,
                    line_number - block.start_line + 1,
                    block.param_count,
                )
            )

    for block in reversed(active):
        results.append(
            (
                block.name,
                block.start_line,
                len(text.splitlines()) - block.start_line + 1,
                block.param_count,
            )
        )
    return results


def count_params_in_signature(
    signature_line: str, name: str | None = None, language: str = ""
) -> int:
    signature_clean = strip_strings(signature_line, language)
    start = -1
    if name == "<anonymous>" and language in {"javascript", "typescript"}:
        arrow = re.search(r"\(([^()]*)\)\s*=>", signature_clean)
        if arrow:
            start = arrow.start()
        else:
            bare = re.search(r"\b[A-Za-z_$][A-Za-z0-9_$]*\s*=>", signature_clean)
            return 1 if bare else 0
    if name and name.isidentifier():
        # Anchor on the paren that follows the function name so a Go receiver
        # (`func (s *Server) Handle(a, b int)`) isn't mistaken for the parameters.
        anchored = re.search(
            r"\b" + re.escape(name) + r"\b\s*(?:<[^<>]*>|\[[^\[\]]*\])?\s*\(",
            signature_clean,
        )
        if anchored:
            start = anchored.end() - 1
    if start == -1:
        start = signature_clean.find("(")
    if start == -1:
        return 0

    depth = 0
    end = -1
    for index in range(start, len(signature_clean)):
        char = signature_clean[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                end = index
                break

    if end <= start:
        return 0

    params_str = signature_clean[start + 1 : end].strip()
    if not params_str:
        return 0

    depth = 0
    count = 1
    for char in params_str:
        if char in "(<{[":
            depth += 1
        elif char in ")>}]":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            count += 1

    return count


def check_nesting_depth(
    relative: str, text: str, language: str, max_depth: int
) -> list[Issue]:
    if language == "python":
        return python_nesting_issues(relative, text, max_depth)
    if language == "ruby":
        return ruby_nesting_issues(relative, text, max_depth)
    issues = c_style_nesting_issues(relative, text, language, max_depth)
    issues.extend(unbraced_nesting_issues(relative, text, language, max_depth))
    if language == "php":
        issues.extend(php_alternative_nesting_issues(relative, text, max_depth))
    return issues


def nesting_issue(relative: str, line: int, depth: int, max_depth: int) -> Issue:
    return Issue(
        path=relative,
        line=line,
        kind="nesting_depth",
        message=f"Nesting depth is {depth}; limit is {max_depth}.",
    )


def python_nesting_issues(relative: str, text: str, max_depth: int) -> list[Issue]:
    issues: list[Issue] = []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return issues

    match_types = (
        ast.If,
        ast.For,
        ast.AsyncFor,
        ast.While,
        ast.Try,
        ast.With,
        ast.AsyncWith,
        getattr(ast, "Match", type(None)),
    )

    def walk(node: ast.AST, depth: int, parent: ast.AST | None = None) -> None:
        for child in ast.iter_child_nodes(node):
            next_depth = depth
            if isinstance(child, match_types):
                is_elif = (
                    isinstance(child, ast.If)
                    and isinstance(parent, ast.If)
                    and any(child is other for other in parent.orelse)
                )
                if not is_elif:
                    next_depth = depth + 1
                    if next_depth > max_depth:
                        issues.append(
                            nesting_issue(
                                relative,
                                getattr(child, "lineno", 1),
                                next_depth,
                                max_depth,
                            )
                        )
            walk(child, next_depth, parent=child)

    walk(tree, 0)
    return issues


def ruby_nesting_issues(relative: str, text: str, max_depth: int) -> list[Issue]:
    issues = []
    frames: list[bool] = []
    depth = 0
    for line_number, line in ruby_code_lines(text):
        stripped = line.strip()
        def_match = RUBY_DEF_PATTERN.match(stripped)
        endless = bool(
            def_match and is_endless_ruby_method(stripped[def_match.end() :])
        )
        declaration = None if endless else re.match(r"(?:def|class|module)\b", stripped)
        logical = not declaration and RUBY_BLOCK_START.search(line) is not None
        if declaration or logical:
            frames.append(logical)
            if logical:
                depth += 1
                if depth > max_depth:
                    issues.append(
                        nesting_issue(relative, line_number, depth, max_depth)
                    )
        for _ in re.finditer(r"(^|[^A-Za-z0-9_])end([^A-Za-z0-9_]|$)", line):
            if frames and frames.pop():
                depth -= 1
    return issues


def unbraced_nesting_issues(
    relative: str, text: str, language: str, max_depth: int
) -> list[Issue]:
    if language not in {"csharp", "java", "javascript", "typescript", "kotlin"}:
        return []
    issues = []
    indents: list[int] = []
    for line_number, (_, clean, _) in enumerate(
        scan_c_style_lines(text, language), start=1
    ):
        if not clean.strip():
            continue
        indent = len(clean) - len(clean.lstrip())
        while indents and indent <= indents[-1]:
            indents.pop()
        match = NESTING_KEYWORD.search(clean)
        if not match or "{" in clean[match.end() :] or clean.rstrip().endswith(";"):
            continue
        indents.append(indent)
        if len(indents) > max_depth:
            issues.append(nesting_issue(relative, line_number, len(indents), max_depth))
    return issues


def php_alternative_nesting_issues(
    relative: str, text: str, max_depth: int
) -> list[Issue]:
    issues = []
    depth = 0
    state = CStyleScanState()
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        clean, _ = scan_c_style_line(raw_line, "php", state)
        if re.search(r"\b(?:endif|endforeach|endfor|endwhile|endswitch)\s*;", clean):
            depth = max(0, depth - 1)
        if re.search(r"^\s*(?:if|foreach|for|while|switch)\b.*:\s*$", clean):
            depth += 1
            if depth > max_depth:
                issues.append(nesting_issue(relative, line_number, depth, max_depth))
    return issues


def brace_events(
    text: str, language: str, trigger: re.Pattern[str]
) -> Iterable[BraceEvent]:
    """Walks `{`/`}` pairs, tagging each pair with whether `trigger` opened it.

    The trigger may sit on an earlier line than its brace (Allman style), so a
    match is carried forward until a brace, a statement-ending `;` outside
    parentheses, or an assignment consumes it.
    """
    frames: list[bool] = []
    pending: re.Match[str] | None = None
    for line_no, (_, clean, _) in enumerate(
        scan_c_style_lines(text, language), start=1
    ):
        match = trigger.search(clean)
        if match:
            pending = match
            yield BraceEvent("trigger", line_no, match=match)
        min_index = match.end() if match else (0 if pending else None)
        parens = 0
        assigned = False
        for index, char in enumerate(clean):
            live = min_index is not None and index >= min_index
            if char == "(":
                parens += 1
            elif char == ")":
                parens = max(0, parens - 1)
            elif char == "=" and live and parens == 0:
                assigned = True
            elif char == "{":
                triggered = pending is not None and live
                frames.append(triggered)
                yield BraceEvent(
                    "open", line_no, triggered, pending if triggered else None
                )
                pending, min_index = None, None
            elif char == "}":
                yield BraceEvent("close", line_no, frames.pop() if frames else False)
                if live:
                    pending, min_index = None, None
            elif char == ";" and live and parens == 0:
                pending, min_index = None, None
        if assigned and pending is not None:
            # `type Alias = string` / `let x = y` completed without a block.
            pending = None


def c_style_nesting_issues(
    relative: str, text: str, language: str, max_depth: int
) -> list[Issue]:
    """Counts only braces a control-flow keyword opened.

    Counting every `{` made a type declaration, a method and each enclosing
    closure eat a level, so an ordinary `if` inside a SwiftUI body reported
    depth 7. Only `if`/`for`/`while`/... blocks are nesting a reader has to
    track, so those are the only frames that raise the depth.
    """
    issues: list[Issue] = []
    depth = 0
    for event in brace_events(text, language, NESTING_KEYWORD):
        if not event.triggered:
            continue
        if event.kind == "open":
            depth += 1
            if depth > max_depth:
                issues.append(nesting_issue(relative, event.line, depth, max_depth))
        elif event.kind == "close":
            depth -= 1
    return issues


def python_comment_kinds(text: str) -> list[str | None]:
    """Real comment lines, via tokenize — a `#` opening a line inside a triple
    quoted string is string data, not a comment, and used to be counted."""
    lines = text.splitlines()
    comment_rows: dict[int, str] = {}
    try:
        tokens = tokenize.generate_tokens(io.StringIO(text).readline)
        for token in tokens:
            row, column = token.start
            if token.type != tokenize.COMMENT or row > len(lines):
                continue
            if lines[row - 1][:column].strip():
                continue  # trailing comment after code
            if row == 1 and token.string.startswith("#!"):
                continue
            comment_rows[row] = "doc" if token.string.startswith("#:") else "prose"
    except (tokenize.TokenError, IndentationError, SyntaxError):
        # Unparseable file: fall back to the prefix scan rather than reporting nothing.
        return [
            (
                "doc"
                if line.strip().startswith("#:")
                else "prose"
                if line.strip().startswith("#")
                and not (index == 0 and line.strip().startswith("#!"))
                else None
            )
            for index, line in enumerate(lines)
        ]
    return [comment_rows.get(row) for row in range(1, len(lines) + 1)]


def comment_line_kinds(text: str, language: str) -> list[str | None]:
    """Classify prose-only and documentation-only comment lines.

    Documentation comments (`///`, `//!`, `/** */`, `#:`) receive a separate
    limit so API documentation is allowed but cannot grow without bound.
    """
    if language == "python":
        return python_comment_kinds(text)

    if language == "ruby":
        flags = []
        for index, line in enumerate(text.splitlines()):
            stripped = line.strip()
            is_shebang = index == 0 and stripped.startswith("#!")
            flags.append(
                "prose" if stripped.startswith("#") and not is_shebang else None
            )
        return flags

    flags = []
    in_doc_block = False
    for raw, _, is_comment in scan_c_style_lines(text, language):
        stripped = raw.strip()
        if in_doc_block:
            is_doc = True
            in_doc_block = "*/" not in stripped
        elif stripped.startswith("/**"):
            is_doc = True
            in_doc_block = "*/" not in stripped[3:]
        else:
            is_doc = stripped.startswith(DOC_LINE_PREFIXES)
        flags.append(
            "doc" if is_comment and is_doc else "prose" if is_comment else None
        )
    return flags


def comment_line_flags(text: str, language: str) -> list[bool]:
    return [kind == "prose" for kind in comment_line_kinds(text, language)]


def is_license_header(lines: Sequence[str]) -> bool:
    header = "\n".join(lines).lower()
    return any(
        token in header
        for token in ("spdx-license-identifier", "copyright", "licensed under")
    )


def check_comment_blocks(
    relative: str,
    text: str,
    language: str,
    max_comment_lines: int,
    max_doc_comment_lines: int = 50,
) -> list[Issue]:
    issues: list[Issue] = []
    current_start: int | None = None
    current_kind: str | None = None
    count = 0
    lines = text.splitlines()

    def flush() -> None:
        if current_start is None or current_kind is None:
            return
        limit = max_doc_comment_lines if current_kind == "doc" else max_comment_lines
        header_lines = lines[current_start - 1 : current_start - 1 + count]
        if count > limit and not (
            current_start == 1 and is_license_header(header_lines)
        ):
            issues.append(
                Issue(
                    path=relative,
                    line=current_start or 1,
                    kind="doc_comment_block"
                    if current_kind == "doc"
                    else "comment_block",
                    message=f"{current_kind.title()} comment block has {count} lines; limit is {limit}.",
                )
            )

    for line_no, kind in enumerate(comment_line_kinds(text, language), start=1):
        if kind:
            if current_kind and kind != current_kind:
                current_kind = "prose"
            if count == 0:
                current_start = line_no
                current_kind = kind
            count += 1
            continue
        if current_kind and not lines[line_no - 1].strip():
            continue
        flush()
        count = 0
        current_start = None
        current_kind = None

    flush()
    return issues


TYPE_PATTERNS = {
    "csharp": r"\b(?:class|struct|interface|enum|record(?:\s+(?:class|struct))?)\s+([A-Za-z_][A-Za-z0-9_]*)",
    "swift": r"\b(?:class|struct|enum|actor|protocol)\s+([A-Za-z_][A-Za-z0-9_]*)",
    "go": r"\btype\s+([A-Za-z_][A-Za-z0-9_]*)\b",
    # Bare `type X = …` aliases are omitted on purpose: they cost a reader
    # nothing, and three of them in a file is normal, not a structure problem.
    "typescript": r"\b(?:class|interface|enum)\s+([A-Za-z_$][A-Za-z0-9_$]*)",
    "javascript": r"\bclass\s+([A-Za-z_$][A-Za-z0-9_$]*)",
    "rust": r"\b(?:struct|enum|trait|union)\s+([A-Za-z_][A-Za-z0-9_]*)",
    "php": r"\b(?:class|interface|enum|trait)\s+([A-Za-z_][A-Za-z0-9_]*)",
    "kotlin": r"\b(?:class|interface|object|enum\s+class|typealias)\s+([A-Za-z_][A-Za-z0-9_]*)",
    "java": r"\b(?:class|interface|enum|record)\s+([A-Za-z_][A-Za-z0-9_]*)",
}

FALLBACK_TYPE_PATTERN = (
    r"\b(?:class|struct|interface|enum|actor)\s+([A-Za-z_][A-Za-z0-9_]*)"
)


def brace_type_declarations(text: str, language: str) -> list[tuple[str, int]]:
    """Top-level type declarations only.

    A helper struct or enum nested inside the type it serves is one unit of
    reading, not two, so it doesn't count. Namespace/extension wrappers aren't
    type declarations either, so C# and Swift files still get counted properly.
    """
    pattern = re.compile(TYPE_PATTERNS.get(language, FALLBACK_TYPE_PATTERN))
    types: list[tuple[str, int]] = []
    inside_type = 0
    for event in brace_events(text, language, pattern):
        if event.kind == "trigger":
            if inside_type == 0 and event.match is not None:
                types.append((event.match.group(1), event.line))
        elif event.triggered:
            inside_type += 1 if event.kind == "open" else -1
    return types


def check_types_per_file(
    relative: str, text: str, language: str, max_types: int
) -> list[Issue]:
    issues: list[Issue] = []
    types: list[tuple[str, int]] = []
    if language == "python":
        try:
            tree = ast.parse(text)
        except SyntaxError:
            tree = None
        if tree is not None:
            types = [
                (node.name, node.lineno)
                for node in tree.body
                if isinstance(node, ast.ClassDef)
            ]
    else:
        types = brace_type_declarations(text, language)

    if len(types) > max_types:
        first_violator = types[max_types]
        type_names = ", ".join(t[0] for t in types)
        issues.append(
            Issue(
                path=relative,
                line=first_violator[1],
                kind="types_per_file",
                message=f"File defines {len(types)} types ({type_names}); limit is {max_types}.",
            )
        )
    return issues


def detect_brace_function(line: str, language: str) -> str | None:  # noqa: PLR0911, PLR0912 - per-language dispatch
    if not line:
        return None

    first_word = re.match(r"(?:@\w+\s+)*(?:[A-Za-z_][A-Za-z0-9_]*)", line)
    if first_word and first_word.group(0).split()[0] in CONTROL_WORDS:
        return None

    if language == "swift":
        match = re.search(
            r"\bfunc\s+(?:`([^`]+)`|([A-Za-z_][A-Za-z0-9_]*)|([^\s<(]+))",
            line,
        )
        if match:
            return (match.group(1) or match.group(2) or match.group(3)).strip("`")
        if re.search(r"\bsubscript\s*[<(]", line):
            return "subscript"
        if re.search(r"\binit\s*\(", line):
            return "init"
        if re.search(r"\bdeinit\b", line):
            return "deinit"
        return None

    if language in {"kotlin"}:
        match = re.search(
            r"\bfun\s+(?:<[^>]+>\s+)?(?:[A-Za-z_][A-Za-z0-9_<>?.]*\.)?(?:`([^`]+)`|([A-Za-z_][A-Za-z0-9_]*))",
            line,
        )
        if match:
            return match.group(1) or match.group(2)
        if re.search(r"\bconstructor\s*\(", line):
            return "constructor"
        return None

    if language == "go":
        match = re.search(
            r"\bfunc\s+(?:\([^)]*\)\s*)?([A-Za-z_][A-Za-z0-9_]*)(?:\s*\[[^]]+\])?\s*\(",
            line,
        ) or re.match(r"\)\s*([A-Za-z_][A-Za-z0-9_]*)(?:\s*\[[^]]+\])?\s*\(", line)
        if match and match.group(1) not in CONTROL_WORDS:
            return match.group(1)
        if re.search(r"\bfunc\s*\(", line):
            return "<anonymous>"
        return None

    if language == "rust":
        match = re.search(r"\bfn\s+([A-Za-z_][A-Za-z0-9_]*)\s*[<(]", line)
        return match.group(1) if match else None

    if language == "php":
        match = re.search(r"\bfunction\s+&?\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(", line)
        return match.group(1) if match else None

    if language in {"javascript", "typescript"}:
        match = re.search(
            r"\bfunction\s+\*?\s*([A-Za-z_$][A-Za-z0-9_$]*)(?:\s*<[^>]+>)?\s*\(", line
        )
        if match:
            return match.group(1)
        match = re.search(
            r"\b(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=.*=>", line
        )
        if match:
            return match.group(1)
        match = re.search(
            r"\b(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*(?:async\s*)?\(?\s*$",
            line,
        )
        if match:
            return match.group(1)
        match = re.match(
            r"(?:static\s+)?([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*(?:async\s*)?.*=>",
            line,
        )
        if match:
            return match.group(1)
        match = re.match(
            r"(?:static\s+)?(?:async\s+)?(?:get\s+|set\s+)?\*?\s*"
            r"([A-Za-z_$][A-Za-z0-9_$]*)\s*\([^)]*\)\s*\{?",
            line,
        )
        if match and match.group(1) not in CONTROL_WORDS:
            return match.group(1)
        if re.search(
            r"(?:\([^()]*(?:\([^()]*\)[^()]*)*\)|[A-Za-z_$][A-Za-z0-9_$]*)\s*=>", line
        ):
            return "<anonymous>"
        return None

    if language in {"csharp", "java"}:
        if "(" not in line:
            return None
        prefix = (
            r"(?:\[[^\]]+\]\s*)*"
            r"(?:(?:public|private|protected|internal|static|virtual|override|async|sealed|extern|unsafe|partial|new|final|synchronized|abstract)\s+)*"
        )
        match = (
            re.match(
                prefix + r"\S+\s+([A-Za-z_][A-Za-z0-9_]*)\s*<[^>]+>\s*\(",
                line,
            )
            or re.match(
                prefix + r"<[^>]+>\s+\S+\s+" + r"([A-Za-z_][A-Za-z0-9_]*)\s*\(",
                line,
            )
            or re.match(
                prefix + r"(?:<[^>]+>\s+)?"
                r"(?:[A-Za-z_][A-Za-z0-9_<>,\[\].?]+?\s+)?"
                r"([A-Za-z_][A-Za-z0-9_]*)(?:\s*<[^>]+>)?\s*\(",
                line,
            )
        )
        if match and match.group(1) not in CONTROL_WORDS:
            return match.group(1)
        return None

    return None


def is_rust_lifetime(line: str, index: int, language: str) -> bool:
    """`'a` in `fn f<'a>(x: &'a str)` is a lifetime, not an unterminated char
    literal — without this the rest of the line is swallowed as a string and
    the brace counts go wrong."""
    if language != "rust" or index + 1 >= len(line):
        return False
    following = line[index + 1]
    if not (following.isalpha() or following == "_"):
        return False
    return not (index + 2 < len(line) and line[index + 2] == "'")


def scan_c_style_lines(text: str, language: str) -> list[tuple[str, str, bool]]:
    state = CStyleScanState()
    scanned = []
    for raw_line in text.splitlines():
        clean, is_comment = scan_c_style_line(raw_line, language, state)
        scanned.append((raw_line, clean, is_comment))
    return scanned


def starts_javascript_regex(output: Sequence[str]) -> bool:
    prefix = "".join(output).rstrip()
    if not prefix:
        return True
    return prefix[-1] in "=(:,[!&|?{};" or bool(
        re.search(r"\b(?:return|throw|case|delete|typeof|void|new|in|of)\s*$", prefix)
    )


def scan_c_style_line(
    line: str, language: str, state: CStyleScanState
) -> tuple[str, bool]:
    if state.quote and state.quote.startswith("php-heredoc:"):
        marker = state.quote.removeprefix("php-heredoc:")
        if line.strip().rstrip(";") == marker:
            state.quote = None
        return "", False
    if language == "php":
        heredoc = re.search(r"<<<[-~]?(?:['\"])?([A-Z][A-Za-z0-9_]*)", line)
        if heredoc:
            state.quote = f"php-heredoc:{heredoc.group(1)}"
            return line[: heredoc.start()], False

    output = []
    index = 0
    had_comment = False
    while index < len(line):
        if state.block_depth:
            had_comment = True
            if language == "swift" and line.startswith("/*", index):
                state.block_depth += 1
                index += 2
            elif line.startswith("*/", index):
                state.block_depth -= 1
                index += 2
            else:
                index += 1
            continue
        if state.quote == '"""':
            if line.startswith('"""', index):
                state.quote = None
                index += 3
            else:
                index += 1
            continue
        if state.quote == '@"':
            if line.startswith('""', index):
                index += 2
            elif line[index] == '"':
                state.quote = None
                index += 1
            else:
                index += 1
            continue
        if state.quote:
            char = line[index]
            if char == "\\" and state.quote != "`" and index + 1 < len(line):
                index += 2
            else:
                if char == state.quote:
                    state.quote = None
                index += 1
            continue
        if line.startswith("//", index):
            had_comment = True
            break
        if language == "php" and line[index] == "#":
            had_comment = True
            break
        if line.startswith("/*", index):
            state.block_depth = 1
            had_comment = True
            index += 2
            continue
        if line.startswith('"""', index):
            state.quote = '"""'
            index += 3
            continue
        if language == "csharp" and line.startswith('@"', index):
            state.quote = '@"'
            index += 2
            continue
        char = line[index]
        if (
            char == "/"
            and language in {"javascript", "typescript"}
            and starts_javascript_regex(output)
        ):
            state.quote = "/"
            in_class = False
            index += 1
            while index < len(line):
                if line[index] == "\\" and index + 1 < len(line):
                    index += 2
                elif line[index] == "[":
                    in_class = True
                    index += 1
                elif line[index] == "]":
                    in_class = False
                    index += 1
                elif line[index] == "/" and not in_class:
                    state.quote = None
                    index += 1
                    while index < len(line) and line[index].isalpha():
                        index += 1
                    break
                else:
                    index += 1
            continue
        if char == "'" and is_rust_lifetime(line, index, language):
            output.append(char)
            index += 1
            continue
        if char in {'"', "'"}:
            quote = char
            index += 1
            while index < len(line):
                if line[index] == "\\" and index + 1 < len(line):
                    index += 2
                elif line[index] == quote:
                    index += 1
                    break
                else:
                    index += 1
            continue
        if char == "`" and language not in {"swift", "kotlin"}:
            state.quote = char
            index += 1
            continue
        output.append(char)
        index += 1
    clean = "".join(output)
    return clean, had_comment and not clean.strip()


def strip_strings(line: str, language: str = "") -> str:
    output = []
    quote: str | None = None
    escaped = False
    quotes = {'"', "'"} if language == "swift" else {'"', "'", "`"}
    index = 0
    while index < len(line):
        char = line[index]
        if quote:
            if escaped:
                escaped = False
                output.append(" ")
                index += 1
                continue
            if char == "\\":
                escaped = True
                output.append(" ")
                index += 1
                continue
            if char == quote:
                quote = None
            output.append(" ")
            index += 1
            continue

        if char in quotes:
            if is_rust_lifetime(line, index, language):
                output.append(char)
                index += 1
                continue
            quote = char
            output.append(" ")
        else:
            output.append(char)
        index += 1
    return "".join(output)


def strip_ruby_comment(line: str) -> str:
    output = []
    quote: str | None = None
    escaped = False
    for char in line:
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            output.append(" ")
            continue
        if char in {'"', "'"}:
            quote = char
            output.append(" ")
        elif char == "#":
            break
        else:
            output.append(char)
    return "".join(output)


def should_ignore(relative_path: str, patterns: Sequence[str]) -> bool:
    parts = relative_path.split("/")
    basename = parts[-1]
    for pattern in patterns:
        normalized = pattern.strip().replace("\\", "/")
        if normalized.startswith("./"):
            normalized = normalized[2:]
        if normalized.startswith(".\\"):
            normalized = normalized[2:]
        if normalized.startswith("/"):
            normalized = normalized[1:]
        if not normalized:
            continue
        is_directory = normalized.endswith("/")
        normalized = normalized.rstrip("/")
        if is_directory:
            if "/" not in normalized:
                if normalized in parts:
                    return True
            elif relative_path.startswith(f"{normalized}/") or fnmatch.fnmatch(
                relative_path, f"**/{normalized}/*"
            ):
                return True
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


def print_report(issues: Sequence[Issue], checked_count: int, mode: str) -> None:
    if not issues:
        print(f"Code Linter passed: scanned {checked_count} file(s) in {mode} mode.")
        return

    for issue in issues:
        print(
            f"::error file={issue.path},line={issue.line},title={issue.kind}::{escape_github_message(issue.message)}"
        )

    print(
        f"Code Linter failed: {len(issues)} issue(s) across {checked_count} scanned file(s) in {mode} mode."
    )


def escape_github_message(message: str) -> str:
    return message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def to_relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        # A symlink pointing outside the repo resolves out of `root`; report it
        # under the path git gave us rather than crashing the whole gate.
        return os.path.relpath(path, root).replace(os.sep, "/")


def github_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.as_posix()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
