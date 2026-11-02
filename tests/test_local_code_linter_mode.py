"""A local (hook) run lints the files being committed, not the whole repository."""

import unittest
from pathlib import Path

from scripts.ci_scope_adapters import commands_for


def spec():
    return type("Check", (), {"type": "code-linter", "config": None, "params": {"mode": "auto"}})()


def mode_of(event: str) -> str:
    command = commands_for(spec(), Path("/repo"), Path("/gates"), ("a", "b"), event)[0]
    return command[command.index("--mode") + 1]


class LocalCodeLinterModeTests(unittest.TestCase):
    def test_hook_runs_lint_only_the_worktree_changes(self):
        self.assertEqual(mode_of("local"), "worktree")

    def test_scheduled_runs_still_lint_everything(self):
        self.assertEqual(mode_of("schedule"), "all")

    def test_pull_requests_still_lint_the_changed_files(self):
        self.assertEqual(mode_of("pull_request"), "changed")


if __name__ == "__main__":
    unittest.main()
