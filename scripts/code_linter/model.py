from __future__ import annotations

from dataclasses import dataclass


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
