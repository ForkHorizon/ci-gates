"""Projects whose config lives on the server are not held to the signed-commit policy guard."""

import tempfile
import unittest
from pathlib import Path

from scripts.ci_scope_adapters import commands_for
from scripts.server_config import build_check_specs

CONFIG = {
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
        "agent-guard": {"enabled": False},
        "language": {"enabled": False, "adapters": []},
        "tests": {"enabled": False, "command": ""},
    },
}


def code_linter_commands(params):
    spec = type("Check", (), {"type": "code-linter", "config": "/cfg.json", "params": params})()
    return commands_for(spec, Path("/repo"), Path("/gates"), ("a", "b"), "pull_request")


class SignatureGuardTests(unittest.TestCase):
    def test_server_config_marks_the_code_linter_without_the_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            spec = next(s for s in build_check_specs(CONFIG, Path(directory)) if s.id == "code-linter")
        self.assertIs(spec.params["signature_guard"], False)
        self.assertEqual(len(code_linter_commands(spec.params)), 1)

    def test_repo_configs_keep_the_guard(self):
        commands = code_linter_commands({"mode": "auto"})
        self.assertEqual(len(commands), 2)
        self.assertIn("policy_signature_guard.py", commands[0][1])


if __name__ == "__main__":
    unittest.main()
