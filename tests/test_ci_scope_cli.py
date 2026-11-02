import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts import ci_scope_cli as cli
from scripts.protected_files import fingerprint_file

CARGO = '[workspace.lints.rust]\nunsafe_code = "forbid"\n'
CONFIG = {
    "schema": 1,
    "repository": "ForkHorizon/Example",
    "version": 1,
    "observeOnly": False,
    "lanes": {
        "code-rules": {"enabled": True, "params": {"maxFileLines": 600, "maxFunctionLines": 80, "maxNestingDepth": 4, "maxParameters": 5, "ignore": [], "forbidSuppressions": True}},
        "agent-guard": {"enabled": False},
        "language": {"enabled": True, "adapters": ["rust"]},
        "tests": {"enabled": False, "command": ""},
    },
    "protectedFiles": ["Cargo.toml", "**/Cargo.toml"],
    "mergeGate": {"requireGreen": True, "deleteBranchAfterMerge": False},
    "updatedBy": "owner",
    "updatedAt": 1,
}


def git(root, *args):
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        git(self.root, "init", "-q")
        git(self.root, "remote", "add", "origin", "git@github.com:ForkHorizon/Example.git")
        (self.root / "Cargo.toml").write_text(CARGO, encoding="utf-8")
        self.baseline = {"Cargo.toml": fingerprint_file("Cargo.toml", CARGO)}
        self.commands = []

    def fetch(self, config=CONFIG, digest=None):
        def fake(url, token):
            self.assertEqual(token, "secret")
            if "/config?" in url:
                text = cli.canonical_config(config)
                return {"config": config, "digest": digest or hashlib.sha256(text.encode()).hexdigest()}
            return {"baseline": {"files": [{"path": p, "fingerprint": f} for p, f in self.baseline.items()]}}
        return fake

    def runner(self, fail_on=None):
        def run(command, cwd):
            self.commands.append(command)
            return (1, "clippy: unused variable") if fail_on and fail_on in command else (0, "")
        return run

    def results(self, tier="push", **kwargs):
        runner = kwargs.pop("runner", self.runner())
        return cli.run_checks(self.root, Path(cli.__file__).resolve().parents[1], tier, self.fetch(**kwargs), runner, "https://ci.example", "secret")

    def test_clean_tree_passes_and_push_tier_runs_full_checks(self):
        results = self.results()
        self.assertEqual([r["id"] for r in results], ["protected-files", "code-linter", "forbidden-constructs", "duplicate-blocks", "file-roles", "rust-quality"])
        self.assertTrue(all(r["status"] == "passed" for r in results))
        self.assertTrue(any(c[:2] == ["cargo", "clippy"] for c in self.commands))
        self.assertTrue(cli.verdict_line(results).startswith("CI Scope: PASSED"))

    def test_commit_tier_skips_full_checks(self):
        ids = [r["id"] for r in self.results(tier="commit")]
        self.assertNotIn("rust-quality", ids)
        self.assertFalse(any(c[:2] == ["cargo", "clippy"] for c in self.commands))

    def test_weakened_lint_section_fails_the_protected_files_check(self):
        (self.root / "Cargo.toml").write_text(CARGO + 'dead_code = "allow"\n', encoding="utf-8")
        results = self.results(tier="commit")
        self.assertEqual(results[0]["status"], "failed")
        self.assertIn("modified Cargo.toml", results[0]["detail"])
        self.assertIn("protected-files: modified Cargo.toml", cli.verdict_line(results))

    def test_deleted_protected_file_fails(self):
        (self.root / "Cargo.toml").unlink()
        self.assertIn("deleted Cargo.toml", self.results(tier="commit")[0]["detail"])

    def test_failing_command_is_reported_with_its_output(self):
        results = self.results(runner=self.runner(fail_on="clippy"))
        failed = [r for r in results if r["status"] == "failed"]
        self.assertEqual([r["id"] for r in failed], ["rust-quality"])
        self.assertIn("unused variable", cli.verdict_line(results))

    def test_a_tampered_config_digest_is_refused(self):
        with self.assertRaises(cli.CliError):
            self.results(digest="0" * 64)

    def test_verdict_for_no_results_is_a_failure(self):
        self.assertIn("FAILED", cli.verdict_line([]))
        self.assertIn("FAILED", cli.verdict_line([{"id": "a", "status": "skipped", "detail": ""}]))

    def test_repository_slug_comes_from_the_origin_remote(self):
        self.assertEqual(cli.repository_slug(self.root), "ForkHorizon/Example")

    def test_device_settings(self):
        self.assertEqual(cli.device_settings({"CI_SCOPE_URL": "https://ci.example/", "CI_SCOPE_CONFIG_TOKEN": "t"}), ("https://ci.example", "t"))
        with self.assertRaises(cli.CliError):
            cli.device_settings({"CI_SCOPE_URL": "http://evil.example", "CI_SCOPE_CONFIG_TOKEN": "t"})
        home = self.root / "home"
        (home / ".config/ci-scope").mkdir(parents=True)
        file = home / ".config/ci-scope/device.json"
        file.write_text(json.dumps({"url": "https://ci.example", "token": "t"}), encoding="utf-8")
        file.chmod(0o644)
        with self.assertRaises(cli.CliError):
            cli.device_settings({}, home)
        file.chmod(0o600)
        self.assertEqual(cli.device_settings({}, home), ("https://ci.example", "t"))
        with self.assertRaises(cli.CliError):
            cli.device_settings({}, self.root / "nowhere")

    def test_digest_matches_the_typescript_default_config(self):
        # Config and digest produced by CI-Scope-Web defaultProjectConfig + canonicalConfig.
        config = json.loads('{"schema":1,"repository":"ForkHorizon/Example","version":1,"observeOnly":false,"lanes":{"code-rules":{"enabled":true,"params":{"maxFileLines":600,"maxFunctionLines":80,"maxNestingDepth":4,"maxParameters":5,"ignore":[],"forbidSuppressions":true}},"agent-guard":{"enabled":true},"language":{"enabled":false,"adapters":[]},"tests":{"enabled":false,"command":""}},"protectedFiles":["Cargo.toml","**/Cargo.toml","clippy.toml","rustfmt.toml","deny.toml","rust-toolchain.toml","tsconfig.json",".eslintrc*","eslint.config.*","package.json","ruff.toml",".ruff.toml","pyproject.toml",".swiftlint.yml",".swift-format",".golangci.yml",".github/**"],"mergeGate":{"requireGreen":true,"deleteBranchAfterMerge":false},"updatedBy":"owner","updatedAt":1700000000000}')
        digest = 'b0dc9ff8f006aaa056eb86aa2bb4a887e14ed7864e6cf462933ef82fecc7110f'
        self.assertEqual(hashlib.sha256(cli.canonical_config(config).encode()).hexdigest(), digest)

    def test_canonical_config_matches_the_server_form(self):
        self.assertEqual(cli.canonical_config({"b": [1, {"z": 1, "a": 2}], "a": "é"}), '{"a":"é","b":[1,{"a":2,"z":1}]}\n')


if __name__ == "__main__":
    unittest.main()
