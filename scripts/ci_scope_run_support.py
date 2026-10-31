"""Manifest preparation helpers for the unified check runner."""

from __future__ import annotations

import hashlib
import json

from ci_scope_manifest import resolve_manifest_file
from ci_scope_models import ResolvedManifest
from policy_preflight import PolicyError, preflight


def prepare_manifest(args) -> tuple[ResolvedManifest, str]:
    policy_path = getattr(args, "policy", None)
    if policy_path is not None:
        result = preflight(
            args.root,
            policy_path,
            repository=getattr(args, "policy_repository", None),
            branch=getattr(args, "policy_branch", None),
            base_sha=getattr(args, "policy_base_sha", None),
            require_signature=not getattr(args, "allow_unsigned_policy", False),
            allowed_signers=getattr(args, "allowed_signers", None),
        )
        if not result.passed:
            raise PolicyError(f"{result.status}: {result.reason}")
    path = args.config.resolve()
    manifest = resolve_manifest_file(path, root=args.root.resolve(), event=args.event)
    return manifest, hashlib.sha256(path.read_bytes()).hexdigest()


def print_validation(manifest: ResolvedManifest, digest: str, tier: str) -> None:
    print(
        json.dumps(
            {
                "version": manifest.version,
                "checks": [check.id for check in manifest.active_checks],
                "tier": tier,
                "tiers": {check.id: check.speed for check in manifest.active_checks},
                "manifest_sha256": digest,
            },
            indent=2,
        )
    )
