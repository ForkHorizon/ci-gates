import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import code_linter
import code_linter.paths as linter_paths
from code_linter.coverage import CoverageGap, PathInventory
from code_linter.github import format_github_command
from code_linter.model import Issue
from code_linter.runner import print_coverage_report
from _progress import progress


class GithubAnnotationSafetyTests(unittest.TestCase):
    def test_swift_compile_gate_imports_without_a_circular_progress_dependency(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "swift-compile-gate.py"), "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_command_formatter_escapes_every_property_and_data_field(self):
        command = format_github_command(
            "error",
            properties=(
                ("file", "bad\nname\r,:%\x1b\"';&.py"),
                ("line", "1,2:3"),
                ("title", "kind\n,:%\x1b\"';&"),
            ),
            data="message\nwith\rpercent % and \x1b[31m ANSI",
        )
        self.assertEqual(
            command,
            "::error file=bad%0Aname%0D%2C%3A%25%1B\"';&.py,line=1%2C2%3A3,"
            "title=kind%0A%2C%3A%25%1B\"';&::message%0Awith%0Dpercent %25 and %1B[31m ANSI",
        )

    def test_command_formatter_supports_data_only_commands(self):
        self.assertEqual(
            format_github_command("notice", data="safe message"),
            "::notice::safe message",
        )

    def test_progress_escapes_percent_encoded_command_sequences_in_paths(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            progress("lint", detail="bad%0A::warning file=forged::x")
        command = output.getvalue().strip()
        self.assertIn('"detail": "bad%250A::warning file=forged::x"', command)
        self.assertNotIn('"detail": "bad%0A::warning', command)

    def test_data_escapes_low_and_c1_control_bytes(self):
        self.assertEqual(code_linter.escape_github_data("\t\x00\x1f\x7f\x80\x9f"), "%09%00%1F%7F%80%9F")

    def test_properties_escape_comma_and_colon(self):
        self.assertEqual(code_linter.escape_github_property("a,b:c"), "a%2Cb%3Ac")

    def test_properties_preserve_quotes_and_shell_metacharacters(self):
        value = "quote\"';&$`<>[]()"
        self.assertEqual(code_linter.escape_github_property(value), value)

    def test_config_error_escapes_control_text_in_message(self):
        error = io.StringIO()
        with contextlib.redirect_stderr(error), self.assertRaises(SystemExit):
            code_linter.config_error(Path("config.json"), "bad\x1b\n%")
        self.assertIn("bad%1B%0A%25", error.getvalue())

    def test_config_error_escapes_control_text_in_path(self):
        error = io.StringIO()
        with contextlib.redirect_stderr(error), self.assertRaises(SystemExit):
            code_linter.config_error(Path("bad\n,:config.json"), "invalid")
        self.assertIn("bad%0A%2C%3Aconfig.json", error.getvalue())

    def test_coverage_warning_and_notice_outputs_are_commands(self):
        warning_gap = CoverageGap("gap\n,:.sql", "unsupported_surface", ".sql", "SQL\nmessage")
        gaps = (
            warning_gap,
            *(CoverageGap(f"extra-{index}.sql", "unsupported_surface", ".sql", "SQL") for index in range(50)),
        )
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            print_coverage_report(PathInventory((Path("selected.py"),), gaps), {}, "report")
        report = output.getvalue()
        self.assertIn("file=gap%0A%2C%3A.sql", report)
        self.assertIn("SQL%0Amessage", report)
        self.assertIn("::notice::Code Linter suppressed 1 additional", report)

    def test_changed_path_diagnostic_escapes_git_output(self):
        failed = subprocess.CompletedProcess([], 1, "", "bad\n::warning file=forged::x")
        error = io.StringIO()
        with (
            patch("code_linter.paths.subprocess.run", side_effect=[failed, failed]),
            contextlib.redirect_stderr(error),
            self.assertRaises(SystemExit),
        ):
            linter_paths.changed_paths(Path("."), "base", "head")
        self.assertIn("bad%0A::warning file=forged::x", error.getvalue())

    def test_newline_filename_is_encoded_by_the_linter(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".code-linter.json").write_text('{"max_file_lines": 1}\n', encoding="utf-8")
            (root / "bad\nname.py").write_text("one\ntwo\n", encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = code_linter.main(["--root", str(root)])
        annotations = [line for line in output.getvalue().splitlines() if line.startswith("::error ")]
        self.assertEqual(result, 1)
        self.assertEqual(len(annotations), 1)
        self.assertIn("file=bad%0Aname.py", annotations[0])

    def test_properties_escape_separators_and_control_text(self):
        issue = Issue(
            "bad\nname\r,:%\x1b\"';&.py",
            1,
            "kind\n,:%\x1b\"';&",
            "message\nwith\rpercent % and \x1b[31m ANSI",
        )
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code_linter.print_report([issue], 1, "all")
        report = output.getvalue()
        annotation = report.splitlines()[0]
        self.assertEqual(report.count("::error "), 1)
        self.assertNotRegex(annotation, r"[\x00-\x1f\x7f-\x9f]")
        self.assertIn("file=bad%0Aname%0D%2C%3A%25%1B\"';&.py", annotation)
        self.assertIn("title=kind%0A%2C%3A%25%1B\"';&::", annotation)
        self.assertIn("message%0Awith%0Dpercent %25 and %1B[31m ANSI", annotation)

    def test_unknown_config_key_cannot_start_a_second_command(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".code-linter.json"
            key = "bad\n::warning file=forged::x"
            path.write_text(json.dumps({key: 1}), encoding="utf-8")
            error = io.StringIO()
            with contextlib.redirect_stderr(error), self.assertRaises(SystemExit):
                code_linter.load_config(path)
        report = error.getvalue()
        annotation = report.rstrip("\n")
        self.assertEqual(report.count("::error "), 1)
        self.assertNotRegex(annotation, r"[\x00-\x1f\x7f-\x9f]")
        self.assertIn("bad%0A::warning file=forged::x", annotation)


if __name__ == "__main__":
    unittest.main()
