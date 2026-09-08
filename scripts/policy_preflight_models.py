from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PolicyResult:
    status: str
    reason: str = ""
    policy_digest: str = ""
    actual_digest: str = ""
    mismatches: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return self.status == "passed"


@dataclass(frozen=True)
class PolicyRecord:
    value: Mapping[str, Any]
    payload: bytes
    policy_digest: str
    files: Mapping[str, str]
    patterns: tuple[str, ...]
