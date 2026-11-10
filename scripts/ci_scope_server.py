"""Reading the project config and protected-file baseline from the CI Scope server (read only)."""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

try:
    from ci_scope_errors import CliError, NotRegisteredError
except ModuleNotFoundError:
    from .ci_scope_errors import CliError, NotRegisteredError

TOKEN_HEADER = "x-ci-scope-config-token"
Fetch = Callable[[str, str], dict]
Post = Callable[[str, str, dict], dict]


class ServerUnavailableError(CliError):
    """The server could not be reached or answered with an error."""


def http_post(url: str, token: str, body: dict) -> dict:
    payload = json.dumps(body).encode("utf-8")
    headers = {TOKEN_HEADER: token, "accept": "application/json", "content-type": "application/json"}
    request = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read(2_000_000))
    except urllib.error.HTTPError as error:
        raise ServerUnavailableError(f"the server refused the request ({error.code})") from error
    except OSError as error:
        raise ServerUnavailableError(f"cannot reach the CI Scope server: {error}") from error


@dataclass(frozen=True)
class Server:
    base_url: str
    token: str
    fetch: Fetch
    post: Post = http_post


def canonical_config(config: dict) -> str:
    """Same text as the server's canonicalConfig: sorted keys, compact, trailing newline."""
    return json.dumps(config, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"


def device_settings(environ: dict[str, str] | None = None, home: Path | None = None) -> tuple[str, str]:
    env = os.environ if environ is None else environ
    url, token = env.get("CI_SCOPE_URL", ""), env.get("CI_SCOPE_CONFIG_TOKEN", "")
    if not (url and token):
        path = (home or Path.home()) / ".config/ci-scope/device.json"
        if not path.is_file():
            raise ServerUnavailableError(f"this device is not set up: missing {path}")
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
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read(2_000_000))
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise NotRegisteredError("this repository is not registered with CI Scope") from error
        raise ServerUnavailableError(f"the server refused the request ({error.code})") from error
    except OSError as error:
        raise ServerUnavailableError(f"cannot reach the CI Scope server: {error}") from error


def fetch_project(server: Server, repository: str, version: int | None = None) -> tuple[dict, dict[str, str]]:
    """The config (a pinned past version when `version` is given) and the protected-file baseline."""
    config, baseline, _approved = fetch_project_with_approvals(server, repository, version)
    return config, baseline


def fetch_project_with_approvals(
    server: Server, repository: str, version: int | None = None
) -> tuple[dict, dict[str, str], dict[str, set[str | None]]]:
    """Like `fetch_project`, plus the content the owner approved for pull requests that are not merged yet."""
    quoted = urllib.parse.quote(repository, safe="/")
    pinned = f"&version={version}" if version else ""
    config_reply = server.fetch(
        f"{server.base_url}/api/ci/v2/projects/config?repository={quoted}{pinned}", server.token
    )
    config = config_reply["config"]
    if hashlib.sha256(canonical_config(config).encode("utf-8")).hexdigest() != config_reply.get("digest"):
        raise CliError("the config digest does not match; refusing to use it")
    baseline_reply = server.fetch(f"{server.base_url}/api/ci/v2/projects/baseline?repository={quoted}", server.token)
    baseline = {item["path"]: item["fingerprint"] for item in baseline_reply["baseline"]["files"]}
    approved: dict[str, set[str | None]] = {}
    for item in baseline_reply.get("approved", []):
        approved.setdefault(item["path"], set()).add(item["fingerprint"])
    return config, baseline, approved


def fetch_approved_tests(server: Server, repository: str) -> list[dict]:
    """Edits to existing tests the owner approved (`path`, `fingerprint`); none when the server cannot say."""
    quoted = urllib.parse.quote(repository, safe="/")
    try:
        reply = server.fetch(f"{server.base_url}/api/ci/v2/changes/test-approved?repository={quoted}", server.token)
        return [{"path": item["path"], "fingerprint": item["fingerprint"]} for item in reply["approved"]]
    except (CliError, KeyError, TypeError):
        return []


def fetch_request_status(server: Server, repository: str, head: str = "") -> list[dict]:
    """What happened to the owner requests of a repository (newest first); the read token cannot decide any."""
    query = urllib.parse.urlencode({"repository": repository, **({"head": head} if head else {})}, safe="/")
    return list(server.fetch(f"{server.base_url}/api/ci/v2/changes/status?{query}", server.token)["requests"])


def open_test_request(server: Server, repository: str, items: list[dict], reason: str) -> int:
    """Ask the owner to approve edits to existing tests; returns the request id."""
    reply = server.post(
        f"{server.base_url}/api/ci/v2/changes/test-request",
        server.token,
        {"repository": repository, "items": items, "reason": reason},
    )
    return int(reply["id"])
