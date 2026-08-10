import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
FETCH_COMMAND = 'git -C "$RUNNER_TEMP/ci-gates" fetch --quiet --depth 1 origin -- "$GATES_REF"'
FETCH_RE = re.compile(r"\bgit\b[^\n;&|]*\bfetch\b[^\n;&|]*")


def _strip_shell_comment(line):
    result = []
    escaped = False
    in_single_quote = False
    in_double_quote = False
    for character in line:
        if escaped:
            result.append(character)
            escaped = False
        elif character == "\\" and not in_single_quote:
            result.append(character)
            escaped = True
        elif character == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
            result.append(character)
        elif character == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            result.append(character)
        elif character == "#" and not in_single_quote and not in_double_quote:
            break
        else:
            result.append(character)
    return "".join(result).rstrip()


def _run_blocks(workflow):
    lines = workflow.splitlines()
    blocks = []
    first_step = next(index for index, line in enumerate(lines) if line.lstrip().startswith("- name:"))
    step_indent = len(lines[first_step]) - len(lines[first_step].lstrip())
    step_starts = [
        index
        for index, line in enumerate(lines)
        if len(line) - len(line.lstrip()) == step_indent and line.lstrip().startswith("- ")
    ]
    for position, start in enumerate(step_starts):
        end = step_starts[position + 1] if position + 1 < len(step_starts) else len(lines)
        block_lines = lines[start:end]
        for run_index, line in enumerate(block_lines):
            run_line = _strip_shell_comment(line).strip()
            if run_line.startswith("- run:"):
                run_line = run_line[1:].lstrip()
            if not run_line.startswith("run:"):
                continue
            run_value = run_line[len("run:") :].strip()
            if run_value and run_value[0] not in "|>":
                blocks.append(run_value)
                break
            run_indent = len(line) - len(line.lstrip())
            body = []
            for body_line in block_lines[run_index + 1 :]:
                if body_line.strip() and len(body_line) - len(body_line.lstrip()) <= run_indent:
                    break
                uncommented = _strip_shell_comment(body_line).strip()
                if uncommented:
                    body.append(uncommented)
            blocks.append("\n".join(body))
            break
    return blocks


def _fetch_invocations(workflow):
    normalized = re.sub(r"\\\s*\n", " ", "\n".join(_run_blocks(workflow)))
    return [match.group(0).strip() for match in FETCH_RE.finditer(normalized)]


def _git(directory, *args, check=True):
    return subprocess.run(
        ["git", "-C", str(directory), *args],
        check=check,
        capture_output=True,
        text=True,
    )


def _make_git_ref_fixture(root):
    remote = root / "remote.git"
    source = root / "source"
    worktree = root / "work"
    _git(root, "init", "--bare", str(remote))
    _git(root, "init", str(source))
    _git(source, "config", "user.email", "test@example.invalid")
    _git(source, "config", "user.name", "workflow-test")
    _git(source, "commit", "--allow-empty", "-m", "init")
    _git(source, "branch", "-M", "main")
    _git(source, "checkout", "-b", "feature")
    (source / "feature.txt").write_text("feature\n", encoding="utf-8")
    _git(source, "add", "feature.txt")
    _git(source, "commit", "-m", "feature")
    feature_commit = _git(source, "rev-parse", "HEAD").stdout.strip()
    main_commit = _git(source, "rev-parse", "main").stdout.strip()
    _git(source, "tag", "lightweight")
    _git(source, "tag", "--annotate", "annotated", "-m", "annotated")
    _git(source, "remote", "add", "origin", str(remote))
    _git(source, "push", "origin", "main", "feature", "--tags")
    _git(root, "clone", "--no-checkout", str(remote), str(worktree))
    return worktree, main_commit, feature_commit


