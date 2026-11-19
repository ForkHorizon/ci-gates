"""An old GitHub Actions gate left in a project fails the CI Scope check until it is removed."""

import hashlib
import tempfile
import unittest
from pathlib import Path

from scripts import ci_scope_run as run
from scripts import ci_scope_server as srv
from tests.test_ci_scope_cli import CONFIG, git

REUSABLE = "jobs:\n  gate:\n    uses: ForkHorizon/ci-gates/.github/workflows/unity-quality.yml@main\n"
OLD_CHECKS = "name: CI Scope\njobs:\n  checks:\n    runs-on: [self-hosted, macOS, ARM64, ci-scope-unified]\n"
OWN_CI = "name: ci\njobs:\n  test:\n    runs-on: [self-hosted, macOS, ARM64, ci-scope]\n"


class LegacyGateTests(unittest.TestCase):
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
        self.workflows = self.root / ".github/workflows"
        self.workflows.mkdir(parents=True)

    def results(self):
        config = {
            **CONFIG,
            "protectedFiles": [],
            "lanes": {**CONFIG["lanes"], "code-rules": {"enabled": False}},
        }
        config["lanes"]["language"] = {"enabled": False, "adapters": []}

        def fetch(url, _token):
            if "/config?" in url:
                return {
                    "config": config,
                    "digest": hashlib.sha256(srv.canonical_config(config).encode()).hexdigest(),
                }
            return {"baseline": {"files": []}}

        request = run.RunRequest(self.root, Path(run.__file__).resolve().parents[1])
        return run.run_checks(
            request,
            srv.Server("https://ci.example", "secret", fetch),
            lambda c, r: (0, ""),
        )

    def test_old_gate_workflows_fail_and_project_ci_does_not(self):
        (self.workflows / "unity-quality-gate.yml").write_text(REUSABLE, encoding="utf-8")
        (self.workflows / "ci-scope-checks.yaml").write_text(OLD_CHECKS, encoding="utf-8")
        (self.workflows / "ci.yml").write_text(OWN_CI, encoding="utf-8")
        results = self.results()
        legacy = next(item for item in results if item["id"] == "legacy-gates")
        self.assertEqual(legacy["status"], "failed")
        self.assertIn(
            ".github/workflows/ci-scope-checks.yaml, .github/workflows/unity-quality-gate.yml",
            legacy["detail"],
        )
        self.assertNotIn("ci.yml", legacy["detail"].replace("ci-scope-checks", ""))
        self.assertIn("legacy-gates: remove", run.verdict_line(results))

    def test_clean_project_has_no_legacy_item(self):
        (self.workflows / "ci.yml").write_text(OWN_CI, encoding="utf-8")
        self.assertNotIn("legacy-gates", [item["id"] for item in self.results()])


if __name__ == "__main__":
    unittest.main()
