from __future__ import annotations

import configparser
import importlib.util
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "self-check.yml"
COVERAGE_CONFIG = ROOT / "configs" / "coverage.ini"
COVERAGE_VERSION = "7.8.2"
COVERAGE_THRESHOLD = "90"
WORKFLOW_HELPER_SPEC = importlib.util.spec_from_file_location(
    "coverage_workflow_helper", ROOT / "tests" / "test_self_check_workflow.py"
)
assert WORKFLOW_HELPER_SPEC is not None
assert WORKFLOW_HELPER_SPEC.loader is not None
WORKFLOW_HELPER = importlib.util.module_from_spec(WORKFLOW_HELPER_SPEC)
sys.modules[WORKFLOW_HELPER_SPEC.name] = WORKFLOW_HELPER
WORKFLOW_HELPER_SPEC.loader.exec_module(WORKFLOW_HELPER)
workflow_job_commands = WORKFLOW_HELPER.workflow_job_commands


class PythonCoverageGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")
        cls.commands = workflow_job_commands(cls.workflow, "self-check")

    def test_coverage_config_exists_and_is_parseable(self):
        parser = configparser.ConfigParser()
        with COVERAGE_CONFIG.open(encoding="utf-8") as stream:
            parser.read_file(stream)
        self.assertTrue(parser.has_section("run"))
        self.assertTrue(parser.has_section("report"))

    def test_coverage_config_measures_branches(self):
        parser = configparser.ConfigParser()
        parser.read(COVERAGE_CONFIG)
        self.assertEqual(parser.getboolean("run", "branch"), True)

    def test_coverage_config_limits_source_to_enforcement_package(self):
        parser = configparser.ConfigParser()
        parser.read(COVERAGE_CONFIG)
        self.assertEqual(parser.get("run", "source"), "scripts/code_linter")

    def test_coverage_config_has_justified_fail_under_threshold(self):
        parser = configparser.ConfigParser()
        parser.read(COVERAGE_CONFIG)
        self.assertEqual(parser.get("report", "fail_under"), COVERAGE_THRESHOLD)
        self.assertIn("93%", COVERAGE_CONFIG.read_text(encoding="utf-8"))
        self.assertIn("fail_under = 90", COVERAGE_CONFIG.read_text(encoding="utf-8"))

    def test_workflow_installs_pinned_coverage_version(self):
        install_commands = [command for command in self.commands if "coverage==" in command]
        self.assertEqual(
            install_commands,
            [f"python3 -m pip install --disable-pip-version-check coverage=={COVERAGE_VERSION}"],
        )

    def test_workflow_runs_coverage_with_repository_config(self):
        self.assertIn(
            "python3 -m coverage run --rcfile=configs/coverage.ini -m unittest discover -s tests -p 'test_*.py' -q",
            "\n".join(self.commands),
        )

    def test_workflow_reports_coverage_with_repository_config(self):
        self.assertIn("python3 -m coverage report --rcfile=configs/coverage.ini", "\n".join(self.commands))

    def test_workflow_erases_stale_measurement_before_running(self):
        self.assertIn("python3 -m coverage erase", "\n".join(self.commands))

    def test_workflow_keeps_discovery_guard_before_coverage_suite(self):
        guard = "python3 scripts/check-test-discovery.py --start-directory tests --pattern 'test_*.py'"
        measured_suite = (
            "python3 -m coverage run --rcfile=configs/coverage.ini -m unittest discover -s tests -p 'test_*.py' -q"
        )
        measured_index = next(index for index, command in enumerate(self.commands) if measured_suite in command)
        self.assertLess(self.commands.index(guard), measured_index)

    def test_workflow_does_not_use_unpinned_coverage_install(self):
        self.assertFalse(
            any(
                re.search(r"pip install(?:[^\n]*\s)coverage(?:\s|$)", command)
                and f"coverage=={COVERAGE_VERSION}" not in command
                for command in self.commands
            )
        )

    def test_workflow_runs_plain_unit_suite_before_measured_gate(self):
        plain_suite = "python3 -m unittest discover -s tests -p 'test_*.py' -q"
        measured_suite = (
            "python3 -m coverage run --rcfile=configs/coverage.ini -m unittest discover -s tests -p 'test_*.py' -q"
        )
        self.assertEqual(self.commands.count(plain_suite), 1)
        measured_index = next(index for index, command in enumerate(self.commands) if measured_suite in command)
        self.assertLess(self.commands.index(plain_suite), measured_index)


if __name__ == "__main__":
    unittest.main()
