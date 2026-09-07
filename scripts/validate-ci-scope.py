#!/usr/bin/env python3
"""Validate a project's CI Scope manifest without executing project code."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ci_scope_manifest import ManifestError, canonical_manifest, validate_only


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a CI Scope project manifest.")
    parser.add_argument("--root", type=Path, required=True, help="project workspace")
    parser.add_argument("--config", type=Path, default=None, help="manifest path (default: ROOT/.ci-scope.json)")
    parser.add_argument("--event", choices=("pull_request", "push", "merge_group", "workflow_dispatch", "schedule"))
    parser.add_argument("--validate-only", action="store_true", help="accepted for runner CLI compatibility")
    args = parser.parse_args(argv)
    path = args.config or args.root / ".ci-scope.json"
    try:
        manifest = validate_only(path, root=args.root, event=args.event)
    except ManifestError as error:
        print(f"ci-scope manifest error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(canonical_manifest(manifest), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
