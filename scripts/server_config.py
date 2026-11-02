"""Turn a project config held by the CI Scope server into runnable check specs.

The config never lives in the repository under test. Per-check config files are written to a
directory outside the checkout so the agent being checked cannot edit the limits it is held to.
"""

from __future__ import annotations

import json
from pathlib import Path

try:
    from ci_scope_models import CheckSpec
except ModuleNotFoundError:
    from .ci_scope_models import CheckSpec

EVENTS = ("pull_request", "merge_group", "push", "local")
LANGUAGE_CHECKS = {
    "swift": ("swift-quality", "swift-compile"),
    "python": ("python-quality",),
    "go": ("go-quality",),
    "web": ("web-quality",),
    "rust": ("rust-quality",),
}
RESOURCES = {"swift-quality": ("xcode",), "swift-compile": ("xcode",)}
CODE_LINTER_EXTENSIONS = [
    ".cs",
    ".go",
    ".java",
    ".js",
    ".jsx",
    ".kt",
    ".kts",
    ".php",
    ".py",
    ".rb",
    ".rs",
    ".swift",
    ".ts",
    ".tsx",
]
CODE_LINTER_IGNORE = [
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


class ConfigError(ValueError):
    pass


def _spec(
    check_id: str, check_type: str, *, config: str | None = None, params: dict | None = None, speed: str = "fast"
) -> CheckSpec:
    return CheckSpec(
        id=check_id,
        type=check_type,
        config=config,
        workdir=".",
        params=params or {},
        depends_on=(),
        events=EVENTS,
        resources=RESOURCES.get(check_type, ()),
        required=True,
        ai=False,
        speed=speed,
    )


def code_linter_config(rules: dict) -> dict:
    params = rules["params"]
    return {
        "max_file_lines": params["maxFileLines"],
        "max_function_lines": params["maxFunctionLines"],
        "max_nesting_depth": params["maxNestingDepth"],
        "max_parameters": params["maxParameters"],
        "max_comment_lines": 5,
        "max_types_per_file": 5,
        "include_extensions": CODE_LINTER_EXTENSIONS,
        "ignore": CODE_LINTER_IGNORE + list(params["ignore"]),
        "language_overrides": {},
    }


def build_check_specs(config: dict, config_dir: Path) -> list[CheckSpec]:
    """Return the checks the server config enables; writes per-check config files into `config_dir`."""
    if config.get("schema") != 1:
        raise ConfigError("unsupported project config schema")
    lanes = config["lanes"]
    specs: list[CheckSpec] = []
    rules = lanes["code-rules"]
    if rules["enabled"]:
        config_dir.mkdir(parents=True, exist_ok=True)
        linter_path = config_dir / "code-linter.json"
        linter_path.write_text(json.dumps(code_linter_config(rules), indent=2) + "\n", encoding="utf-8")
        specs.append(
            _spec(
                "code-linter", "code-linter", config=str(linter_path), params={"mode": "auto", "signature_guard": False}
            )
        )
        if rules["params"]["forbidSuppressions"]:
            specs.append(_spec("forbidden-constructs", "forbidden-constructs", params={"mode": "new"}))
        specs.append(_spec("duplicate-blocks", "duplicate-blocks", params={"mode": "new"}))
        specs.append(_spec("file-roles", "file-roles", params={"mode": "new"}))
    if lanes["agent-guard"]["enabled"]:
        specs.append(_spec("test-protection", "test-protection"))
        specs.append(_spec("agent-docs-stable", "agent-docs-stable", params={"mode": "new"}))
    if lanes["language"]["enabled"]:
        for adapter in lanes["language"]["adapters"]:
            if adapter not in LANGUAGE_CHECKS:
                raise ConfigError(f"no check is available for language adapter: {adapter}")
            for check_type in LANGUAGE_CHECKS[adapter]:
                specs.append(_spec(check_type, check_type, speed="full"))
    if lanes["tests"]["enabled"]:
        specs.append(
            _spec("project-tests", "project-tests", params={"command": lanes["tests"]["command"]}, speed="full")
        )
    return specs
