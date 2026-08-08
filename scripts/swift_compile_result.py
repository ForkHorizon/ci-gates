from __future__ import annotations

from dataclasses import dataclass
from re import Pattern

from swift_compile_model import WarningRecord


@dataclass(frozen=True)
class WarningPolicy:
    fail_on_any_warning: bool
    include_patterns: list[Pattern[str]]
    exclude_patterns: list[Pattern[str]]


@dataclass(frozen=True)
class BuildResult:
    exit_code: int
    critical_warnings: list[WarningRecord]
