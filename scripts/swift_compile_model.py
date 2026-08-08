from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SwiftProject:
    kind: str
    project_path: str | None = None
    scheme: str | None = None
    destination: str = ""
    configuration: str = "Debug"


@dataclass(frozen=True)
class WarningRecord:
    raw_line: str
    path: str | None
    line: int | None
    message: str

    def summary(self) -> str:
        if self.path and self.line:
            return f"{self.path}:{self.line}: {self.message}"
        if self.path:
            return f"{self.path}: {self.message}"
        return self.message or self.raw_line.strip()
