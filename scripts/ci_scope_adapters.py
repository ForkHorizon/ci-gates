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
    command = [sys.executable, str(gates / "scripts/code-linter.py"), "--root", str(root), "--mode", mode]
    if mode == "changed":
        command += ["--base", base, "--head", head]
    if check.config:
        command += ["--config", check.config]
    if check.params.get("coverage_mode"):
        command += ["--coverage-mode", str(check.params["coverage_mode"])]
    guard = [
        sys.executable, str(gates / "scripts/policy_signature_guard.py"),
        "--root", str(root), "--base", base, "--head", head,
        "--allowed-signers", str(gates / "configs/allowed_signers"),
    ]
    return [guard, command] if mode == "changed" else [command]


def _python_quality(check: CheckSpec, root: Path, gates: Path) -> list[list[str]]:
    workdir = root / check.workdir
    has_config = (workdir / "ruff.toml").is_file() or (workdir / ".ruff.toml").is_file()
    pyproject = workdir / "pyproject.toml"
    has_config = has_config or (pyproject.is_file() and "[tool.ruff" in pyproject.read_text(encoding="utf-8"))
    config = [] if has_config else ["--config", str(gates / "configs/ruff-strict.toml")]
    return [["ruff", "check", *config, "."], ["ruff", "format", "--check", *config, "."]]


def _swift_quality(check: CheckSpec, root: Path, gates: Path, revisions: tuple[str, str], event: str) -> list[list[str]]:
    base, head = revisions
    prefix = [sys.executable, str(gates / "scripts/swift-quality-gate.py"), "--root", str(root)]
    if check.config:
        prefix += ["--config", check.config]
    mode = "changed" if event in {"pull_request", "merge_group"} else "all"
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
    command = [sys.executable, str(gates / "scripts/slop-review.py"), "--base", base, "--head", head]
    if check.config:
        command += ["--config", check.config]
    command += ["--model", str(check.params.get("model", DEFAULT_AI_MODEL))]
    return [command]


def commands_for(check: CheckSpec, root: Path, gates: Path, revisions: tuple[str, str], event: str = "pull_request") -> list[list[str]]:
    if check.type == "code-linter":
        return _code_linter(check, root, gates, revisions, event)
    if check.type == "python-quality":
        return _python_quality(check, root, gates)
    if check.type == "go-quality":
        return [
            ["go", "mod", "download"], ["go", "vet", "./..."],
            [sys.executable, "-c", "import subprocess,sys; files=subprocess.check_output(['gofmt','-l','.'], text=True); print(files, end=''); sys.exit(bool(files))"],
            ["golangci-lint", "run", "./..."],
        ]
    if check.type == "swift-quality":
        return _swift_quality(check, root, gates, revisions, event)
    if check.type == "swift-compile":
        return _configured("swift-compile-gate.py", check, root, gates)
    if check.type == "slop-review":
        return _slop_review(check, gates, revisions)
    raise ManifestError(f"unsupported executor adapter: {check.type}")
