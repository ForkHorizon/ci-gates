#!/usr/bin/env python3
"""`ci-scope check`: run the project's server-held checks locally or on a pull request checkout.

The server owns the config, so the repository under test cannot weaken it. This tool only reads.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from ci_scope_errors import CliError, NotRegisteredError
    from ci_scope_run import RunRequest, TIERS, git, repository_slug, run_checks_versioned, run_command, verdict_line
    from ci_scope_server import (
        Fetch,
        Server,
        ServerUnavailableError,
        canonical_config,
        device_settings,
        fetch_request_status,
        http_fetch,
    )
except ModuleNotFoundError:
    from .ci_scope_errors import CliError, NotRegisteredError
    from .ci_scope_run import RunRequest, TIERS, git, repository_slug, run_checks_versioned, run_command, verdict_line
    from .ci_scope_server import (
        Fetch,
        Server,
        ServerUnavailableError,
        canonical_config,
        device_settings,
        fetch_request_status,
        http_fetch,
    )

__all__ = [
    "CliError",
    "NotRegisteredError",
    "ServerUnavailableError",
    "canonical_config",
    "device_settings",
    "main",
    "verdict_line",
]


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="ci-scope check")
    parser.add_argument("--tier", choices=sorted(TIERS), default="push")
    parser.add_argument("--root", default=".")
    parser.add_argument("--event", choices=("local", "pull_request"), default="local")
    parser.add_argument("--base", help="Base commit; required with --event pull_request.")
    parser.add_argument("--head", help="Head commit; required with --event pull_request.")
    parser.add_argument("--repository", help="owner/name; defaults to the origin remote.")
    parser.add_argument(
        "--config-version", type=int, help="Use this past version of the server config (to repeat an earlier run)."
    )
    parser.add_argument(
        "--hook",
        action="store_true",
        help="Git hook mode: stay quiet for unregistered repositories and do not block when the server is down.",
    )
    parser.add_argument(
        "--requests",
        action="store_true",
        help="Print the status of the owner requests (protected files, test edits) of the repository and exit.",
    )
    parser.add_argument("--json", action="store_true", help="Print the full result as JSON after the one-line verdict.")
    return parser.parse_args(argv)


def build_request(args: argparse.Namespace) -> RunRequest:
    root = Path(git(Path(args.root), "rev-parse", "--show-toplevel") or args.root).resolve()
    revisions = None
    if args.event == "pull_request":
        if not (args.base and args.head):
            raise CliError("--event pull_request needs --base and --head")
        revisions = (args.base, args.head)
    return RunRequest(
        root,
        Path(__file__).resolve().parents[1],
        args.tier,
        args.event,
        revisions,
        args.repository,
        args.config_version,
    )


def print_requests(args: argparse.Namespace, server: Server) -> int:
    """One line per request: no browser, app or Touch ID is needed to see whether the owner has decided."""
    root = Path(git(Path(args.root), "rev-parse", "--show-toplevel") or args.root).resolve()
    found = fetch_request_status(server, args.repository or repository_slug(root), args.head or "")
    for item in found:
        pull = f"PR #{item['pullRequest']}" if item["pullRequest"] else "no PR"
        print(f"#{item['id']} {item['status']} {item['kind']} {pull} {item['headSha'][:8]}: {', '.join(item['paths'])}")
    if not found:
        print("No owner requests for this repository.")
    return 0


def main(argv: list[str], fetch: Fetch = http_fetch, runner=run_command) -> int:
    args = parse_args(argv)
    try:
        url, token = device_settings()
        if args.requests:
            return print_requests(args, Server(url, token, fetch))
        results, config_version = run_checks_versioned(build_request(args), Server(url, token, fetch), runner)
    except (NotRegisteredError, ServerUnavailableError) as error:
        if args.hook:
            if isinstance(error, ServerUnavailableError):
                print(f"CI Scope: skipped locally — {error}; the pull request check still applies", file=sys.stderr)
            return 0
        print(f"CI Scope: FAILED — {error}")
        return 2
    except (CliError, KeyError, ValueError) as error:
        print(f"CI Scope: FAILED — {error}")
        return 2
    print(verdict_line(results))
    if args.json:
        print(json.dumps({"results": results, "configVersion": config_version}, ensure_ascii=False))
    # A hook must not stop the commit behind the PR where the owner approves protected files; the server blocks there.
    blocking = [
        item for item in results if item["status"] == "failed" and not (args.hook and item["id"] == "protected-files")
    ]
    return 1 if blocking or not results else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
