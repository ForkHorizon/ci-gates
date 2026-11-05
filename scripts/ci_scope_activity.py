"""Live progress for the CI Scope agent: which gate runs and what it is doing, as one JSON event per stderr line.

Silent unless the agent asks (CI_SCOPE_ACTIVITY=1), so people and git hooks never see it. Gates already print
`::ci-scope-progress:: {json}` markers (see _progress.py); the runner captures their output to a file, so this
module reads new lines from that file while the command runs and relays the markers.
"""

from __future__ import annotations

import json
import os
import sys
import threading

MARKER = "::ci-scope-progress::"
CURRENT = {"check": ""}  # the check whose command is running; markers are credited to it
POLL_SECONDS = 1.0


def emit(event: dict) -> None:
    if os.environ.get("CI_SCOPE_ACTIVITY") == "1":
        print("@@activity " + json.dumps(event, ensure_ascii=False), file=sys.stderr, flush=True)


def parse_marker(line: str) -> dict | None:
    """The progress payload of one output line, or None when the line is not a marker."""
    text = line.strip()
    if not text.startswith(MARKER):
        return None
    data = text[len(MARKER) :].replace("%0A", "\n").replace("%0D", "\r").replace("%25", "%")
    try:
        payload = json.loads(data)
    except ValueError:
        return None
    return payload if isinstance(payload, dict) and isinstance(payload.get("step"), str) else None


def marker_event(check: str, payload: dict) -> dict:
    event = {"check": check, "state": "running", "step": payload["step"]}
    for key in ("current", "total", "detail"):
        if key in payload:
            event[key] = payload[key]
    return event


class MarkerTail:
    """Relays the markers a running command writes to its output file `fd`; `stop()` after the command ends."""

    def __init__(self, fd: int) -> None:
        self.fd, self.offset, self.pending = fd, 0, b""
        self.done = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def __enter__(self) -> MarkerTail:
        if os.environ.get("CI_SCOPE_ACTIVITY") == "1":
            self.thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.done.set()
        if self.thread.is_alive():
            self.thread.join()

    def _run(self) -> None:
        while True:
            finished = self.done.wait(POLL_SECONDS)
            self._read()  # one last pass after the command ended, so the final marker is not lost
            if finished:
                return

    def _read(self) -> None:
        chunk = os.pread(self.fd, 1 << 16, self.offset)
        while chunk:
            self.offset += len(chunk)
            self.pending += chunk
            *lines, self.pending = self.pending.split(b"\n")
            last = None
            for raw in lines:
                payload = parse_marker(raw.decode("utf-8", errors="replace"))
                last = payload or last
            if last:  # only the newest of a burst: the screen cannot show more than that anyway
                emit(marker_event(CURRENT["check"], last))
            chunk = os.pread(self.fd, 1 << 16, self.offset)
