#!/usr/bin/env python3
"""`ci-scope check`: run the project's server-held checks on the local working tree.

The server owns the config, so the repository under test cannot weaken it. This tool only reads.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path

try:
    from ci_scope_adapters import commands_for
    from protected_files import check_protected_files, fingerprint_file, select_protected_paths
    from server_config import build_check_specs
except ModuleNotFoundError:
    from .ci_scope_adapters import commands_for
    from .protected_files import check_protected_files, fingerprint_file, select_protected_paths
    from .server_config import build_check_specs

TIERS = {"edit": {"fast"}, "commit": {"fast"}, "push": {"fast", "full"}}
TOKEN_HEADER = "x-ci-scope-config-token"
MAX_DETAIL = 160
MAX_OUTPUT = 4_000

Fetch = Callable[[str, str], dict]
Runner = Callable[[list[str], Path], tuple[int, str]]


class CliError(RuntimeError):
    pass


class NotRegistered(CliError):
    """The server has no config for this repository."""


class ServerUnavailable(CliError):
    """The server could not be reached or answered with an error."""


def canonical_config(config: dict) -> str:
    """Same text as the server's canonicalConfig: sorted keys, compact, trailing newline."""
    return json.dumps(config, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else ""


def repository_slug(root: Path) -> str:
    match = re.search(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?$", git(root, "remote", "get-url", "origin"))
    if not match:
        raise NotRegistered("cannot tell the GitHub repository from the origin remote")
    return f"{match.group(1)}/{match.group(2)}"


def device_settings(environ: dict[str, str] | None = None, home: Path | None = None) -> tuple[str, str]:
    env = os.environ if environ is None else environ
    url, token = env.get("CI_SCOPE_URL", ""), env.get("CI_SCOPE_CONFIG_TOKEN", "")
    if not (url and token):
        path = (home or Path.home()) / ".config/ci-scope/device.json"
        if not path.is_file():
            raise ServerUnavailable(f"this device is not set up: missing {path}")
        if path.stat().st_mode & 0o077:
            raise CliError(f"{path} must not be readable by other users (chmod 600)")
        data = json.loads(path.read_text(encoding="utf-8"))
        url, token = str(data.get("url", "")), str(data.get("token", ""))
    if not url.startswith("https://") and not url.startswith("http://localhost"):
        raise CliError("the CI Scope server URL must use https")
    return url.rstrip("/"), token


def http_fetch(url: str, token: str) -> dict:
    request = urllib.request.Request(url, headers={TOKEN_HEADER: token, "accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310 - scheme checked in device_settings
            return json.loads(response.read(2_000_000))
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise NotRegistered("this repository is not registered with CI Scope") from error
        raise ServerUnavailable(f"the server refused the request ({error.code})") from error
    except OSError as error:
        raise ServerUnavailable(f"cannot reach the CI Scope server: {error}") from error


def fetch_project(base_url: str, token: str, repository: str, fetch: Fetch) -> tuple[dict, dict[str, str]]:
    quoted = urllib.parse.quote(repository, safe="/")
    config_reply = fetch(f"{base_url}/api/ci/v2/projects/config?repository={quoted}", token)
    config = config_reply["config"]
    if hashlib.sha256(canonical_config(config).encode("utf-8")).hexdigest() != config_reply.get("digest"):
        raise CliError("the config digest does not match; refusing to use it")
    baseline_reply = fetch(f"{base_url}/api/ci/v2/projects/baseline?repository={quoted}", token)
    return config, {item["path"]: item["fingerprint"] for item in baseline_reply["baseline"]["files"]}


def observed_files(root: Path, patterns: list[str], baseline: dict[str, str]) -> dict[str, str | None]:
    listed = git(root, "ls-files", "-co", "--exclude-standard").splitlines()
    paths = set(select_protected_paths(listed, patterns)) | set(baseline)
    result: dict[str, str | None] = {}
    for path in sorted(paths):
        file = root / path
        result[path] = file.read_text(encoding="utf-8", errors="replace") if file.is_file() and not file.is_symlink() else None
    return result


def run_command(command: list[str], cwd: Path) -> tuple[int, str]:
    try:
        done = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False, timeout=1_800)
    except (OSError, subprocess.TimeoutExpired) as error:
        return 127, str(error)
    return done.returncode, (done.stdout + done.stderr)[-MAX_OUTPUT:]


def clip(text: str, limit: int = MAX_DETAIL) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def verdict_line(results: list[dict]) -> str:
    failed = [item for item in results if item["status"] == "failed"]
    ran = [item for item in results if item["status"] in {"passed", "failed"}]
    if failed:
        shown = "; ".join(f"{item['id']}: {clip(item['detail'] or 'failed')}" for item in failed[:3])
        more = f" (+{len(failed) - 3} more)" if len(failed) > 3 else ""
        return f"CI Scope: FAILED — {shown}{more}"
    if not ran:
        return "CI Scope: FAILED — no check produced a result"
    return f"CI Scope: PASSED — {len(ran)} of {len(results)} checks passed"


def run_checks(root: Path, gates: Path, tier: str, fetch: Fetch, runner: Runner, base_url: str, token: str) -> list[dict]:
    config, baseline = fetch_project(base_url, token, repository_slug(root), fetch)
    results: list[dict] = []
    violations = check_protected_files(baseline, observed_files(root, config["protectedFiles"], baseline), config["protectedFiles"])
    results.append({
        "id": "protected-files",
        "status": "failed" if violations else "passed",
        "detail": ", ".join(f"{item.kind} {item.path}" for item in violations),
    })
    base = git(root, "merge-base", "HEAD", "origin/main") or "HEAD"
    with tempfile.TemporaryDirectory(prefix="ci-scope-config-") as directory:
        for spec in build_check_specs(config, Path(directory)):
            if spec.speed not in TIERS[tier]:
                continue
            outcome, detail = 0, ""
            for command in commands_for(spec, root, gates, (base, "HEAD"), "local"):
                code, output = runner(command, root)
                if code != 0:
                    outcome, detail = code, output
                    break
            results.append({"id": spec.id, "status": "passed" if outcome == 0 else "failed", "detail": detail})
    return results


def main(argv: list[str], fetch: Fetch = lambda url, token: http_fetch(url, token), runner: Runner = run_command) -> int:
    parser = argparse.ArgumentParser(prog="ci-scope check")
    parser.add_argument("--tier", choices=sorted(TIERS), default="push")
    parser.add_argument("--root", default=".")
    parser.add_argument("--hook", action="store_true", help="Git hook mode: stay quiet for unregistered repositories and do not block when the server is down.")
    parser.add_argument("--json", action="store_true", help="Print the full result as JSON after the one-line verdict.")
    args = parser.parse_args(argv)
    root = Path(git(Path(args.root), "rev-parse", "--show-toplevel") or args.root).resolve()
    gates = Path(__file__).resolve().parents[1]
    try:
        base_url, token = device_settings()
        results = run_checks(root, gates, args.tier, fetch, runner, base_url, token)
    except NotRegistered as error:
        if args.hook:
            return 0
        print(f"CI Scope: FAILED — {error}")
        return 2
    except ServerUnavailable as error:
        if args.hook:
            print(f"CI Scope: skipped locally — {error}; the pull request check still applies", file=sys.stderr)
            return 0
        print(f"CI Scope: FAILED — {error}")
        return 2
    except (CliError, KeyError, ValueError) as error:
        print(f"CI Scope: FAILED — {error}")
        return 2
    print(verdict_line(results))
    if args.json:
        print(json.dumps({"results": results}, ensure_ascii=False))
    return 1 if any(item["status"] == "failed" for item in results) or not results else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
