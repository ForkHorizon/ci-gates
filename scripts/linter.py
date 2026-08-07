#!/usr/bin/env python3
"""Portable readability gate for humans and AI coding agents.

The checker intentionally uses only Python's standard library so this file can
be copied between repositories and run from GitHub Actions without setup.
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import os
import re
import subprocess
import sys
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
    "linter.py",
    "*.designer.cs",
    "*.generated.*",
    "*.g.cs",
    "*.g.swift",
    "*.gen.*",
    "*.min.js",
    "*.pb.*",
    "*.snap",
    "*.snapshot",
]

DEFAULT_CONFIG = {
    "max_file_lines": 300,
    "max_function_lines": 50,
    "max_nesting_depth": 4,
    "max_parameters": 5,
    "max_comment_lines": 5,
    "max_types_per_file": 2,
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


def main(argv: Sequence[str]) -> int:
    args = parse_args(argv)
    root = Path(args.root).resolve()
    config = load_config(root / args.config)

    paths = collect_paths(root, config, args)
    if not paths:
        progress("lint", detail="No matching source files")
    issues = check_paths(root, paths, config)
    print_report(issues, len(paths), args.mode)
    return 1 if issues else 0


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check source file and function length for AI-readable code."
    )
    parser.add_argument("--mode", choices=("all", "changed"), default="all")
    parser.add_argument(
        "--base", default="origin/main", help="Base ref for changed mode."
    )
    parser.add_argument("--head", default="HEAD", help="Head ref for changed mode.")
    parser.add_argument("--config", default=".ai-readability.json")
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
                f"::error file={github_path(path)}::.ai-readability config must be a JSON object",
                file=sys.stderr,
            )
            sys.exit(2)
        loaded_ignore = loaded.get("ignore")
        config.update(loaded)
        if loaded_ignore is not None:
            merged = list(DEFAULT_IGNORE)
            for item in loaded_ignore:
                if item not in merged:
                    merged.append(item)
            config["ignore"] = merged

    config["max_file_lines"] = int(config.get("max_file_lines", 300))
    config["max_function_lines"] = int(config.get("max_function_lines", 50))
    config["max_nesting_depth"] = int(config.get("max_nesting_depth", 4))
    config["max_parameters"] = int(config.get("max_parameters", 5))
    config["max_comment_lines"] = int(config.get("max_comment_lines", 5))
    config["max_types_per_file"] = int(config.get("max_types_per_file", 2))
    config["include_extensions"] = [
        ext if ext.startswith(".") else f".{ext}"
        for ext in config.get("include_extensions", LANGUAGE_BY_EXTENSION)
    ]
    config["language_overrides"] = dict(config.get("language_overrides", {}))
    return config


def collect_paths(root: Path, config: dict, args: argparse.Namespace) -> list[Path]:
    candidates = (
        changed_paths(root, args.base, args.head)
        if args.mode == "changed"
        else all_repo_paths(root)
    )

    include_extensions = set(config["include_extensions"])
    paths = []
    for path in candidates:
        if not path.is_file():
            continue
        relative = to_relative(root, path)
        if path.suffix not in include_extensions:
            continue
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
        language = LANGUAGE_BY_EXTENSION.get(path.suffix)
        if language is None:
            continue

        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = path.read_text(encoding="utf-8", errors="replace")

        lines = text.splitlines()
        limits = limits_for_language(config, language)
        max_file_lines = limits["max_file_lines"]
        max_function_lines = limits["max_function_lines"]
        max_nesting_depth = limits["max_nesting_depth"]
        max_parameters = limits["max_parameters"]
        max_comment_lines = limits["max_comment_lines"]
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
        issues.extend(check_comment_blocks(relative, text, language, max_comment_lines))
        issues.extend(
            check_types_per_file(relative, text, language, max_types_per_file)
        )
    return issues


def limits_for_language(config: dict, language: str) -> dict[str, int]:
    limits = {
        "max_file_lines": int(config.get("max_file_lines", 300)),
        "max_function_lines": int(config.get("max_function_lines", 50)),
        "max_nesting_depth": int(config.get("max_nesting_depth", 4)),
        "max_parameters": int(config.get("max_parameters", 5)),
        "max_comment_lines": int(config.get("max_comment_lines", 5)),
        "max_types_per_file": int(config.get("max_types_per_file", 2)),
    }
    override = config.get("language_overrides", {}).get(language, {})
    if isinstance(override, dict):
        for key in limits:
            if key in override:
                limits[key] = int(override[key])
    return limits


def function_lengths(text: str, language: str) -> list[tuple[str, int, int, int]]:
    if language == "python":
        return python_function_lengths(text)
    if language == "ruby":
        return ruby_function_lengths(text)
    return brace_function_lengths(text, language)


def python_function_lengths(text: str) -> list[tuple[str, int, int, int]]:
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        line = exc.lineno or 1
        return [
            (
                f"Python syntax error near line {line}",
                line,
                len(text.splitlines()) - line + 1,
                0,
            )
        ]

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


def ruby_function_lengths(text: str) -> list[tuple[str, int, int, int]]:
    stack: list[tuple[str, str, int, int]] = []
    results = []

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = strip_ruby_comment(raw_line)
        stripped = line.strip()
        if not stripped:
            continue

        def_match = re.match(
            r"\s*def\s+([A-Za-z_][A-Za-z0-9_!?=]*(?:\.[A-Za-z_][A-Za-z0-9_!?=]*)?)",
            line,
        )
        if def_match:
            name = def_match.group(1)
            pcount = count_params_in_signature(line)
            if re.search(r"\s=\s", line):
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

    return results


def brace_function_lengths(text: str, language: str) -> list[tuple[str, int, int, int]]:
    results = []
    active: list[FunctionBlock] = []
    pending: tuple[str, int, int] | None = None
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
            pcount = count_params_in_signature(clean)
            pending = (detected, line_number, pcount)
        elif pending:
            pending_sig.append(clean)
            full_sig = "\n".join(pending_sig)
            pcount = count_params_in_signature(full_sig)
            pending = (pending[0], pending[1], pcount)

        opens = clean.count("{")
        closes = clean.count("}")

        if pending and opens:
            name, start_line, pcount = pending
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
            and opens == 0
            and closes == 0
            and ("=" in stripped or "=>" in stripped)
        ):
            if not (
                stripped.endswith(",")
                or (len(pending_sig) > 1 and not stripped.endswith(";"))
            ):
                name, start_line, pcount = pending
                results.append((name, start_line, 1, pcount))
                pending = None
                pending_sig = []

        if pending and stripped.endswith(";"):
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

    return results


def count_params_in_signature(signature_line: str) -> int:
    signature_clean = strip_strings(signature_line)
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
    issues: list[Issue] = []
    if language == "python":
        try:
            tree = ast.parse(text)
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
                            and any(child is o for o in parent.orelse)
                        )
                        if not is_elif:
                            next_depth = depth + 1
                            if next_depth > max_depth:
                                issues.append(
                                    Issue(
                                        path=relative,
                                        line=getattr(child, "lineno", 1),
                                        kind="nesting_depth",
                                        message=f"Nesting depth is {next_depth}; limit is {max_depth}.",
                                    )
                                )
                    walk(child, next_depth, parent=child)

            walk(tree, 0)
        except SyntaxError:
            pass
    else:
        depth = 0
        for line_no, (_, clean, _) in enumerate(
            scan_c_style_lines(text, language), start=1
        ):
            opens = clean.count("{")
            closes = clean.count("}")

            first_word = re.search(
                r"\b(if|for|foreach|while|switch|try|catch|guard|do)\b", clean
            )
            if first_word and (opens > 0 or depth > 0):
                current_depth = depth + (1 if opens > 0 else 0)
                if current_depth > max_depth:
                    issues.append(
                        Issue(
                            path=relative,
                            line=line_no,
                            kind="nesting_depth",
                            message=f"Nesting depth is {current_depth}; limit is {max_depth}.",
                        )
                    )

            depth += opens - closes
            depth = max(depth, 0)
    return issues


def check_comment_blocks(
    relative: str, text: str, language: str, max_comment_lines: int
) -> list[Issue]:
    issues: list[Issue] = []
    prefix = "#" if language in {"python", "ruby"} else "//"
    current_start = None
    count = 0
    if language in {"python", "ruby"}:
        comment_lines = [
            line.strip().startswith(prefix) and not line.strip().startswith("#!")
            for line in text.splitlines()
        ]
    else:
        comment_lines = [
            is_comment for _, _, is_comment in scan_c_style_lines(text, language)
        ]

    for line_no, is_comment in enumerate(comment_lines, start=1):
        if is_comment:
            if count == 0:
                current_start = line_no
            count += 1
        else:
            if count > max_comment_lines and current_start is not None:
                issues.append(
                    Issue(
                        path=relative,
                        line=current_start,
                        kind="comment_block",
                        message=f"Comment block has {count} consecutive lines; limit is {max_comment_lines}.",
                    )
                )
            count = 0
            current_start = None

    if count > max_comment_lines and current_start is not None:
        issues.append(
            Issue(
                path=relative,
                line=current_start,
                kind="comment_block",
                message=f"Comment block has {count} consecutive lines; limit is {max_comment_lines}.",
            )
        )
    return issues


def check_types_per_file(
    relative: str, text: str, language: str, max_types: int
) -> list[Issue]:
    issues: list[Issue] = []
    types: list[tuple[str, int]] = []
    if language == "python":
        try:
            tree = ast.parse(text)
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    types.append((node.name, node.lineno))
        except SyntaxError:
            pass
    else:
        type_patterns = {
            "csharp": r"\b(?:class|struct|interface|enum|record(?:\s+(?:class|struct))?)\s+([A-Za-z_][A-Za-z0-9_]*)",
            "swift": r"\b(?:class|struct|enum|actor|protocol)\s+([A-Za-z_][A-Za-z0-9_]*)",
            "go": r"\btype\s+([A-Za-z_][A-Za-z0-9_]*)\b",
            "typescript": r"\b(?:class|interface|enum|type)\s+([A-Za-z_$][A-Za-z0-9_$]*)",
            "javascript": r"\bclass\s+([A-Za-z_$][A-Za-z0-9_$]*)",
            "rust": r"\b(?:struct|enum|trait|union)\s+([A-Za-z_][A-Za-z0-9_]*)",
            "php": r"\b(?:class|interface|enum|trait)\s+([A-Za-z_][A-Za-z0-9_]*)",
            "kotlin": r"\b(?:class|interface|object|enum\s+class|typealias)\s+([A-Za-z_][A-Za-z0-9_]*)",
            "java": r"\b(?:class|interface|enum|record)\s+([A-Za-z_][A-Za-z0-9_]*)",
        }
        pattern = type_patterns.get(
            language,
            r"\b(?:class|struct|interface|enum|actor)\s+([A-Za-z_][A-Za-z0-9_]*)",
        )
        for line_no, (_, clean, _) in enumerate(
            scan_c_style_lines(text, language), start=1
        ):
            match = re.search(pattern, clean)
            if match:
                types.append((match.group(1), line_no))

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
        match = re.search(r"\bfunc\s+(?:`([^`]+)`|([A-Za-z_][A-Za-z0-9_]*))", line)
        if match:
            return (match.group(1) or match.group(2)).strip("`")
        if re.search(r"\binit\s*\(", line):
            return "init"
        if re.search(r"\bdeinit\b", line):
            return "deinit"
        return None

    if language in {"kotlin"}:
        match = re.search(
            r"\bfun\s+(?:<[^>]+>\s+)?(?:[A-Za-z_][A-Za-z0-9_<>?.]*\.)?([A-Za-z_][A-Za-z0-9_]*)",
            line,
        )
        if match:
            return match.group(1)
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
        match = re.match(
            r"(?:async\s+)?([A-Za-z_$][A-Za-z0-9_$]*)\s*\([^)]*\)\s*\{?", line
        )
        if match and match.group(1) not in CONTROL_WORDS:
            return match.group(1)
        return None

    if language in {"csharp", "java"}:
        if "(" not in line or "=>" in line:
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


def strip_c_style_comments(line: str, in_block_comment: bool) -> tuple[str, bool]:
    output = []
    index = 0
    quote: str | None = None
    escaped = False

    while index < len(line):
        if in_block_comment:
            end = line.find("*/", index)
            if end == -1:
                return "".join(output), True
            index = end + 2
            in_block_comment = False
            continue

        char = line[index]
        if quote:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            index += 1
            continue

        if char in {'"', "'", "`"}:
            quote = char
            output.append(char)
            index += 1
            continue

        if line.startswith("//", index):
            break

        if line.startswith("/*", index):
            index += 2
            in_block_comment = True
            continue

        output.append(char)
        index += 1

    return "".join(output), in_block_comment


def scan_c_style_lines(text: str, language: str) -> list[tuple[str, str, bool]]:
    state = CStyleScanState()
    scanned = []
    for raw_line in text.splitlines():
        clean, is_comment = scan_c_style_line(raw_line, language, state)
        scanned.append((raw_line, clean, is_comment))
    return scanned


def scan_c_style_line(
    line: str, language: str, state: CStyleScanState
) -> tuple[str, bool]:
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
        if char == "`" and language != "swift":
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
            if (
                char == "'"
                and language == "rust"
                and index + 1 < len(line)
                and (line[index + 1].isalpha() or line[index + 1] == "_")
            ):
                if not (index + 2 < len(line) and line[index + 2] == "'"):
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
    quote: str | None = None
    escaped = False
    for index, char in enumerate(line):
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in {'"', "'"}:
            quote = char
        elif char == "#":
            return line[:index]
    return line


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
        print(
            f"AI readability check passed: scanned {checked_count} file(s) in {mode} mode."
        )
        return

    for issue in issues:
        print(
            f"::error file={issue.path},line={issue.line},title={issue.kind}::{escape_github_message(issue.message)}"
        )

    print(
        f"AI readability check failed: {len(issues)} issue(s) across {checked_count} scanned file(s) in {mode} mode."
    )


def escape_github_message(message: str) -> str:
    return message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def to_relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root).as_posix()


def github_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.as_posix()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
