"""Shared data models for the unified CI Scope manifest."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class CheckSpec:
    id: str
    type: str
    config: str | None
    workdir: str
    params: Mapping[str, Any]
    depends_on: tuple[str, ...]
    events: tuple[str, ...]
    resources: tuple[str, ...]
    required: bool
    ai: bool


@dataclass(frozen=True)
class ResolvedManifest:
    version: int
    checks: tuple[CheckSpec, ...]
    root: Path
    source: Path
    event: str | None = None

    @property
    def active_checks(self) -> tuple[CheckSpec, ...]:
        if self.event is None:
            return self.checks
        return tuple(check for check in self.checks if not check.events or self.event in check.events)