def _assert_detached_fetch(testcase, worktree, ref, expected_commit):
    valid_fetch = _git(
        worktree,
        "fetch",
        "--quiet",
        "--depth",
        "1",
        "origin",
        "--",
        ref,
    )
    testcase.assertEqual(valid_fetch.returncode, 0)
    _git(worktree, "checkout", "--quiet", "--detach", "FETCH_HEAD")
    testcase.assertEqual(_git(worktree, "rev-parse", "HEAD").stdout.strip(), expected_commit)
    testcase.assertEqual(
        _git(worktree, "rev-parse", "FETCH_HEAD^{commit}").stdout.strip(),
        expected_commit,
    )
    testcase.assertEqual(
        _git(worktree, "symbolic-ref", "--quiet", "HEAD", check=False).returncode,
        1,
    )


def _assert_option_like_ref_is_inert(testcase, root, worktree):
    marker = root / "marker"
    malicious_ref = f"--upload-pack=touch {marker}"
    malicious_fetch = _git(
        worktree,
        "fetch",
        "--quiet",
        "--depth",
        "1",
        "origin",
        "--",
        malicious_ref,
        check=False,
    )
    testcase.assertNotEqual(malicious_fetch.returncode, 0)
    testcase.assertFalse(marker.exists())


class ReusableWorkflowReferenceTests(unittest.TestCase):
    def test_all_gate_workflows_default_to_latest_main_with_sha_override(self):
        workflow_paths = sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))
        gate_workflows = []
        for path in workflow_paths:
            workflow = path.read_text(encoding="utf-8")
            if "ci-gates" not in workflow:
                continue
            gate_workflows.append(path)
            with self.subTest(workflow=path.name):
                self.assertIn("gates-ref:", workflow)
                self.assertIn("default: main", workflow)
                self.assertNotIn("ref: 441c840036ae31e9ac310ff381b6322339dfff65", workflow)
                if "repository: ForkHorizon/ci-gates" in workflow:
                    self.assertIn("ref: ${{ inputs.gates-ref }}", workflow)
        self.assertGreaterEqual(len(gate_workflows), 8)

    def test_fetch_scanner_detects_inline_unnamed_run_steps(self):
        workflow = """\
steps:
  - name: anchor
    run: |
      true
  - run: | # inline mapping
      git -C "$RUNNER_TEMP/ci-gates" fetch --quiet --depth 1 origin "$GATES_REF"
"""
        self.assertEqual(
            _fetch_invocations(workflow),
            ['git -C "$RUNNER_TEMP/ci-gates" fetch --quiet --depth 1 origin "$GATES_REF"'],
        )

    def test_clone_based_gate_workflows_fetch_and_detach_the_requested_sha(self):
        for path in sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml")):
            workflow = path.read_text(encoding="utf-8")
            if "git clone" not in workflow or "inputs.gates-ref" not in workflow:
                continue
            with self.subTest(workflow=path.name):
                self.assertIn("GATES_REF: ${{ inputs.gates-ref }}", workflow)
                fetch_blocks = [block for block in _run_blocks(workflow) if "git clone" in block]
                self.assertEqual(len(fetch_blocks), 1)
                self.assertIn(FETCH_COMMAND, fetch_blocks[0])
                self.assertIn(
                    'git -C "$RUNNER_TEMP/ci-gates" checkout --quiet --detach FETCH_HEAD',
                    fetch_blocks[0],
                )
                fetch_invocations = _fetch_invocations(workflow)
                self.assertEqual(fetch_invocations, [FETCH_COMMAND])
                self.assertNotIn('--branch "${{ inputs.gates-ref }}"', workflow)

    def test_fetch_command_handles_main_and_rejects_option_like_refs(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            worktree, main_commit, feature_commit = _make_git_ref_fixture(root)

            for ref, expected_commit in (
                ("main", main_commit),
                ("feature", feature_commit),
                ("lightweight", feature_commit),
                ("annotated", feature_commit),
                (feature_commit, feature_commit),
            ):
                with self.subTest(ref=ref):
                    _assert_detached_fetch(self, worktree, ref, expected_commit)
            _assert_option_like_ref_is_inert(self, root, worktree)


if __name__ == "__main__":
    unittest.main()
