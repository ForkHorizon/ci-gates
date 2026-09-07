"""Write small, safe check reports for CI artifacts."""

import json
import os
import re
import tempfile
from pathlib import Path


MAX_BYTES = 64 * 1024
MAX_LOG_BYTES = 64 * 1024
MAX_TEXT = 200
MAX_EVENTS = 1000
_SECRET = re.compile(
    r"(?i)(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}|"
    r"(?:token|secret|password|passwd|credential|api[_-]?key|private[_-]?key)\s*[:=]\s*[^\s,;]+|"
    r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16})\b|"
    r"https?://[^/\s:@]+:[^@\s]+@"
)
_PATH = re.compile(r"(?i)file:///[^\s,;]+|(?<![\w:/])/(?:[^\s,;]+)|[A-Za-z]:[\\/][^\s,;]+")


def _safe(value, depth=0):
    if depth > 4:
        return "[TRUNCATED]"
    if isinstance(value, str):
        return safe_text(value)[:MAX_TEXT]
    if isinstance(value, dict):
        return {str(_safe(k, depth + 1))[:MAX_TEXT]: _safe(v, depth + 1) for k, v in list(value.items())[:50]}
    if isinstance(value, (list, tuple)):
        return [_safe(v, depth + 1) for v in value[:50]]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _safe(str(value), depth + 1)


def safe_text(value: str) -> str:
    """Redact paths and credentials before text is persisted."""
    return _PATH.sub("[REDACTED_PATH]", _SECRET.sub("[REDACTED]", str(value)))


class BoundedLog:
    """File-like sink that redacts and caps subprocess output."""

    def __init__(self, stream, limit=MAX_LOG_BYTES):
        self.stream, self.limit, self.size, self.truncated = stream, limit, 0, False

    def write(self, value):
        if self.truncated:
            return len(value)
        data = safe_text(value).encode("utf-8")
        remaining = self.limit - self.size
        if len(data) > remaining:
            marker = b"\n[TRUNCATED]\n"
            data = data[: max(0, remaining - len(marker))]
            self.truncated = True
        self.stream.write(data.decode("utf-8", errors="ignore"))
        self.size += len(data)
        if self.truncated:
            marker = "\n[TRUNCATED]\n"
            self.stream.write(marker[: max(0, self.limit - self.size)])
            self.size += min(len(marker), self.limit - self.size)
        return len(value)

    def flush(self):
        self.stream.flush()


def _atomic_text(path: Path, payload: str):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if len(payload.encode()) > MAX_BYTES:
        raise ValueError("report exceeds size limit")
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _write_json(path: Path, value):
    _atomic_text(path, json.dumps(_safe(value), sort_keys=True, separators=(",", ":")) + "\n")


def write_events(path, events):
    """Atomically replace bounded events.jsonl."""
    events = list(events)[-MAX_EVENTS:]
    payload = "\n".join(json.dumps(_safe(event), sort_keys=True, separators=(",", ":")) for event in events)
    _atomic_text(Path(path), payload + ("\n" if payload else ""))


def write_result(path, result, *, ordinary_ms=None, ai_ms=None):
    result = dict(result)
    if ordinary_ms is not None or ai_ms is not None:
        result["timings"] = {"ordinary_ms": ordinary_ms or 0, "ai_ms": ai_ms or 0}
    _write_json(Path(path), result)


def write_report(directory, events, result, *, ordinary_ms=None, ai_ms=None):
    directory = Path(directory)
    write_events(directory / "events.jsonl", events)
    write_result(directory / "result.json", result, ordinary_ms=ordinary_ms, ai_ms=ai_ms)
