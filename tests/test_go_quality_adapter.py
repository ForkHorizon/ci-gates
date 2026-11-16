"""Tests that go-quality checks every Go module, wherever its go.mod sits."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from ci_scope_adapters import commands_for


def _check():
    return type("Check", (), {"type": "go-quality", "workdir": ".", "config": None, "params": {}})()


def _dirs(commands):
    return [command[3] for command in commands if command[-3:] == ["golangci-lint", "run", "./..."]]


class GoQualityAdapterTests(unittest.TestCase):
    def test_checks_each_module_in_its_own_directory(self):
        # CI-Scope keeps agent/go.mod and agent/watchdog/go.mod; nothing at the root.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for module in ("agent", "agent/watchdog", ".build/x", "vendor/y"):
                (root / module).mkdir(parents=True)
                (root / module / "go.mod").write_text("module m\n", encoding="utf-8")
            commands = commands_for(_check(), root, ROOT, ("base", "head"))
            self.assertEqual(_dirs(commands), ["agent", "agent/watchdog"])

    def test_root_module_runs_at_the_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "go.mod").write_text("module m\n", encoding="utf-8")
            self.assertEqual(_dirs(commands_for(_check(), root, ROOT, ("base", "head"))), ["."])

    def test_skips_with_exit_zero_when_there_is_no_go_module(self):
        with tempfile.TemporaryDirectory() as directory:
            commands = commands_for(_check(), Path(directory), ROOT, ("base", "head"))
            self.assertEqual(len(commands), 1)
            result = subprocess.run(commands[0], capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0)
            self.assertIn("skipped", result.stdout)


if __name__ == "__main__":
    unittest.main()
