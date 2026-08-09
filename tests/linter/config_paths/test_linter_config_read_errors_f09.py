"""Regression tests for F-09 config read diagnostics."""

import contextlib
import importlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import code_linter

config_module = importlib.import_module("code_linter.config")


class ConfigReadErrorTests(unittest.TestCase):
    def assert_config_error(self, path, action, *message_fragments):
        error = io.StringIO()
        with contextlib.redirect_stderr(error), self.assertRaises(SystemExit) as raised:
            action()
        report = error.getvalue()
        self.assertEqual(raised.exception.code, 2)
        self.assertEqual(report.count("::error "), 1)
        self.assertIn(f"file={path.as_posix()}", report)
        self.assertNotIn("Traceback", report)
        for fragment in message_fragments:
            self.assertIn(fragment, report)
        return report

    def test_missing_config_path_loaded_directly_is_structured(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing.json"
            self.assert_config_error(
                path,
                lambda: config_module.read_config(path),
                "Unable to read Code Linter config",
                "No such file or directory",
            )

    def test_permission_denied_read_is_structured_without_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".code-linter.json"
            path.write_text("{}\n", encoding="utf-8")
            with patch.object(Path, "read_text", side_effect=PermissionError(13, "Permission denied")):
                self.assert_config_error(
                    path,
                    lambda: code_linter.load_config(path),
                    "Unable to read Code Linter config",
                    "Permission denied",
                )

    def test_read_failure_does_not_leak_exception_text_or_secret(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".code-linter.json"
            path.write_text("{}\n", encoding="utf-8")
            secret = "super-secret-config-token"
            with patch.object(Path, "read_text", side_effect=OSError(secret)):
                report = self.assert_config_error(
                    path,
                    lambda: code_linter.load_config(path),
                    "Unable to read Code Linter config",
                )
            self.assertNotIn(secret, report)

    def test_directory_at_config_path_is_structured(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config-directory"
            path.mkdir()
            self.assert_config_error(
                path,
                lambda: code_linter.load_config(path),
                "Unable to read Code Linter config",
                "Is a directory",
            )

    def test_invalid_utf8_config_bytes_are_structured(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".code-linter.json"
            path.write_bytes(b'{"max_file_lines": "\xff"}')
            self.assert_config_error(
                path,
                lambda: code_linter.load_config(path),
                "Unable to read Code Linter config",
                "UTF-8",
            )

    def test_other_os_error_is_structured_and_useful(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".code-linter.json"
            path.write_text("{}\n", encoding="utf-8")
            with patch.object(Path, "read_text", side_effect=OSError(5, "Input/output error")):
                self.assert_config_error(
                    path,
                    lambda: code_linter.load_config(path),
                    "Unable to read Code Linter config",
                    "Input/output error",
                )

    def test_json_syntax_error_keeps_existing_config_error_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".code-linter.json"
            path.write_text("{not-json}\n", encoding="utf-8")
            report = self.assert_config_error(
                path,
                lambda: code_linter.load_config(path),
                "Invalid JSON config:",
            )
            self.assertNotIn("Unable to read Code Linter config", report)

    def test_schema_error_keeps_existing_config_error_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".code-linter.json"
            path.write_text('{"unknown_setting": true}\n', encoding="utf-8")
            report = self.assert_config_error(
                path,
                lambda: code_linter.load_config(path),
                "Unknown config key(s): unknown_setting.",
            )
            self.assertNotIn("Unable to read Code Linter config", report)

    def test_duplicate_key_validator_error_remains_a_json_config_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".code-linter.json"
            path.write_text('{"max_file_lines": 100, "max_file_lines": 200}\n', encoding="utf-8")
            duplicate_error = json.JSONDecodeError("Duplicate config key", path.read_text(), 1)
            with patch.object(config_module.json, "loads", side_effect=duplicate_error):
                report = self.assert_config_error(
                    path,
                    lambda: code_linter.load_config(path),
                    "Invalid JSON config: Duplicate config key",
                )
            self.assertNotIn("Unable to read Code Linter config", report)

    def test_public_entry_point_reports_missing_config_without_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "code-linter.py"),
                    "--root",
                    str(root),
                    "--config",
                    "missing.json",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("::error ", result.stderr)
            self.assertIn("Code Linter config does not exist.", result.stderr)
            self.assertNotIn("Traceback", result.stderr)

    def test_public_entry_point_reports_directory_config_without_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config-dir"
            config_path.mkdir()
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "code-linter.py"),
                    "--root",
                    str(root),
                    "--config",
                    config_path.name,
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("::error ", result.stderr)
            self.assertIn("Code Linter config does not exist.", result.stderr)
            self.assertNotIn("Traceback", result.stderr)

    def test_public_entry_point_reports_invalid_utf8_without_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / ".code-linter.json"
            config_path.write_bytes(b"{\xff")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "code-linter.py"),
                    "--root",
                    str(root),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("::error ", result.stderr)
            self.assertIn("UTF-8", result.stderr)
            self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
