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


class ServerUnavailableError(CliError):
    """The server could not be reached or answered with an error."""


@dataclass(frozen=True)
class Server:
    base_url: str
    token: str
    fetch: Fetch


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


def fetch_project(server: Server, repository: str) -> tuple[dict, dict[str, str]]:
    quoted = urllib.parse.quote(repository, safe="/")
    config_reply = server.fetch(f"{server.base_url}/api/ci/v2/projects/config?repository={quoted}", server.token)
    config = config_reply["config"]
    if hashlib.sha256(canonical_config(config).encode("utf-8")).hexdigest() != config_reply.get("digest"):
        raise CliError("the config digest does not match; refusing to use it")
    baseline_reply = server.fetch(f"{server.base_url}/api/ci/v2/projects/baseline?repository={quoted}", server.token)
    return config, {item["path"]: item["fingerprint"] for item in baseline_reply["baseline"]["files"]}
