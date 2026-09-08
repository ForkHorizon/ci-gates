#!/usr/bin/env python3
"""Fail-closed validation of a signed CI Scope policy record.

The control plane owns the policy record.  This module deliberately does not
fetch it: callers must provide the already trusted record and a local checkout.
That keeps network/authentication outside the executor while making the digest
and signature contract deterministic and testable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import base64
import binascii
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


POLICY_VERSION = 1
SHA256 = 64
SHA1 = 40


class PolicyError(ValueError):
    """Raised when a policy cannot be trusted or does not match the checkout."""


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


def _canonical(value: object) -> bytes:
    try:
        return (
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise PolicyError(f"policy is not canonical JSON: {error}") from error


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


def _safe_path(value: object, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\x00" in value
    ):
        raise PolicyError(f"{field} must be a non-empty path without whitespace or NUL")
    normalized = value.replace("\\", "/")
    path = Path(normalized)
    if path.is_absolute() or normalized in {".", ".."} or ".." in path.parts:
        raise PolicyError(f"{field} must be relative to the workspace")
    return path.as_posix()


def _safe_root_path(root: Path, relative: str) -> Path:
    root = Path(root).resolve()
    target = (root / relative).resolve(strict=False)
    try:
        target.relative_to(root)
    except ValueError as error:
        raise PolicyError(f"protected path escapes workspace: {relative}") from error
    return target


def _validate_sha(value: object, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != SHA256
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise PolicyError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _validate_git_sha(value: object, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != SHA1
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise PolicyError(f"{field} must be a lowercase Git SHA")
    return value


def _validate_patterns(values: object) -> tuple[str, ...]:
    if values is None:
        return ()
    if not isinstance(values, list) or any(
        not isinstance(item, str) for item in values
    ):
        raise PolicyError("protected_patterns must be an array of strings")
    result = tuple(_safe_path(item, field="protected_patterns[]") for item in values)
    if len(set(result)) != len(result):
        raise PolicyError("protected_patterns must not contain duplicates")
    return result


def _payload_from_record(record: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(record)
    payload.pop("signature", None)
    payload.pop("policy_digest", None)
    return payload


def load_policy_record(path: Path) -> PolicyRecord:  # noqa: PLR0912
    """Load and validate the immutable fields of one control-plane record."""

    path = Path(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise PolicyError(f"policy_missing: {path}") from error
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PolicyError(f"invalid policy record {path}: {error}") from error
    if not isinstance(value, dict):
        raise PolicyError("policy record must be a JSON object")
    if value.get("version") != POLICY_VERSION:
        raise PolicyError(f"unsupported policy version: {value.get('version')!r}")
    for field in ("repository", "branch", "approved_sha", "policy_digest", "files"):
        if field not in value:
            raise PolicyError(f"policy record missing {field}")
    if not isinstance(value["repository"], str) or not value["repository"].strip():
        raise PolicyError("repository must be a non-empty string")
    if not isinstance(value["branch"], str) or not value["branch"].strip():
        raise PolicyError("branch must be a non-empty string")
    _validate_git_sha(value["approved_sha"], field="approved_sha")
    expected_digest = _validate_sha(value["policy_digest"], field="policy_digest")
    entries = value["files"]
    if not isinstance(entries, list) or not entries:
        raise PolicyError("files must be a non-empty array")
    files: dict[str, str] = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256"}:
            raise PolicyError(f"files[{index}] must contain only path and sha256")
        relative = _safe_path(entry["path"], field=f"files[{index}].path")
        if relative in files:
            raise PolicyError(f"duplicate protected file: {relative}")
        files[relative] = _validate_sha(entry["sha256"], field=f"files[{index}].sha256")
    patterns = _validate_patterns(value.get("protected_patterns"))
    payload = _canonical(_payload_from_record(value))
    actual_digest = _sha256(payload)
    if actual_digest != expected_digest:
        raise PolicyError("policy_digest does not match the canonical policy payload")
    return PolicyRecord(value, payload, expected_digest, files, patterns)


def policy_payload(  # noqa: PLR0913
    *,
    repository: str,
    branch: str,
    approved_sha: str,
    files: Mapping[str, str],
    protected_patterns: Sequence[str] = (),
    gates_sha: str | None = None,
    checks: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Build the unsigned canonical payload used by the control plane."""

    normalized_files = [
        {
            "path": _safe_path(path, field="files.path"),
            "sha256": _validate_sha(digest, field="files.sha256"),
        }
        for path, digest in sorted(files.items())
    ]
    payload: dict[str, Any] = {
        "version": POLICY_VERSION,
        "repository": repository,
        "branch": branch,
        "approved_sha": _validate_git_sha(approved_sha, field="approved_sha"),
        "files": normalized_files,
    }
    if protected_patterns:
        payload["protected_patterns"] = sorted(
            {
                _safe_path(item, field="protected_patterns[]")
                for item in protected_patterns
            }
        )
    if gates_sha is not None:
        payload["gates_sha"] = _validate_git_sha(gates_sha, field="gates_sha")
    if checks:
        payload["checks"] = sorted(checks, key=lambda check: str(check.get("id", "")))
    return payload


def make_policy_record(**kwargs: Any) -> dict[str, Any]:
    """Create an unsigned record; the control plane adds signature afterwards."""

    payload = policy_payload(**kwargs)
    return {**payload, "policy_digest": _sha256(_canonical(payload))}


def _discovered_paths(root: Path, patterns: Sequence[str]) -> set[str]:
    discovered: set[str] = set()
    for pattern in patterns:
        # glob() does not follow symlinked directories when recursive=True.
        glob_pattern = f"{pattern}*" if pattern.endswith("/**") else pattern
        for candidate in root.glob(glob_pattern):
            relative = candidate.relative_to(root).as_posix()
            if candidate.is_file() or candidate.is_symlink():
                _safe_root_path(root, relative)
                discovered.add(relative)
    return discovered


