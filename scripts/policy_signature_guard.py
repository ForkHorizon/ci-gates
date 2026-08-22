#!/usr/bin/env python3
"""Fail-closed cryptographic signature verification for protected policy files.

Ensures that normal code changes (C#, Python, Swift, etc.) can be contributed
freely by agents or human developers without friction, while any modifications
to linter rules, quality gates, or CI workflows strictly require a verified
cryptographic SSH or GPG signature from an approved code owner.
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

DEFAULT_PROTECTED_PATTERNS = (
    ".code-linter.json",
    "**/.code-linter.json",
    ".ruff.toml",
    "**/.ruff.toml",
    "ruff.toml",
    "**/ruff.toml",
    ".unity-quality-gate.json",
    "**/.unity-quality-gate.json",
    ".swift-quality-gate.json",
    "**/.swift-quality-gate.json",
    ".slop-review.json",
    "**/.slop-review.json",
    ".github/workflows/*",
    ".github/workflows/**",
    ".github/CODEOWNERS",
    "**/.github/CODEOWNERS",
    "configs/allowed_signers",
)

DEFAULT_ALLOWED_SIGNERS = Path(__file__).resolve().parents[1] / "configs" / "allowed_signers"


def is_protected_file(path_str: str, patterns: Sequence[str] = DEFAULT_PROTECTED_PATTERNS) -> bool:
    normalized = path_str.replace("\\", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    basename = os.path.basename(normalized)
    for pattern in patterns:
        if fnmatch.fnmatch(normalized, pattern) or fnmatch.fnmatch(basename, pattern):
            return True
    return False


def git_cmd(root: Path, args: list[str]) -> tuple[int, str, str]:
    env = dict(os.environ)
    if "GIT_CONFIG_GLOBAL" not in env:
        env["GIT_CONFIG_GLOBAL"] = "/dev/null"
    if "GIT_CONFIG_NOSYSTEM" not in env:
        env["GIT_CONFIG_NOSYSTEM"] = "1"
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        check=False,
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def find_changed_protected_files(
    root: Path,
    base: str,
    head: str,
    patterns: Sequence[str] = DEFAULT_PROTECTED_PATTERNS,
) -> list[str]:
    code, stdout, stderr = git_cmd(root, ["diff", "--name-only", f"{base}...{head}"])
    if code != 0:
        # Fallback to direct two-dot diff if three-dot is unavailable
        code, stdout, stderr = git_cmd(root, ["diff", "--name-only", base, head])
        if code != 0:
            raise RuntimeError(f"Failed to calculate git diff between {base} and {head}: {stderr}")

    changed = [line.strip() for line in stdout.splitlines() if line.strip()]
    return [path for path in changed if is_protected_file(path, patterns)]


def verify_commit_signature(
    root: Path,
    commit_sha: str,
    allowed_signers: Path,
) -> tuple[bool, str, str]:
    """Verify commit signature using Git's built-in SSH/GPG verification.

    Returns:
        (is_valid, signer_identity, failure_reason)
    """
    if not allowed_signers.exists():
        return False, "", f"Allowed signers file not found: {allowed_signers}"

    args = [
        "-c",
        f"gpg.ssh.allowedSignersFile={allowed_signers.as_posix()}",
        "log",
        "-1",
        "--format=%G?|%GS|%GK|%GT",
        commit_sha,
    ]
    code, stdout, stderr = git_cmd(root, args)
    if code != 0:
        return False, "", f"git log failed on commit {commit_sha}: {stderr}"

    parts = stdout.split("|")
    status = parts[0].strip() if len(parts) > 0 else "N"
    signer = parts[1].strip() if len(parts) > 1 else ""
    key_fingerprint = parts[2].strip() if len(parts) > 2 else ""

    # Status explanations in Git:
    # G = Good (valid) signature
    # B = Bad signature
    # U = Good signature with unknown validity (untrusted key)
    # X = Expired signature
    # Y = Expired key
    # R = Revoked key
    # E = Signature cannot be checked
    # N = No signature
    if status == "G":
        return True, signer or key_fingerprint, ""
    if status == "N":
        return False, "", "Commit is unsigned (no cryptographic signature present)"
    if status == "U":
        return False, signer, f"Signature exists but is from an untrusted / unauthorized key ({signer or key_fingerprint})"
    if status == "B":
        return False, signer, "Signature is corrupt or invalid (BAD signature)"
    return False, signer, f"Signature verification failed with status code '{status}'"


def audit_policy_signatures(
    root: Path,
    base: str,
    head: str,
    allowed_signers: Path = DEFAULT_ALLOWED_SIGNERS,
    patterns: Sequence[str] = DEFAULT_PROTECTED_PATTERNS,
) -> list[str]:
    """Audit all commits in range modifying protected policy files."""
    protected_files = find_changed_protected_files(root, base, head, patterns)
    if not protected_files:
        return []

    errors: list[str] = []
    # Find all commits that touched these specific protected files
    code, stdout, stderr = git_cmd(
        root,
        ["log", f"{base}..{head}", "--format=%H", "--", *protected_files],
    )
    if code != 0:
        # Fallback if range fails
        code, stdout, stderr = git_cmd(
            root,
            ["log", "-n", "20", "--format=%H", "--", *protected_files],
        )

    commits = [line.strip() for line in stdout.splitlines() if line.strip()]
    if not commits and protected_files:
        # If git log range was empty but diff has files (e.g. uncommitted/head), check HEAD
        commits = [head]

    for commit in commits:
        valid, signer, reason = verify_commit_signature(root, commit, allowed_signers)
        if not valid:
            for pf in protected_files:
                err_msg = (
                    f"::error file={pf},line=1,title=Policy Signature Required::"
                    f"Commit {commit[:8]} modified protected policy file '{pf}' without a valid "
                    f"signature from a trusted code owner. Reason: {reason}."
                )
                errors.append(err_msg)

    return errors


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Repository root directory")
    parser.add_argument("--base", default="origin/main", help="Base git ref for diff comparison")
    parser.add_argument("--head", default="HEAD", help="Head git ref for diff comparison")
    parser.add_argument(
        "--allowed-signers",
        type=Path,
        default=DEFAULT_ALLOWED_SIGNERS,
        help="Path to allowed_signers file",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        errors = audit_policy_signatures(
            root=args.root,
            base=args.base,
            head=args.head,
            allowed_signers=args.allowed_signers,
        )
    except Exception as exc:
        print(f"::error title=Policy Signature Guard Failure::{exc}", file=sys.stderr)
        return 2

    if errors:
        for err in errors:
            print(err, file=sys.stderr)
        print(
            f"\n❌ Policy Signature Verification FAILED: {len(errors)} violation(s) detected.\n"
            "Modifications to linter configurations and CI workflows require a verified commit signature from an authorized code owner (@daliys).\n"
            "Unsigned changes generated by AI agents are strictly blocked from merging.",
            file=sys.stderr,
        )
        return 1

    print("✅ Policy Signature Guard: All policy modifications are authorized by verified code owners (or only regular source files were modified).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
