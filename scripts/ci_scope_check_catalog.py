from dataclasses import dataclass


@dataclass(frozen=True)
class CheckDefinition:
    type: str
    required: bool
    default_config: str | None = None
    allowed_params: frozenset[str] = frozenset()
    resources: frozenset[str] = frozenset()
    ai: bool = False


CHECK_CATALOG: dict[str, CheckDefinition] = {
    "code-linter": CheckDefinition(
        "code-linter",
        True,
        ".code-linter.json",
        frozenset({"mode", "coverage_mode", "explain_model"}),
    ),
    "python-quality": CheckDefinition("python-quality", True, None, frozenset({"explain_model"})),
    "python-pytest": CheckDefinition("python-pytest", True),
    "forbidden-constructs": CheckDefinition(
        "forbidden-constructs", True, ".forbidden-constructs.json", frozenset({"mode"})
    ),
    "duplicate-blocks": CheckDefinition(
        "duplicate-blocks",
        True,
        ".duplicate-blocks.json",
        frozenset({"mode", "min_lines"}),
    ),
    "file-roles": CheckDefinition("file-roles", True, None, frozenset({"mode"})),
    "agent-docs-stable": CheckDefinition("agent-docs-stable", True, None, frozenset({"mode"})),
    "go-quality": CheckDefinition("go-quality", True, None, frozenset({"explain_model"})),
    "web-quality": CheckDefinition("web-quality", True),
    "web-test": CheckDefinition("web-test", True),
    "swift-quality": CheckDefinition(
        "swift-quality",
        True,
        ".swift-quality-gate.json",
        frozenset({"run_build", "explain_model"}),
        frozenset({"xcode"}),
    ),
    "swift-compile": CheckDefinition(
        "swift-compile",
        True,
        ".swift-compile-gate.json",
        frozenset({"explain_model"}),
        frozenset({"xcode"}),
    ),
    "slop-review": CheckDefinition(
        "slop-review",
        False,
        ".slop-review.json",
        frozenset({"model"}),
        frozenset({"ollama"}),
        True,
    ),
}
