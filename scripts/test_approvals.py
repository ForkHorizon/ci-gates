"""Owner approvals for edits to existing tests: what a gate accepts, and the items a request to the owner lists."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

try:
    from protected_files import fingerprint_file
except ModuleNotFoundError:
    from .protected_files import fingerprint_file

Approvals = dict[str, set[str | None]]


@dataclass
class ApprovalState:
    """What the owner approved, and (filled by a scan) the edits still waiting for a decision."""

    approved: Approvals = field(default_factory=dict)
    requests: list[dict] = field(default_factory=list)
    # Content the owner approved as protected files: it also clears a runner-config change of that exact content.
    config_approved: Approvals = field(default_factory=dict)


def load_approvals(path: Path | None) -> Approvals:
    """`{path: {fingerprint or None}}` from the JSON a gate run wrote (`[{"path", "fingerprint"}]`); empty if absent."""
    if path is None or not path.is_file():
        return {}
    approvals: Approvals = {}
    for entry in json.loads(path.read_text(encoding="utf-8")):
        approvals.setdefault(entry["path"], set()).add(entry["fingerprint"])
    return approvals


def _content(root: Path, rev: str | None, path: str) -> str | None:
    """The file at a commit, or in the working tree when `rev` is None; None when it does not exist."""
    if rev is None:
        file = root / path
        return file.read_text(encoding="utf-8", errors="replace") if file.is_file() and not file.is_symlink() else None
    result = subprocess.run(["git", "show", f"{rev}:{path}"], cwd=root, capture_output=True, text=True, check=False)
    return None if result.returncode else result.stdout


def _fingerprint(root: Path, rev: str | None, path: str) -> str | None:
    content = _content(root, rev, path)
    return None if content is None else fingerprint_file(path, content)


def change_item(root: Path, revs: tuple[str | None, str], kind: str, path: str) -> dict:
    """One file the request asks about: its content now (`revs[0]`, None = working tree) against `revs[1]`."""
    now, base = revs
    return {
        "path": path,
        "kind": kind,
        "fingerprint": None if kind == "deleted" else _fingerprint(root, now, path),
        "previous": None if kind == "added" else _fingerprint(root, base, path),
    }


def all_approved(items: list[dict], approvals: Approvals) -> bool:
    return all(item["fingerprint"] in approvals.get(item["path"], ()) for item in items)
