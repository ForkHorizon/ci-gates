"""Run a project's server-held checks on a working tree or a pull request checkout."""

from __future__ import annotations

import re
import resource
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

try:
    from ci_scope_activity import CURRENT, MarkerTail, emit
    from ci_scope_adapters import commands_for
    from ci_scope_errors import NotRegisteredError
    from ci_scope_server import Server, fetch_project
    from protected_files import check_protected_files, select_protected_paths
    from server_config import build_check_specs
except ModuleNotFoundError:
    from .ci_scope_activity import CURRENT, MarkerTail, emit
    from .ci_scope_adapters import commands_for
    from .ci_scope_errors import NotRegisteredError
    from .ci_scope_server import Server, fetch_project
    from .protected_files import check_protected_files, select_protected_paths
    from .server_config import build_check_specs

TIERS = {"edit": {"fast"}, "commit": {"fast"}, "push": {"fast", "full"}}
MAX_DETAIL = 160
MAX_OUTPUT = 4_000
Runner = Callable[[list[str], Path], tuple[int, str]]


@dataclass(frozen=True)
class RunRequest:
    root: Path
    gates: Path
    tier: str = "push"
    event: str = "local"  # "local" = working tree, "pull_request" = clean checkout of `revisions`
    revisions: tuple[str, str] | None = None  # (base, head) commits
    repository: str | None = None  # owner/name, defaults to the origin remote
    config_version: int | None = None  # rerun with a past version of the server config


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else ""


def repository_slug(root: Path) -> str:
    match = re.search(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?$", git(root, "remote", "get-url", "origin"))
    if not match:
        raise NotRegisteredError("cannot tell the GitHub repository from the origin remote")
    return f"{match.group(1)}/{match.group(2)}"


def observed_files(root: Path, patterns: list[str], baseline: dict[str, str]) -> dict[str, str | None]:
    listed = git(root, "ls-files", "-co", "--exclude-standard").splitlines()
    paths = set(select_protected_paths(listed, patterns)) | set(baseline)
    result: dict[str, str | None] = {}
    for path in sorted(paths):
        file = root / path
        result[path] = (
            file.read_text(encoding="utf-8", errors="replace") if file.is_file() and not file.is_symlink() else None
        )
    return result


MAX_CAPTURE_BYTES = 64 * 1024 * 1024


def _limit_file_size() -> None:
    """Runs in the child before exec: a command cannot write more than the capture limit to its output file."""
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_CAPTURE_BYTES, MAX_CAPTURE_BYTES))


def run_command(command: list[str], cwd: Path) -> tuple[int, str]:
    # Output goes to a size-limited temporary file, so a noisy or hostile command cannot fill this process's memory.
    with tempfile.TemporaryFile() as sink, MarkerTail(sink.fileno()):
        try:
            done = subprocess.run(
                command,
                cwd=cwd,
                stdout=sink,
                stderr=subprocess.STDOUT,
                check=False,
                timeout=1_800,
                preexec_fn=_limit_file_size,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return 127, str(error)
        size = sink.seek(0, 2)
        sink.seek(max(0, size - MAX_OUTPUT * 4))
        return done.returncode, sink.read().decode("utf-8", errors="replace")[-MAX_OUTPUT:]


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


def run_checks(request: RunRequest, server: Server, runner: Runner = run_command) -> list[dict]:
    return run_checks_versioned(request, server, runner)[0]


def run_checks_versioned(request: RunRequest, server: Server, runner: Runner = run_command) -> tuple[list[dict], int]:
    """The results and the version of the server config they were produced with."""
    root = request.root
    config, baseline = fetch_project(server, request.repository or repository_slug(root), request.config_version)
    patterns = config["protectedFiles"]
    violations = check_protected_files(baseline, observed_files(root, patterns, baseline), patterns)
    results: list[dict] = [
        {
            "id": "protected-files",
            "status": "failed" if violations else "passed",
            "detail": ", ".join(f"{item.kind} {item.path}" for item in violations),
        }
    ]
    base, head = request.revisions or (git(root, "merge-base", "HEAD", "origin/main") or "HEAD", "HEAD")
    with tempfile.TemporaryDirectory(prefix="ci-scope-config-") as directory:
        specs = [spec for spec in build_check_specs(config, Path(directory)) if spec.speed in TIERS[request.tier]]
        emit({"plan": ["protected-files", *(spec.id for spec in specs)]})
        emit({"check": "protected-files", "state": results[0]["status"]})
        for spec in specs:
            CURRENT["check"] = spec.id
            emit({"check": spec.id, "state": "running"})
            outcome, detail = 0, ""
            for command in commands_for(spec, root, request.gates, (base, head), request.event):
                code, output = runner(command, root)
                if code != 0:
                    outcome, detail = code, output
                    break
            results.append({"id": spec.id, "status": "passed" if outcome == 0 else "failed", "detail": detail})
            emit({"check": spec.id, "state": results[-1]["status"]})
    return results, int(config["version"])
