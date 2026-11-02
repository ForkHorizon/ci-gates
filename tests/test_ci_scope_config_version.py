import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import ci_scope_cli as cli
from scripts import ci_scope_run as run
from scripts import ci_scope_server as srv
from scripts.protected_files import fingerprint_file

CARGO = '[workspace.lints.rust]\nunsafe_code = "forbid"\n'


def config(version):
    return {
        "schema": 1,
        "repository": "ForkHorizon/Example",
        "version": version,
        "observeOnly": False,
        "lanes": {
            "code-rules": {
                "enabled": True,
                "params": {
                    "maxFileLines": 600,
                    "maxFunctionLines": 80,
                    "maxNestingDepth": 4,
                    "maxParameters": 5,
                    "ignore": [],
                    "forbidSuppressions": True,
                },
            },
            "agent-guard": {"enabled": False},
            "language": {"enabled": False, "adapters": []},
            "tests": {"enabled": False, "command": ""},
        },
        "protectedFiles": ["Cargo.toml"],
        "mergeGate": {"requireGreen": True, "deleteBranchAfterMerge": False},
        "updatedBy": "owner",
        "updatedAt": 1,
    }


class ConfigVersionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        (self.root / "Cargo.toml").write_text(CARGO, encoding="utf-8")
        self.urls = []

    def fetch(self, url, token):
        self.urls.append(url)
        if "/config?" in url:
            version = int(url.split("version=")[1]) if "version=" in url else 5
            body = config(version)
            return {"config": body, "digest": srv.hashlib.sha256(srv.canonical_config(body).encode()).hexdigest()}
        return {"baseline": {"files": [{"path": "Cargo.toml", "fingerprint": fingerprint_file("Cargo.toml", CARGO)}]}}

    def request(self, **extra):
        return run.RunRequest(
            self.root, Path(run.__file__).resolve().parents[1], "commit", repository="ForkHorizon/Example", **extra
        )

    def test_the_current_version_is_used_and_reported_by_default(self):
        results, version = run.run_checks_versioned(
            self.request(), srv.Server("https://ci.example", "t", self.fetch), lambda c, d: (0, "")
        )
        self.assertEqual(version, 5)
        self.assertTrue(all(item["status"] == "passed" for item in results))
        self.assertNotIn("version=", self.urls[0])

    def test_a_pinned_version_is_requested_and_reported(self):
        _, version = run.run_checks_versioned(
            self.request(config_version=3), srv.Server("https://ci.example", "t", self.fetch), lambda c, d: (0, "")
        )
        self.assertEqual(version, 3)
        self.assertTrue(self.urls[0].endswith("&version=3"))

    def test_the_plain_entry_point_still_returns_only_results(self):
        results = run.run_checks(
            self.request(), srv.Server("https://ci.example", "t", self.fetch), lambda c, d: (0, "")
        )
        self.assertIsInstance(results, list)

    def test_the_cli_prints_the_config_version_in_its_json(self):

        out = io.StringIO()
        env = {"CI_SCOPE_URL": "https://ci.example", "CI_SCOPE_CONFIG_TOKEN": "t"}
        with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(out):
            code = cli.main(
                [
                    "--root",
                    str(self.root),
                    "--repository",
                    "ForkHorizon/Example",
                    "--tier",
                    "commit",
                    "--config-version",
                    "4",
                    "--json",
                ],
                fetch=self.fetch,
                runner=lambda c, d: (0, ""),
            )
        lines = out.getvalue().strip().splitlines()
        self.assertEqual(code, 0)
        self.assertTrue(lines[0].startswith("CI Scope: PASSED"))
        self.assertEqual(json.loads(lines[1])["configVersion"], 4)


if __name__ == "__main__":
    unittest.main()