def compute_workspace_digest(
    root: Path, paths: Sequence[str]
) -> tuple[str, dict[str, str], tuple[str, ...]]:
    """Hash protected files and return aggregate digest plus missing paths."""

    root = Path(root).resolve()
    actual: dict[str, str] = {}
    missing: list[str] = []
    for relative in sorted(set(paths)):
        path = _safe_root_path(root, relative)
        if not path.is_file() or path.is_symlink():
            missing.append(relative)
            continue
        actual[relative] = _sha256_file(path)
    aggregate = _sha256(
        _canonical([{"path": path, "sha256": actual[path]} for path in sorted(actual)])
    )
    return aggregate, actual, tuple(missing)


def _verify_signature(record: PolicyRecord, *, allowed_signers: Path | None) -> None:
    signature = record.value.get("signature")
    if not isinstance(signature, dict):
        raise PolicyError("policy_signature_invalid: signature is required")
    if signature.get("algorithm") != "ed25519":
        raise PolicyError("policy_signature_invalid: unsupported signature algorithm")
    identity = signature.get("identity")
    encoded = signature.get("value")
    if (
        not isinstance(identity, str)
        or not identity
        or not isinstance(encoded, str)
        or not encoded
    ):
        raise PolicyError("policy_signature_invalid: malformed SSH signature")
    if allowed_signers is None or not Path(allowed_signers).is_file():
        raise PolicyError(
            "policy_signature_invalid: allowed signers file is unavailable"
        )
    with tempfile.TemporaryDirectory(prefix="ci-scope-policy-") as directory:
        signature_path = Path(directory) / "signature"
        payload_path = Path(directory) / "payload"
        payload_path.write_bytes(record.payload)
        try:
            signature_path.write_bytes(base64.b64decode(encoded, validate=True))
        except (ValueError, binascii.Error) as error:
            raise PolicyError("policy_signature_invalid: malformed Ed25519 signature") from error
        command = [
            "openssl", "pkeyutl", "-verify", "-pubin", "-inkey", str(Path(allowed_signers)),
            "-rawin", "-in", str(payload_path), "-sigfile", str(signature_path)
        ]
        try:
            completed = subprocess.run(
                command, capture_output=True, check=False
            )
        except OSError as error:
            raise PolicyError(
                f"policy_signature_invalid: cannot run ssh-keygen: {error}"
            ) from error
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()[:200]
        raise PolicyError(
            f"policy_signature_invalid: Ed25519 signature verification failed{': ' + detail if detail else ''}"
        )


def preflight(  # noqa: PLR0913
    root: Path,
    policy_path: Path,
    *,
    repository: str | None = None,
    branch: str | None = None,
    base_sha: str | None = None,
    gates_sha: str | None = None,
    require_signature: bool = True,
    allowed_signers: Path | None = None,
) -> PolicyResult:
    """Verify policy identity, optional signature, and exact protected files."""

    try:
        record = load_policy_record(policy_path)
        if repository is not None and record.value["repository"] != repository:
            raise PolicyError("policy_mismatch: repository does not match")
        if branch is not None and record.value["branch"] != branch:
            raise PolicyError("policy_mismatch: branch does not match")
        if base_sha is not None and record.value["approved_sha"] != base_sha:
            raise PolicyError("policy_mismatch: approved base SHA does not match")
        if gates_sha is not None and record.value.get("gates_sha") != gates_sha:
            raise PolicyError("policy_mismatch: pinned ci-gates SHA does not match")
        if require_signature:
            _verify_signature(record, allowed_signers=allowed_signers)
        paths = set(record.files)
        paths.update(_discovered_paths(Path(root).resolve(), record.patterns))
        actual_digest, actual, missing = compute_workspace_digest(root, sorted(paths))
        mismatches = sorted(
            [f"missing:{path}" for path in missing]
            + [
                f"changed:{path}"
                for path, digest in record.files.items()
                if actual.get(path) != digest
            ]
            + [f"unexpected:{path}" for path in actual if path not in record.files]
        )
        if mismatches:
            return PolicyResult(
                "policy_mismatch",
                "protected files differ from approved policy",
                record.policy_digest,
                actual_digest,
                tuple(mismatches),
            )
        return PolicyResult(
            "passed", policy_digest=record.policy_digest, actual_digest=actual_digest
        )
    except PolicyError as error:
        message = str(error)
        if "policy_signature_invalid" in message:
            status = "policy_signature_invalid"
        elif "policy_missing" in message:
            status = "policy_missing"
        elif "policy_mismatch" in message:
            status = "policy_mismatch"
        else:
            status = "policy_invalid"
        return PolicyResult(status, message)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--repository")
    parser.add_argument("--branch")
    parser.add_argument(
        "--base-sha", help="Approved base commit expected by the policy record"
    )
    parser.add_argument("--allowed-signers", type=Path)
    parser.add_argument(
        "--allow-unsigned",
        action="store_true",
        help="Only for local policy generation/tests",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    result = preflight(
        args.root,
        args.policy,
        repository=args.repository,
        branch=args.branch,
        base_sha=args.base_sha,
        require_signature=not args.allow_unsigned,
        allowed_signers=args.allowed_signers,
    )
    print(
        json.dumps(
            {
                "status": result.status,
                "reason": result.reason,
                "policy_digest": result.policy_digest,
                "actual_digest": result.actual_digest,
                "mismatches": list(result.mismatches),
            },
            sort_keys=True,
        )
    )
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
