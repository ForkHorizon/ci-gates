"""The whole gate: approvals come from the server, a failed local run opens a request for the owner."""

import copy
import hashlib
import os
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from scripts import ci_scope_run as run
from scripts import ci_scope_server as srv
from scripts.protected_files import fingerprint_file
from tests.test_ci_scope_cli import CONFIG
from tests.test_test_edit_approval import NEW, TEST, Repo, git


class GateRunTests(Repo):
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
