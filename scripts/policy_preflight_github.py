#!/usr/bin/env python3
"""Fetch and validate a trusted CI Scope policy before candidate execution."""
from __future__ import annotations

import argparse
import base64
import fnmatch
import json
import os
from pathlib import Path
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from policy_preflight import PolicyError, preflight


def api_get(url: str, token: str) -> object:
    request = Request(url, headers={"accept": "application/vnd.github+json", "authorization": f"Bearer {token}"})
    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, ValueError) as error:
        raise PolicyError(f"policy_service_unavailable: GitHub API request failed: {error}") from error


def fetch_policy(url: str, repository: str, branch: str, token: str) -> dict:
    query = urlencode({"repository": repository, "branch": branch})
    value = api_get(f"{url.rstrip('/')}?{query}", token)
    if not isinstance(value, dict) or not isinstance(value.get("record"), dict):
        raise PolicyError("policy_service_unavailable: malformed policy response")
    record = value["record"]
    if "signature" not in record and isinstance(value.get("signature"), dict):
        record["signature"] = value["signature"]
    if "policy_digest" not in record and isinstance(value.get("policyDigest"), str):
        record["policy_digest"] = value["policyDigest"]
    return record


def tree_paths(api_base: str, repository: str, revision: str, token: str) -> list[str]:
    value = api_get(f"{api_base}/repos/{repository}/git/trees/{quote(revision, safe='')}?recursive=1", token)
    if not isinstance(value, dict) or value.get("truncated") is True or not isinstance(value.get("tree"), list):
        raise PolicyError("policy_service_unavailable: repository tree unavailable or truncated")
    return [item["path"] for item in value["tree"] if isinstance(item, dict) and item.get("type") == "blob" and isinstance(item.get("path"), str)]


def file_bytes(api_base: str, repository: str, revision: str, path: str, token: str) -> bytes | None:
    encoded = quote(path, safe="/")
    try:
        value = api_get(f"{api_base}/repos/{repository}/contents/{encoded}?ref={quote(revision, safe='')}", token)
    except PolicyError as error:
        if "HTTP Error 404" in str(error):
            return None
        raise
    if not isinstance(value, dict) or value.get("encoding") != "base64" or not isinstance(value.get("content"), str):
        raise PolicyError(f"policy_service_unavailable: invalid content response for {path}")
    try:
        return base64.b64decode(value["content"], validate=False)
    except (ValueError, TypeError) as error:
        raise PolicyError(f"policy_service_unavailable: invalid content encoding for {path}") from error


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--policy-url", required=True)
    parser.add_argument("--github-api", default="https://api.github.com")
    parser.add_argument("--github-token", default=os.environ.get("GITHUB_TOKEN", ""))
    parser.add_argument("--policy-token", default=os.environ.get("CI_SCOPE_POLICY_READ_TOKEN", ""))
    parser.add_argument("--allowed-signers", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.github_token or not args.policy_token:
        raise SystemExit("policy_service_unavailable: GitHub and policy tokens are required")

    record = fetch_policy(args.policy_url, args.repository, args.branch, args.policy_token)
    with tempfile.TemporaryDirectory(prefix="ci-scope-policy-checkout-") as directory:
        root = Path(directory)
        policy_path = root / "policy.json"
        policy_path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        paths = {entry["path"] for entry in record.get("files", []) if isinstance(entry, dict) and isinstance(entry.get("path"), str)}
        all_paths = tree_paths(args.github_api, args.repository, args.head_sha, args.github_token)
        for pattern in record.get("protected_patterns", []):
            if isinstance(pattern, str):
                paths.update(path for path in all_paths if fnmatch.fnmatchcase(path, pattern))
        for path in sorted(paths):
            content = file_bytes(args.github_api, args.repository, args.head_sha, path, args.github_token)
            if content is not None:
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
        result = preflight(root, policy_path, repository=args.repository, branch=args.branch, base_sha=args.base_sha, allowed_signers=args.allowed_signers)
        print(json.dumps({"status": result.status, "reason": result.reason, "mismatches": list(result.mismatches)}, sort_keys=True))
        if not result.passed:
            return 1
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PolicyError as error:
        print(json.dumps({"status": "policy_blocked", "reason": str(error)}, sort_keys=True))
        raise SystemExit(1) from error
