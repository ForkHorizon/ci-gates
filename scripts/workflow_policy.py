"""Dependency-free trust and routing checks for GitHub workflow text."""

from __future__ import annotations

import re
from collections.abc import Mapping


APPROVED_REUSABLE_ORIGINS = frozenset({"ForkHorizon/ci-gates"})
TRUSTED_GROUP = "ci-scope-v2-canary"
V2_LABELS = frozenset({"self-hosted", "macOS", "ARM64", "ci-scope-v2"})
# Release manifests pin immutable Git commits; keep this identical to
# release_manifest.py instead of accepting alternate-length or uppercase refs.
SHA_RE = re.compile(r"^[0-9a-f]{40}$")

_KEY_RE = re.compile(r"^\s*([A-Za-z0-9_-]+)\s*:\s*(.*?)\s*$")
_USES_RE = re.compile(r"^\s*uses\s*:\s*([^\s#]+)", re.MULTILINE)
_REUSABLE_RE = re.compile(r"^(?P<origin>[^/\s]+/[^/\s]+)/\.github/workflows/[^@\s]+@(?P<ref>[^\s#]+)$")
_EVENT_RE = re.compile(r"^\s*(?:[\"']?on[\"']?)\s*:\s*(.*)$", re.MULTILINE)


def validate_workflow_text(
    text: str,
    production: bool = True,
    manifest: Mapping[str, object] | None = None,
) -> list[str]:
    """Return policy violations found in a workflow without parsing YAML.

    ``manifest`` is optional for local structural checks.  When supplied, it is
    a release/check input and must contain a 40- or 64-character ``source_sha``
    (or the same field nested under ``check_input``).  It may also contain
    ``approved_origins``, ``trusted_groups``, and ``routing`` overrides.
    """
    if not isinstance(text, str):
        return ["workflow text must be a string"]
    if manifest is not None and not isinstance(manifest, Mapping):
        return ["manifest must be a mapping"]

    clean = _strip_comments(text)
    issues: list[str] = []
    config = _policy_config(manifest)
    issues.extend(_source_sha_issues(manifest))
    issues.extend(_routing_issues(clean, config))

    unguarded_trusted_job = any(
        _uses_trusted_group(job, config["trusted_groups"]) and not _same_repository_guard(_job_if(job))
        for job in _job_blocks(clean)
    )
    if unguarded_trusted_job and _has_event(clean, "pull_request"):
        issues.append("external fork pull_request is eligible for a trusted runner group")

    if _has_event(clean, "pull_request_target") and _checks_out_untrusted_head(clean):
        issues.append("pull_request_target checks out an untrusted pull request head")

    for origin, ref in _reusable_workflows(clean):
        if origin not in config["approved_origins"]:
            issues.append(f"reusable workflow origin is not approved: {origin}")
        if production and _floating_main(ref):
            issues.append(f"production reusable workflow uses floating @main: {origin}")

    return _unique(issues)


def _policy_config(manifest: Mapping[str, object] | None) -> dict[str, object]:
    config: dict[str, object] = {
        "approved_origins": APPROVED_REUSABLE_ORIGINS,
        "trusted_groups": frozenset({TRUSTED_GROUP}),
        "routing": {"generation": "v2", "group": TRUSTED_GROUP, "labels": V2_LABELS},
    }
    if manifest is None:
        return config
    approved = manifest.get("approved_origins")
    if isinstance(approved, (list, tuple, set, frozenset)):
        config["approved_origins"] = frozenset(str(value) for value in approved)
    groups = manifest.get("trusted_groups")
    if isinstance(groups, (list, tuple, set, frozenset)):
        config["trusted_groups"] = frozenset(str(value) for value in groups)
    routing = manifest.get("routing")
    if isinstance(routing, Mapping):
        expected = dict(config["routing"])
        expected.update({key: routing[key] for key in ("generation", "group", "labels") if key in routing})
        if isinstance(expected.get("labels"), (list, tuple, set, frozenset)):
            expected["labels"] = frozenset(str(value) for value in expected["labels"])
        config["routing"] = expected
    return config


def _source_sha_issues(manifest: Mapping[str, object] | None) -> list[str]:
    if manifest is None:
        return []
    check_input = manifest.get("check_input")
    source_sha = manifest.get("source_sha")
    if source_sha is None and isinstance(check_input, Mapping):
        source_sha = check_input.get("source_sha")
    if not isinstance(source_sha, str) or not SHA_RE.fullmatch(source_sha):
        return ["source SHA is missing or invalid in manifest/check input"]
    return []


