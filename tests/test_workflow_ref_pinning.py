import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
FETCH_COMMAND = 'git -C "$RUNNER_TEMP/ci-gates" fetch --quiet --depth 1 origin -- "$GATES_REF"'


def _run_blocks(workflow):
    lines = workflow.splitlines()
    blocks = []
    step_starts = [index for index, line in enumerate(lines) if line.lstrip().startswith("- name:")]
    for position, start in enumerate(step_starts):
        step_indent = len(lines[start]) - len(lines[start].lstrip())
        end = step_starts[position + 1] if position + 1 < len(step_starts) else len(lines)
        next_start = next(
            (
                candidate
                for candidate in step_starts[position + 1 :]
                if len(lines[candidate]) - len(lines[candidate].lstrip()) == step_indent
            ),
            end,
        )
        block_lines = lines[start:next_start]
        for run_index, line in enumerate(block_lines):
            if line.strip() not in {"run: |", "run: |-", "run: >", "run: >-"}:
                continue
            run_indent = len(line) - len(line.lstrip())
            body = []
            for body_line in block_lines[run_index + 1 :]:
                if body_line.strip() and len(body_line) - len(body_line.lstrip()) <= run_indent:
                    break
                if body_line.strip() and not body_line.lstrip().startswith("#"):
                    body.append(body_line.strip())
            blocks.append("\n".join(body))
            break
    return blocks


def _git(directory, *args, check=True):
    return subprocess.run(
        ["git", "-C", str(directory), *args],
        check=check,
        capture_output=True,
        text=True,
    )


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
                self.assertNotIn('--branch "${{ inputs.gates-ref }}"', workflow)

    def test_fetch_command_handles_main_and_rejects_option_like_refs(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            remote = root / "remote.git"
            source = root / "source"
            worktree = root / "work"
            _git(root, "init", "--bare", str(remote))
            _git(root, "init", str(source))
            _git(source, "config", "user.email", "test@example.invalid")
            _git(source, "config", "user.name", "workflow-test")
            _git(source, "commit", "--allow-empty", "-m", "init")
            _git(source, "branch", "-M", "main")
            _git(source, "remote", "add", "origin", str(remote))
            _git(source, "push", "origin", "main")
            _git(root, "clone", "--no-checkout", str(remote), str(worktree))

            valid_fetch = _git(
                worktree,
                "fetch",
                "--quiet",
                "--depth",
                "1",
                "origin",
                "--",
                "main",
            )
            self.assertEqual(valid_fetch.returncode, 0)
            _git(worktree, "checkout", "--quiet", "--detach", "FETCH_HEAD")
            self.assertEqual(_git(worktree, "symbolic-ref", "--quiet", "HEAD", check=False).returncode, 1)

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
            self.assertNotEqual(malicious_fetch.returncode, 0)
            self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
