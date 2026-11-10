"""Edits to existing tests pass only with the owner's approval of exactly that content; the gate asks the owner."""

import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.protected_files import fingerprint_file
from scripts.test_approvals import load_approvals
from scripts.test_approvals import ApprovalState
from scripts.test_protection import scan_with_approvals

OLD, NEW = "fn old() {}\nfn keep() {}\n", "fn new_behavior() {}\nfn keep() {}\n"
TEST = "crates/x/tests/daemon.rs"


def git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


class Repo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        git(self.root, "init", "-q")
        git(self.root, "config", "user.email", "a@b.c")
        git(self.root, "config", "user.name", "t")
        (self.root / TEST).parent.mkdir(parents=True)
        (self.root / TEST).write_text(OLD, encoding="utf-8")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "base")
        (self.root / TEST).write_text(NEW, encoding="utf-8")


class ScanApprovalTests(Repo):
    def findings(self, approved, requests=None):
        state = ApprovalState(approved, requests if requests is not None else [])
        return [f.rule_id for f in scan_with_approvals(self.root, ("worktree", "HEAD~1", "HEAD"), None, state)]

    def test_an_edit_without_approval_is_flagged_and_listed_for_the_owner(self):
        requests = []
        self.assertEqual(self.findings({}, requests), ["test-modified"])
        self.assertEqual(
            requests,
            [
                {
                    "path": TEST,
                    "kind": "modified",
                    "fingerprint": fingerprint_file(TEST, NEW),
                    "previous": fingerprint_file(TEST, OLD),
                }
            ],
        )

    def test_the_approved_content_passes(self):
        requests = []
        self.assertEqual(self.findings({TEST: {fingerprint_file(TEST, NEW)}}, requests), [])
        self.assertEqual(requests, [])

    def test_any_other_content_is_still_flagged(self):
        (self.root / TEST).write_text(NEW + "// more\n", encoding="utf-8")
        self.assertEqual(self.findings({TEST: {fingerprint_file(TEST, NEW)}}), ["test-modified"])

    def test_an_approved_deletion_passes_and_a_missing_one_does_not(self):
        (self.root / TEST).unlink()
        self.assertEqual(self.findings({}), ["test-deleted"])
        self.assertEqual(self.findings({TEST: {None}}), [])

    def test_runner_config_can_never_be_approved(self):
        (self.root / "conftest.py").write_text("x = 1\n", encoding="utf-8")
        git(self.root, "add", "conftest.py")
        git(self.root, "commit", "-q", "-m", "runner")
        (self.root / "conftest.py").write_text("x = 2\n", encoding="utf-8")
        approved = {"conftest.py": {fingerprint_file("conftest.py", "x = 2\n")}, TEST: {fingerprint_file(TEST, NEW)}}
        self.assertEqual(self.findings(approved), ["runner-config-changed"])

    def test_runner_config_is_cleared_only_by_the_protected_file_approval_of_that_content(self):
        (self.root / "conftest.py").write_text("x = 1\n", encoding="utf-8")
        git(self.root, "add", "conftest.py")
        git(self.root, "commit", "-q", "-m", "runner")
        (self.root / "conftest.py").write_text("x = 2\n", encoding="utf-8")
        revisions = ("worktree", "HEAD~1", "HEAD")
        approved = {TEST: {fingerprint_file(TEST, NEW)}}

        def rules(config):
            return [
                f.rule_id for f in scan_with_approvals(self.root, revisions, None, ApprovalState(approved, [], config))
            ]

        self.assertEqual(rules({"conftest.py": {fingerprint_file("conftest.py", "x = 2\n")}}), [])
        self.assertEqual(
            rules({"conftest.py": {fingerprint_file("conftest.py", "x = 3\n")}}), ["runner-config-changed"]
        )

    def test_a_missing_approvals_file_means_none(self):
        self.assertEqual(load_approvals(None), {})
        self.assertEqual(load_approvals(self.root / "absent.json"), {})


if __name__ == "__main__":
    unittest.main()
