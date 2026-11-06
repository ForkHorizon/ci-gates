"""Content the owner approved for a pull request passes the protected-files check, and nothing else does."""

import hashlib
import tempfile
import unittest
from pathlib import Path

from scripts import ci_scope_run as run
from scripts import ci_scope_server as srv
from scripts.protected_files import fingerprint_file
from tests.test_ci_scope_cli import CARGO, CONFIG, git


class ApprovedContentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        git(self.root, "init", "-q")
        git(
            self.root,
            "remote",
            "add",
            "origin",
            "git@github.com:ForkHorizon/Example.git",
        )
        self.edited = CARGO.replace("forbid", "allow")
        (self.root / "Cargo.toml").write_text(self.edited, encoding="utf-8")

    def protected_files_result(self, approved):
        def fake(url, token):
            if "/config?" in url:
                return {
                    "config": CONFIG,
                    "digest": hashlib.sha256(srv.canonical_config(CONFIG).encode()).hexdigest(),
                }
            files = [
                {
                    "path": "Cargo.toml",
                    "fingerprint": fingerprint_file("Cargo.toml", CARGO),
                }
            ]
            return {"baseline": {"files": files}, "approved": approved}

        request = run.RunRequest(self.root, Path(run.__file__).resolve().parents[1], "commit")
        return run.run_checks(
            request,
            srv.Server("https://ci.example", "secret", fake),
            lambda command, cwd: (0, ""),
        )[0]

    def test_an_unapproved_edit_is_caught(self):
        result = self.protected_files_result([])
        self.assertEqual((result["status"], result["detail"]), ("failed", "modified Cargo.toml"))

    def test_the_approved_content_passes(self):
        approved = [
            {
                "path": "Cargo.toml",
                "fingerprint": fingerprint_file("Cargo.toml", self.edited),
            }
        ]
        self.assertEqual(self.protected_files_result(approved)["status"], "passed")

    def test_other_content_than_the_approved_one_is_caught(self):
        approved = [
            {
                "path": "Cargo.toml",
                "fingerprint": fingerprint_file("Cargo.toml", CARGO.replace("forbid", "warn")),
            }
        ]
        self.assertEqual(self.protected_files_result(approved)["status"], "failed")


if __name__ == "__main__":
    unittest.main()
