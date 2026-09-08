#!/usr/bin/env python3
"""Fail-closed validation of a signed CI Scope policy record."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

try:
    from .policy_preflight_models import PolicyError, PolicyRecord, PolicyResult
    from .policy_preflight_workspace import _canonical, compute_workspace_digest, discovered_paths, verify_signature
except ImportError:
    from policy_preflight_models import PolicyError, PolicyRecord, PolicyResult
    from policy_preflight_workspace import _canonical, compute_workspace_digest, discovered_paths, verify_signature

POLICY_VERSION = 1
SHA256, SHA1 = 64, 40


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_path(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or "\x00" in value:
        raise PolicyError(f"{field} must be a non-empty path without whitespace or NUL")
    normalized = value.replace("\\", "/")
    path = Path(normalized)
    if path.is_absolute() or normalized in {".", ".."} or ".." in path.parts:
        raise PolicyError(f"{field} must be relative to the workspace")
    return path.as_posix()


def _validate_sha(value: object, *, field: str) -> str:
    if not isinstance(value, str) or len(value) != SHA256 or any(char not in "0123456789abcdef" for char in value):
        raise PolicyError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _validate_git_sha(value: object, *, field: str) -> str:
    if not isinstance(value, str) or len(value) != SHA1 or any(char not in "0123456789abcdef" for char in value):
        raise PolicyError(f"{field} must be a lowercase Git SHA")
    return value


def _validate_patterns(values: object) -> tuple[str, ...]:
    if values is None:
        return ()
    if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
        raise PolicyError("protected_patterns must be an array of strings")
    result = tuple(_safe_path(item, field="protected_patterns[]") for item in values)
    if len(set(result)) != len(result):
        raise PolicyError("protected_patterns must not contain duplicates")
    return result


def load_policy_record(path: Path) -> PolicyRecord:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise PolicyError(f"policy_missing: {path}") from error
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PolicyError(f"invalid policy record {path}: {error}") from error
    if not isinstance(value, dict) or value.get("version") != POLICY_VERSION:
        shown = value.get("version") if isinstance(value, dict) else value
        raise PolicyError(f"unsupported policy version: {shown!r}")
    for field in ("repository", "branch", "approved_sha", "policy_digest", "files"):
        if field not in value:
            raise PolicyError(f"policy record missing {field}")
    if not isinstance(value["repository"], str) or not value["repository"].strip() or not isinstance(value["branch"], str) or not value["branch"].strip():
        raise PolicyError("repository and branch must be non-empty strings")
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
    payload = dict(value)
    payload.pop("signature", None)
    payload.pop("policy_digest", None)
    canonical = _canonical(payload)
    if _sha256(canonical) != expected_digest:
        raise PolicyError("policy_digest does not match the canonical policy payload")
    return PolicyRecord(value, canonical, expected_digest, files, _validate_patterns(value.get("protected_patterns")))


def policy_payload(**kwargs: Any) -> dict[str, Any]:
    files = kwargs["files"]
    payload: dict[str, Any] = {
        "version": POLICY_VERSION,
        "repository": kwargs["repository"],
        "branch": kwargs["branch"],
        "approved_sha": _validate_git_sha(kwargs["approved_sha"], field="approved_sha"),
        "files": [{"path": _safe_path(path, field="files.path"), "sha256": _validate_sha(digest, field="files.sha256")} for path, digest in sorted(files.items())],
    }
    patterns = kwargs.get("protected_patterns", ())
    if patterns:
        payload["protected_patterns"] = sorted({_safe_path(item, field="protected_patterns[]") for item in patterns})
    if kwargs.get("gates_sha") is not None:
        payload["gates_sha"] = _validate_git_sha(kwargs["gates_sha"], field="gates_sha")
    if kwargs.get("checks"):
        payload["checks"] = sorted(kwargs["checks"], key=lambda check: str(check.get("id", "")))
    return payload


def make_policy_record(**kwargs: Any) -> dict[str, Any]:
    payload = policy_payload(**kwargs)
    return {**payload, "policy_digest": _sha256(_canonical(payload))}


def preflight(root: Path, policy_path: Path, **options: Any) -> PolicyResult:
    try:
        record = load_policy_record(policy_path)
        for field in ("repository", "branch"):
            if options.get(field) is not None and record.value[field] != options[field]:
                raise PolicyError(f"policy_mismatch: {field} does not match")
        if options.get("base_sha") is not None and record.value["approved_sha"] != options["base_sha"]:
            raise PolicyError("policy_mismatch: approved base SHA does not match")
        if options.get("gates_sha") is not None and record.value.get("gates_sha") != options["gates_sha"]:
            raise PolicyError("policy_mismatch: pinned ci-gates SHA does not match")
        if options.get("require_signature", True):
            verify_signature(record, allowed_signers=options.get("allowed_signers"))
        paths = set(record.files)
        paths.update(discovered_paths(Path(root).resolve(), record.patterns))
        actual_digest, actual, missing = compute_workspace_digest(root, sorted(paths))
        mismatches = sorted(
            [f"missing:{path}" for path in missing]
            + [f"changed:{path}" for path, digest in record.files.items() if actual.get(path) != digest]
            + [f"unexpected:{path}" for path in actual if path not in record.files]
        )
        if mismatches:
            return PolicyResult("policy_mismatch", "protected files differ from approved policy", record.policy_digest, actual_digest, tuple(mismatches))
        return PolicyResult("passed", policy_digest=record.policy_digest, actual_digest=actual_digest)
    except PolicyError as error:
        message = str(error)
        status = next((name for name in ("policy_signature_invalid", "policy_missing", "policy_mismatch") if name in message), "policy_invalid")
        return PolicyResult(status, message)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--repository")
    parser.add_argument("--branch")
    parser.add_argument("--base-sha")
    parser.add_argument("--allowed-signers", type=Path)
    parser.add_argument("--allow-unsigned", action="store_true")
    args = parser.parse_args(argv)
    result = preflight(args.root, args.policy, repository=args.repository, branch=args.branch, base_sha=args.base_sha, require_signature=not args.allow_unsigned, allowed_signers=args.allowed_signers)
    print(json.dumps({"status": result.status, "reason": result.reason, "policy_digest": result.policy_digest, "actual_digest": result.actual_digest, "mismatches": list(result.mismatches)}, sort_keys=True))
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