def _routing_issues(text: str, config: Mapping[str, object]) -> list[str]:
    generation_values = _values(text, "routing-generation") + _values(text, "routing_generation")
    generation_values += _values(text, "generation")
    generations = {value.strip(" '\"") for value in generation_values if value.strip(" '\"")}
    v2_named = bool(_values(text, "runner-group") or _values(text, "runner-labels"))
    v2_runs_on = bool(re.search(r"(?ms)^\s*runs-on\s*:\s*\n\s+group\s*:\s*[^\n]+\n\s+labels\s*:", text))
    v2_fields = v2_named or v2_runs_on
    v1_runs_on = bool(re.search(r"(?m)^[ \t]*runs-on[ \t]*:[ \t]+\S", text))
    issues: list[str] = []
    if v1_runs_on and (v2_fields or "v2" in generations):
        issues.append("v1 and v2 routing fields cannot be used together")
    if not generations:
        if v2_fields:
            issues.append("routing generation is missing or unknown")
        return issues
    if len(generations) != 1 or next(iter(generations)) not in {"v1", "v2"}:
        issues.append("routing generation is missing or unknown")
        return issues
    generation = next(iter(generations))
    if generation == "v1":
        if v2_fields:
            issues.append("v1 and v2 routing fields cannot be used together")
        return _unique(issues)
    if generation != str(config["routing"]["generation"]):
        issues.append("routing generation does not match the approved routing")
        return issues

    expected_group = str(config["routing"]["group"])
    groups = set(_values(text, "runner-group")) | set(_values(text, "group"))
    if expected_group not in groups:
        issues.append("runs-on group does not match routing generation")

    labels = set(_labels(text))
    expected_labels = set(config["routing"]["labels"])
    if labels != expected_labels:
        issues.append("runs-on labels do not match routing generation")
    return issues


def _values(text: str, key: str) -> list[str]:
    values = []
    for line in text.splitlines():
        match = _KEY_RE.match(line)
        if match and match.group(1) == key:
            values.append(match.group(2).strip().strip(" '\""))
    return values


def _labels(text: str) -> list[str]:
    labels: list[str] = []
    for key in ("runner-labels", "runner_labels", "labels"):
        for value in _values(text, key):
            labels.extend(re.findall(r"[A-Za-z0-9_.-]+", value))
    return labels


def _has_event(text: str, event: str) -> bool:
    for value in _EVENT_RE.findall(text):
        if re.search(
            r"(?:^|[\[,\s])['\"]?" + re.escape(event) + r"['\"]?(?:$|[\]},\s:])",
            value,
        ):
            return True
    return bool(re.search(rf"(?m)^\s+{re.escape(event)}\s*:", text))


def _same_repository_guard(text: str) -> bool:
    return bool(
        re.search(
            r"pull_request\.head\.repo\.full_name\s*==\s*(?:github\.repository|github\.event\.repository\.full_name|pull_request\.base\.repo\.full_name)",
            text,
        )
    )


def _uses_trusted_group(job: str, trusted_groups: object) -> bool:
    groups = _values(job, "group") + _values(job, "runner-group")
    return any(group in trusted_groups for group in groups)


def _job_blocks(text: str) -> list[str]:
    lines = text.splitlines()
    for jobs_index, line in enumerate(lines):
        match = _KEY_RE.match(line)
        if match and match.group(1) == "jobs" and not match.group(2):
            break
    else:
        return []

    jobs_indent = len(lines[jobs_index]) - len(lines[jobs_index].lstrip())
    job_indent = None
    starts: list[int] = []
    end = len(lines)
    for index in range(jobs_index + 1, len(lines)):
        line = lines[index]
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= jobs_indent:
            end = index
            break
        if job_indent is None:
            job_indent = indent
        if indent == job_indent and _KEY_RE.match(line):
            starts.append(index)
    return [
        "\n".join(lines[start : starts[position + 1] if position + 1 < len(starts) else end])
        for position, start in enumerate(starts)
    ]


def _job_if(job: str) -> str:
    lines = job.splitlines()
    if not lines:
        return ""
    body_indents = [len(line) - len(line.lstrip()) for line in lines[1:] if line.strip()]
    if not body_indents:
        return ""
    field_indent = min(body_indents)
    for index, line in enumerate(lines[1:], start=1):
        match = _KEY_RE.match(line)
        if match and len(line) - len(line.lstrip()) == field_indent and match.group(1) == "if":
            parts = [match.group(2)]
            for continuation in lines[index + 1 :]:
                if continuation.strip() and len(continuation) - len(continuation.lstrip()) <= field_indent:
                    break
                parts.append(continuation.strip())
            return " ".join(parts)
    return ""


def _checks_out_untrusted_head(text: str) -> bool:
    return bool(
        re.search(
            r"(?:actions/checkout|git\s+(?:checkout|clone)|(?:ref|repository)\s*:)[^\n]*(?:pull_request\.head\.(?:sha|ref|repo)|github\.head_(?:sha|ref)|GITHUB_HEAD_REF)",
            text,
            re.IGNORECASE,
        )
    )


def _reusable_workflows(text: str) -> list[tuple[str, str]]:
    workflows = []
    for value in _USES_RE.findall(text):
        match = _REUSABLE_RE.match(value.strip(" '\""))
        if match:
            workflows.append((match.group("origin"), match.group("ref")))
    return workflows


def _floating_main(ref: str) -> bool:
    return ref.lower() in {"main", "refs/heads/main"}


def _strip_comments(text: str) -> str:
    lines = []
    for original_line in text.splitlines():
        line = original_line
        quote = ""
        for index, character in enumerate(line):
            if character in {"'", '"'}:
                if quote == character:
                    quote = ""
                elif not quote:
                    quote = character
            elif character == "#" and not quote and (index == 0 or line[index - 1].isspace()):
                line = line[:index]
                break
        lines.append(line.rstrip())
    return "\n".join(lines)


def _unique(issues: list[str]) -> list[str]:
    return list(dict.fromkeys(issues))


__all__ = ["validate_workflow_text"]
