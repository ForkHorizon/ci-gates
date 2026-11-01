"""Trusted command adapters for the unified CI Scope executor."""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from ci_scope_manifest import ManifestError
    from ci_scope_models import CheckSpec
except ModuleNotFoundError:  # Imported as scripts.ci_scope_adapters by tools.
    from .ci_scope_manifest import ManifestError
    from .ci_scope_models import CheckSpec


DEFAULT_AI_MODEL = "qwen3-coder:30b-a3b-q4_K_M"


def _code_linter(check: CheckSpec, root: Path, gates: Path, revisions: tuple[str, str], event: str) -> list[list[str]]:
    base, head = revisions
    mode = str(check.params.get("mode", "auto"))
    if mode == "auto":
        mode = "changed" if event in {"pull_request", "merge_group"} else "all"
    command = [
        sys.executable,
        str(gates / "scripts/code-linter.py"),
        "--root",
        str(root),
        "--mode",
        mode,
    ]
    if mode == "changed":
        command += ["--base", base, "--head", head]
    if check.config:
        command += ["--config", check.config]
    if check.params.get("coverage_mode"):
        command += ["--coverage-mode", str(check.params["coverage_mode"])]
    guard = [
        sys.executable,
        str(gates / "scripts/policy_signature_guard.py"),
        "--root",
        str(root),
        "--base",
        base,
        "--head",
        head,
        "--allowed-signers",
        str(gates / "configs/allowed_signers"),
    ]
    return [guard, command] if mode == "changed" else [command]


def _python_quality(check: CheckSpec, root: Path, gates: Path) -> list[list[str]]:
    workdir = root / check.workdir
    has_config = (workdir / "ruff.toml").is_file() or (workdir / ".ruff.toml").is_file()
    pyproject = workdir / "pyproject.toml"
    has_config = has_config or (pyproject.is_file() and "[tool.ruff" in pyproject.read_text(encoding="utf-8"))
    config = [] if has_config else ["--config", str(gates / "configs/ruff-strict.toml")]
    return [
        ["ruff", "check", *config, "."],
        ["ruff", "format", "--check", *config, "."],
    ]


def _python_pytest() -> list[list[str]]:
    return [["python3", "-m", "pytest", "tests", "-q"]]


def _shape_checks(check: CheckSpec, root: Path, gates: Path, revisions: tuple[str, str], event: str) -> list[list[str]]:
    script = {
        "forbidden-constructs": "forbidden_constructs.py",
        "duplicate-blocks": "duplicate_blocks.py",
        "file-roles": "file_roles.py",
    }[check.type]
    command = [
        sys.executable,
        str(gates / f"scripts/{script}"),
        "--root",
        str(root),
        "--mode",
        str(check.params.get("mode", "new")),
        "--git-mode",
        "worktree" if event == "local" else "committed",
        "--base",
        revisions[0],
        "--head",
        revisions[1],
    ]
    if check.type == "duplicate-blocks":
        command += ["--min-lines", str(check.params.get("min_lines", 10))]
    if check.config:
        command += ["--config", str(root / check.config)]
    return [command]


def _web_quality(check: CheckSpec, root: Path) -> list[list[str]]:
    workdir = root / check.workdir
    compiler = workdir / "node_modules/typescript/bin/tsc"
    commands = [["node", str(compiler), "--noEmit"]]
    binaries = workdir / "node_modules/.bin"
    for tool, arguments in (("eslint", ["."]), ("knip", []), ("jscpd", ["."])):
        if (binaries / tool).is_file():
            commands.append([str(binaries / tool), *arguments])
    return commands


def _web_test() -> list[list[str]]:
    return [["node", "scripts/test.mjs"]]


def _swift_quality(
    check: CheckSpec, root: Path, gates: Path, revisions: tuple[str, str], event: str
) -> list[list[str]]:
    base, head = revisions
    prefix = [
        sys.executable,
        str(gates / "scripts/swift-quality-gate.py"),
        "--root",
        str(root),
    ]
    if check.config:
        prefix += ["--config", check.config]
    mode = "worktree" if event == "local" else ("changed" if event in {"pull_request", "merge_group"} else "all")
    commands = []
    if check.params.get("run_build", True):
        commands.append([*prefix, "--stage", "build", "--mode", "all"])
    commands.append([*prefix, "--stage", "format", "--mode", mode, "--base", base, "--head", head])
    commands.append([*prefix, "--stage", "dead-code", "--mode", "all"])
    return commands


def _configured(script: str, check: CheckSpec, root: Path, gates: Path) -> list[list[str]]:
    command = [sys.executable, str(gates / f"scripts/{script}"), "--root", str(root)]
    if check.config:
        command += ["--config", check.config]
    return [command]


def _slop_review(check: CheckSpec, gates: Path, revisions: tuple[str, str]) -> list[list[str]]:
    base, head = revisions
    command = [
        sys.executable,
        str(gates / "scripts/slop-review.py"),
        "--base",
        base,
        "--head",
        head,
    ]
    if check.config:
        command += ["--config", check.config]
    command += ["--model", str(check.params.get("model", DEFAULT_AI_MODEL))]
    return [command]


def commands_for(
    check: CheckSpec,
    root: Path,
    gates: Path,
    revisions: tuple[str, str],
    event: str = "pull_request",
) -> list[list[str]]:
    if check.type == "code-linter":
        commands = _code_linter(check, root, gates, revisions, event)
    elif check.type == "python-quality":
        commands = _python_quality(check, root, gates)
    elif check.type == "python-pytest":
        commands = _python_pytest()
    elif check.type in {"forbidden-constructs", "duplicate-blocks", "file-roles"}:
        commands = _shape_checks(check, root, gates, revisions, event)
    elif check.type == "web-quality":
        commands = _web_quality(check, root)
    elif check.type == "web-test":
        commands = _web_test()
    elif check.type == "go-quality":
        commands = [
            ["go", "mod", "download"],
            ["go", "vet", "./..."],
            [
                sys.executable,
                "-c",
                "import subprocess,sys; files=subprocess.check_output(['gofmt','-l','.'], text=True); print(files, end=''); sys.exit(bool(files))",
            ],
            ["golangci-lint", "run", "./..."],
        ]
    elif check.type == "swift-quality":
        commands = _swift_quality(check, root, gates, revisions, event)
    elif check.type == "swift-compile":
        commands = _configured("swift-compile-gate.py", check, root, gates)
    elif check.type == "slop-review":
        commands = _slop_review(check, gates, revisions)
    else:
        raise ManifestError(f"unsupported executor adapter: {check.type}")
    return commands
