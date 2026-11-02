import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.ci_scope_adapters import commands_for
from scripts.server_config import ConfigError, build_check_specs

ROOT = Path(__file__).resolve().parents[1]


def config(**lanes):
    base = {
        "schema": 1,
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
            "agent-guard": {"enabled": True},
            "language": {"enabled": False, "adapters": []},
            "tests": {"enabled": False, "command": ""},
        },
    }
    base["lanes"].update(lanes)
    return base


class ServerConfigTests(unittest.TestCase):
    def specs(self, value):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        return build_check_specs(value, Path(self.tmp.name) / "cfg")

    def test_default_lanes_expand_to_the_core_checks(self):
        ids = [spec.id for spec in self.specs(config())]
        self.assertEqual(
            ids,
            [
                "code-linter",
                "forbidden-constructs",
                "duplicate-blocks",
                "file-roles",
                "test-protection",
                "agent-docs-stable",
            ],
        )

    def test_disabled_lanes_and_suppression_switch_remove_checks(self):
        value = config(**{"agent-guard": {"enabled": False}})
        value["lanes"]["code-rules"]["params"]["forbidSuppressions"] = False
        self.assertEqual([spec.id for spec in self.specs(value)], ["code-linter", "duplicate-blocks", "file-roles"])
        value["lanes"]["code-rules"]["enabled"] = False
        self.assertEqual(self.specs(value), [])

    def test_language_and_test_lanes_are_full_speed(self):
        value = config(
            language={"enabled": True, "adapters": ["rust", "swift"]}, tests={"enabled": True, "command": "cargo test"}
        )
        specs = {spec.id: spec for spec in self.specs(value)}
        self.assertEqual(specs["rust-quality"].speed, "full")
        self.assertEqual(specs["swift-compile"].resources, ("xcode",))
        self.assertEqual(specs["project-tests"].params["command"], "cargo test")
        self.assertEqual(specs["code-linter"].speed, "fast")

    def test_unsupported_adapter_and_schema_are_refused(self):
        with self.assertRaises(ConfigError):
            self.specs(config(language={"enabled": True, "adapters": ["unity"]}))
        with self.assertRaises(ConfigError):
            self.specs({**config(), "schema": 2})

    def test_linter_config_is_written_outside_the_checkout_with_server_limits(self):
        value = config()
        value["lanes"]["code-rules"]["params"].update({"maxFileLines": 300, "ignore": ["generated/**"]})
        spec = self.specs(value)[0]
        written = json.loads(Path(spec.config).read_text(encoding="utf-8"))
        self.assertEqual(written["max_file_lines"], 300)
        self.assertIn("generated/**", written["ignore"])
        self.assertTrue(Path(spec.config).is_absolute())

    def test_generated_linter_config_is_accepted_by_the_real_linter(self):
        value = config()
        value["lanes"]["code-rules"]["params"]["maxFileLines"] = 100
        spec = self.specs(value)[0]
        with tempfile.TemporaryDirectory() as repo:
            (Path(repo) / "ok.py").write_text("x = 1\n", encoding="utf-8")
            (Path(repo) / "long.py").write_text("x = 1\n" * 150, encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/code-linter.py"),
                    "--root",
                    repo,
                    "--mode",
                    "all",
                    "--config",
                    spec.config,
                    "--trusted-config",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("long.py", result.stdout + result.stderr)

    def test_linter_refuses_an_outside_config_without_the_trusted_flag(self):
        spec = self.specs(config())[0]
        with tempfile.TemporaryDirectory() as repo:
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/code-linter.py"),
                    "--root",
                    repo,
                    "--mode",
                    "all",
                    "--config",
                    spec.config,
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must be inside the repository", result.stdout + result.stderr)

    def test_adapter_marks_server_configs_as_trusted(self):
        spec = self.specs(config())[0]
        with tempfile.TemporaryDirectory() as root:
            command = commands_for(spec, Path(root), ROOT, ("a", "b"), "local")[-1]
        self.assertIn("--trusted-config", command)

    def test_new_check_types_have_commands(self):
        value = config(
            language={"enabled": True, "adapters": ["rust"]}, tests={"enabled": True, "command": "make test"}
        )
        specs = {spec.id: spec for spec in self.specs(value)}
        with tempfile.TemporaryDirectory() as root:
            rust = commands_for(specs["rust-quality"], Path(root), ROOT, ("a", "b"))
            self.assertEqual(rust[1][:4], ["cargo", "clippy", "--workspace", "--all-targets"])
            self.assertEqual(len(rust), 2)
            (Path(root) / "deny.toml").write_text("", encoding="utf-8")
            self.assertEqual(
                commands_for(specs["rust-quality"], Path(root), ROOT, ("a", "b"))[-1], ["cargo", "deny", "check"]
            )
            self.assertEqual(
                commands_for(specs["project-tests"], Path(root), ROOT, ("a", "b")), [["/bin/sh", "-c", "make test"]]
            )


if __name__ == "__main__":
    unittest.main()
