"""Find GitHub Actions gates a project kept after moving to CI Scope."""

from __future__ import annotations

from pathlib import Path

# The GitHub Actions gates CI Scope replaced: reusable ci-gates workflows and the old "CI Scope / Checks" workflow.
LEGACY_GATE_MARKERS = ("ForkHorizon/ci-gates/.github/workflows/", "ci-scope-unified")


def legacy_gate_workflows(root: Path) -> list[str]:
    """Workflow files that still run an old gate next to the CI Scope check."""
    workflows = root / ".github/workflows"
    files = sorted([*workflows.glob("*.yml"), *workflows.glob("*.yaml")]) if workflows.is_dir() else []
    return [
        f".github/workflows/{file.name}"
        for file in files
        if any(marker in file.read_text(encoding="utf-8", errors="replace") for marker in LEGACY_GATE_MARKERS)
    ]
