from __future__ import annotations

import base64
import binascii
import hashlib
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path

try:
    from .policy_preflight_models import PolicyError, PolicyRecord
except ImportError:
    from policy_preflight_models import PolicyError, PolicyRecord


def _canonical(value: object) -> bytes:
    import json

    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as error:
        raise PolicyError(f"cannot read protected file {path}: {error}") from error
    return digest.hexdigest()


def safe_root_path(root: Path, relative: str) -> Path:
    root = Path(root).resolve()
    target = (root / relative).resolve(strict=False)
    try:
        target.relative_to(root)
    except ValueError as error:
        raise PolicyError(f"protected path escapes workspace: {relative}") from error
    return target


def discovered_paths(root: Path, patterns: Sequence[str]) -> set[str]:
    discovered: set[str] = set()
    for pattern in patterns:
        if pattern.endswith("/**"):
            base = root / pattern[:-3].rstrip("/")
            candidates = base.rglob("*") if base.is_dir() else ()
        else:
            candidates = root.glob(pattern)
        for candidate in candidates:
            relative = candidate.relative_to(root).as_posix()
            if candidate.is_file() or candidate.is_symlink():
                safe_root_path(root, relative)
                discovered.add(relative)
    return discovered


def compute_workspace_digest(root: Path, paths: Sequence[str]) -> tuple[str, dict[str, str], tuple[str, ...]]:
    root = Path(root).resolve()
    actual: dict[str, str] = {}
    missing: list[str] = []
    for relative in sorted(set(paths)):
        path = safe_root_path(root, relative)
        if not path.is_file() or path.is_symlink():
            missing.append(relative)
            continue
        actual[relative] = _sha256_file(path)
    aggregate = _sha256(_canonical([{"path": path, "sha256": actual[path]} for path in sorted(actual)]))
    return aggregate, actual, tuple(missing)


def verify_signature(record: PolicyRecord, *, allowed_signers: Path | None) -> None:
    signature = record.value.get("signature")
    if not isinstance(signature, dict) or signature.get("algorithm") != "ed25519":
        raise PolicyError("policy_signature_invalid: malformed signature")
    identity, encoded = signature.get("identity"), signature.get("value")
    if not isinstance(identity, str) or not identity or not isinstance(encoded, str) or not encoded:
        raise PolicyError("policy_signature_invalid: malformed SSH signature")
    if allowed_signers is None or not Path(allowed_signers).is_file():
        raise PolicyError("policy_signature_invalid: allowed signers file is unavailable")
    with tempfile.TemporaryDirectory(prefix="ci-scope-policy-") as directory:
        signature_path, payload_path = Path(directory) / "signature", Path(directory) / "payload"
        payload_path.write_bytes(record.payload)
        try:
            signature_path.write_bytes(base64.b64decode(encoded, validate=True))
        except (ValueError, binascii.Error) as error:
            raise PolicyError("policy_signature_invalid: malformed Ed25519 signature") from error
        command = ["openssl", "pkeyutl", "-verify", "-pubin", "-inkey", str(Path(allowed_signers)), "-rawin", "-in", str(payload_path), "-sigfile", str(signature_path)]
        try:
            completed = subprocess.run(command, capture_output=True, check=False)
        except OSError as error:
            raise PolicyError(f"policy_signature_invalid: cannot run openssl: {error}") from error
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()[:200]
        suffix = f": {detail}" if detail else ""
        raise PolicyError(f"policy_signature_invalid: Ed25519 signature verification failed{suffix}")
