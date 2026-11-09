"""Turn the raw output of a failed check into one short line an AI agent can act on.

Deterministic only: no model, no network. Known formats (GitHub `::error` annotations, `path:line  rule  message`
columns, ruff `-->` locations) become `file:line rule: message`. Anything else is left unstructured and a cleaned excerpt
is returned so a later step may ask a model about it. Lines that read like instructions are redacted: check output is
produced by the code under test and must never be treated as a request.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

MAX_FINDINGS = 3
MAX_MESSAGE = 90
MAX_LINE = 380
MAX_EXCERPT = 6_000
PROGRESS_PREFIX = "::ci-scope-progress::"
REDACTED = "[line removed: looks like an instruction, not a tool message]"

ANNOTATION = re.compile(r"::error file=([^,]+),line=(\d+)(?:,[^:]*?title=([^:]+))?::(.*)")
COLUMNS = re.compile(r"^([\w./@-]+\.\w+?)(?::(\d+)(?:-\d+)?)?\s{2,}(?:(?:high|medium|low)\s{2,})?([\w.-]+)\s{2,}(.+)$")
RUFF_LOCATION = re.compile(r"^\s*-->\s+(\S+?):(\d+)")
INSTRUCTION = re.compile(
    r"(ignore (all )?(the )?(previous|above)|disregard (the|all|this)|system override|note to (the )?ai|"
    r"^\s*(assistant|system)\s*:|you are (now )?an? |verdict is passed|respond only with|new instructions)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Finding:
    file: str
    line: int | None
    rule: str
    message: str

    def text(self) -> str:
        where = f"{self.file}:{self.line}" if self.line else self.file
        message = " ".join(self.message.split())[:MAX_MESSAGE]
        return f"{where} {self.rule}: {message}" if message else f"{where} {self.rule}"


@dataclass(frozen=True)
class Digest:
    findings: list[Finding] = field(default_factory=list)
    suspicious: bool = False
    excerpt: str = ""  # cleaned output, only set when no finding could be extracted

    @property
    def structured(self) -> bool:
        return bool(self.findings)

    def line(self) -> str:
        """`file:line rule: message; ...  (+N more)`, at most MAX_LINE characters."""
        shown = "; ".join(finding.text() for finding in self.findings[:MAX_FINDINGS])
        more = len(self.findings) - MAX_FINDINGS
        suffix = f" (+{more} more)" if more > 0 else ""
        flag = " [output had instruction-like text, ignored]" if self.suspicious else ""
        room = MAX_LINE - len(suffix) - len(flag)
        return (shown if len(shown) <= room else shown[: room - 1] + "…") + suffix + flag


def clean(output: str) -> tuple[str, bool]:
    """Drop progress noise and redact instruction-like lines. Returns (text, any line redacted)."""
    kept, redacted = [], False
    for line in output.splitlines():
        if line.startswith(PROGRESS_PREFIX):
            continue
        redacted = redacted or bool(INSTRUCTION.search(line))
        kept.append(REDACTED if INSTRUCTION.search(line) else line)
    return "\n".join(kept), redacted


def _match(line: str, previous: str) -> Finding | None:
    if found := ANNOTATION.match(line):
        return Finding(found[1], int(found[2]), (found[3] or "error").strip(), found[4].strip())
    if found := RUFF_LOCATION.match(line):
        rule, _, message = previous.strip().partition(" ")
        return Finding(found[1], int(found[2]), rule.rstrip(":")[:40] or "ruff", message)
    if found := COLUMNS.match(line):
        return Finding(found[1], int(found[2]) if found[2] else None, found[3], found[4].strip())
    return None


def extract(text: str) -> list[Finding]:
    """Every location the known formats report, in order of appearance."""
    findings: list[Finding] = []
    previous = ""
    for line in text.splitlines():
        if finding := _match(line, previous):
            findings.append(finding)
        if line.strip():
            previous = line
    return findings


def digest(output: str) -> Digest:
    text, suspicious = clean(output)
    findings = extract(text)
    return Digest(findings, suspicious, "" if findings else text[-MAX_EXCERPT:])
