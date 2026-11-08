"""Edits to existing tests pass only with the owner's approval of exactly that content; the gate asks the owner."""

import copy
import hashlib
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import ci_scope_run as run
from scripts import ci_scope_server as srv
from scripts.protected_files import fingerprint_file
from scripts.test_approvals import load_approvals
from scripts.test_protection import scan
from tests.test_ci_scope_cli import CONFIG

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
        return [f.rule_id for f in scan(self.root, "worktree", "HEAD~1", "HEAD", None, approved, requests)]

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

    def test_a_missing_approvals_file_means_none(self):
        self.assertEqual(load_approvals(None), {})
        self.assertEqual(load_approvals(self.root / "absent.json"), {})


class GateRunTests(Repo):
    """The whole gate: approvals come from the server, a failed run opens a request for the owner."""

    def setUp(self):
        super().setUp()
        git(self.root, "remote", "add", "origin", "git@github.com:ForkHorizon/Example.git")
        self.config = copy.deepcopy(CONFIG)
        self.config["lanes"]["code-rules"]["enabled"] = False
        self.config["lanes"]["language"]["enabled"] = False
        self.config["lanes"]["agent-guard"]["enabled"] = True
        self.posted = []

    def server(self, approved):
        def fetch(url, token):
            if "/config?" in url:
                return {
                    "config": self.config,
                    "digest": hashlib.sha256(srv.canonical_config(self.config).encode()).hexdigest(),
                }
            if "/test-approved" in url:
                return {"approved": approved}
            return {"baseline": {"files": []}, "approved": []}

        def post(url, token, body):
            self.posted.append((url, body))
            return {"id": 12, "status": "pending"}

        return srv.Server("https://ci.example", "secret", fetch, post)

    def result(self, approved, event="local"):
        gates = Path(run.__file__).resolve().parents[1]
        request = run.RunRequest(self.root, gates, "commit", event, ("HEAD~1", "HEAD") if event != "local" else None)

        def runner(command, cwd):
            real = [c for c in command if c.endswith("test_protection.py")]
            if not real:
                return 0, ""
            done = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)
            return done.returncode, done.stdout + done.stderr

        results = run.run_checks(request, self.server(approved), runner)
        return next(item for item in results if item["id"] == "test-protection")

    def test_an_approved_edit_passes_the_gate(self):
        approved = [{"path": TEST, "fingerprint": fingerprint_file(TEST, NEW)}]
        self.assertEqual(self.result(approved)["status"], "passed")
        self.assertEqual(self.posted, [])

    def test_a_failed_gate_without_a_reason_says_how_to_ask_and_opens_nothing(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(run.REASON_ENV, None)
            result = self.result([])
        self.assertEqual(result["status"], "failed")
        self.assertIn(run.REASON_ENV, result["detail"])
        self.assertEqual(self.posted, [])

    def test_a_failed_gate_with_a_reason_opens_one_request_with_the_exact_content(self):
        with mock.patch.dict(os.environ, {run.REASON_ENV: "T7.1 removes the old enrollment"}):
            result = self.result([])
        self.assertIn("request #12", result["detail"])
        url, body = self.posted[0]
        self.assertTrue(url.endswith("/api/ci/v2/changes/test-request"))
        self.assertEqual(body["repository"], "ForkHorizon/Example")
        self.assertEqual(body["reason"], "T7.1 removes the old enrollment")
        self.assertEqual(body["items"][0]["fingerprint"], fingerprint_file(TEST, NEW))

    def test_a_pull_request_run_never_opens_a_request(self):
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "edit")
        with mock.patch.dict(os.environ, {run.REASON_ENV: "why"}):
            result = self.result([], event="pull_request")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(self.posted, [])


if __name__ == "__main__":
    unittest.main()
