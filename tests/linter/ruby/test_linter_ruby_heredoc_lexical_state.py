import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("ruby_heredoc_linter", SCRIPTS / "code-linter.py")
linter = importlib.util.module_from_spec(spec)
sys.modules["ruby_heredoc_linter"] = linter
spec.loader.exec_module(linter)


class RubyHeredocLexicalStateTests(unittest.TestCase):
    def assert_ruby_syntax_ok(self, source):
        with tempfile.NamedTemporaryFile(suffix=".rb", mode="w", encoding="utf-8") as fixture:
            fixture.write(source)
            fixture.flush()
            result = subprocess.run(["ruby", "-c", fixture.name], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def assert_ruby_syntax_error(self, source):
        with tempfile.NamedTemporaryFile(suffix=".rb", mode="w", encoding="utf-8") as fixture:
            fixture.write(source)
            fixture.flush()
            result = subprocess.run(["ruby", "-c", fixture.name], capture_output=True, text=True, check=False)
        self.assertNotEqual(result.returncode, 0, result.stdout)

    def test_executable_method_after_fake_string_marker_is_measured(self):
        source = 'marker = "<<~FAKE"\n'
        source += "def too_long(a, b, c, d, e, f)\n"
        source += "  work\n" * 51
        source += "end\n"

        self.assertEqual(linter.check_syntax("sample.rb", source, "ruby"), [])
        self.assertEqual(
            linter.ruby_function_lengths(source),
            [("too_long", 2, 53, 6)],
        )

    def test_single_quoted_string_marker_does_not_start_heredoc(self):
        source = "marker = '<<-FAKE'\n"
        source += "def after_marker\n  work\nend\n"

        self.assertEqual(linter.ruby_function_lengths(source), [("after_marker", 2, 3, 0)])
        self.assertEqual(linter.check_syntax("sample.rb", source, "ruby"), [])

    def test_comment_marker_does_not_start_heredoc(self):
        source = "# <<~COMMENT\n"
        source += "def after_comment\n  work\nend\n"

        self.assertEqual(linter.ruby_function_lengths(source), [("after_comment", 2, 3, 0)])
        self.assertEqual(linter.check_syntax("sample.rb", source, "ruby"), [])

    def test_escaped_and_near_markers_remain_ordinary_string_content(self):
        source = 'escaped = "\\<<~FAKE"\nnear = "<<~FAKEX"\n'
        source += "def after_strings\n  work\nend\n"

        self.assertEqual(linter.ruby_function_lengths(source), [("after_strings", 3, 3, 0)])
        self.assertEqual(linter.check_syntax("sample.rb", source, "ruby"), [])

    def test_plain_heredoc_content_hides_fake_ruby(self):
        source = (
            "def wrapper\n  text = <<TEXT\ndef fake(a, b, c, d, e, f)\n  if one\n    end\n  end\nTEXT\n  work\nend\n"
        )

        self.assertEqual(linter.ruby_function_lengths(source), [("wrapper", 1, 9, 0)])
        self.assertEqual(linter.check_syntax("sample.rb", source, "ruby"), [])
        self.assert_ruby_syntax_ok(source)

    def test_squiggly_heredoc_accepts_indented_terminator(self):
        source = "text = <<~TEXT\n  fake = <<~INNER\n  end\n    TEXT\n"
        source += "  TEXT\n"
        source += "def after_squiggly\n  work\nend\n"

        self.assertEqual(linter.ruby_function_lengths(source), [("after_squiggly", 6, 3, 0)])
        self.assertEqual(linter.check_syntax("sample.rb", source, "ruby"), [])
        self.assert_ruby_syntax_ok(source)

    def test_indented_heredoc_accepts_indented_terminator(self):
        source = "text = <<-TEXT\n  def fake\n    end\n  TEXT\n"
        source += "def after_indented\n  work\nend\n"

        self.assertEqual(linter.ruby_function_lengths(source), [("after_indented", 5, 3, 0)])
        self.assertEqual(linter.check_syntax("sample.rb", source, "ruby"), [])
        self.assert_ruby_syntax_ok(source)

    def test_quoted_nowdoc_marker_is_masked(self):
        source = "text = <<'NOWDOC'\n#{fake_interpolation}\ndef fake(a, b, c, d, e, f) {}\nNOWDOC\n"
        source += "def after_nowdoc\n  work\nend\n"

        self.assertEqual(linter.ruby_function_lengths(source), [("after_nowdoc", 5, 3, 0)])
        self.assertEqual(linter.check_syntax("sample.rb", source, "ruby"), [])
        self.assert_ruby_syntax_ok(source)

    def test_interpolated_heredoc_content_is_opaque(self):
        source = "text = <<~TEXT\n  #{value}\n  if fake\n    end\nTEXT\ndef after_interpolation\n  work\nend\n"

        self.assertEqual(linter.ruby_function_lengths(source), [("after_interpolation", 6, 3, 0)])
        self.assertEqual(linter.check_syntax("sample.rb", source, "ruby"), [])
        self.assert_ruby_syntax_ok(source)

    def test_heredoc_opener_with_semicolon_is_masked(self):
        source = "text = <<~TEXT;\n  def fake(a, b, c, d, e, f)\n  end\nTEXT\n"
        source += "def after_semicolon\n  work\nend\n"

        self.assertEqual(linter.ruby_function_lengths(source), [("after_semicolon", 5, 3, 0)])
        self.assertEqual(linter.check_syntax("sample.rb", source, "ruby"), [])
        self.assert_ruby_syntax_ok(source)

    def test_multiple_heredocs_are_consumed_in_source_order(self):
        source = (
            "first, second = <<FIRST, <<'SECOND'\n"
            "def fake_first\n"
            "end\n"
            "FIRST\n"
            "def fake_second\n"
            "end\n"
            "SECOND\n"
            "def after_multiple\n"
            "  work\n"
            "end\n"
        )

        self.assertEqual(linter.ruby_function_lengths(source), [("after_multiple", 8, 3, 0)])
        self.assertEqual(linter.check_syntax("sample.rb", source, "ruby"), [])
        self.assert_ruby_syntax_ok(source)

    def test_multiline_declaration_parameters_and_line_accounting_survive_heredoc(self):
        source = (
            "def process(\n"
            "  first, second, third, fourth, fifth, sixth\n"
            ")\n"
            "  text = <<~TEXT\n"
            "    def fake\n"
            "    end\n"
            "  TEXT\n"
            "  work\n"
            "end\n"
        )

        self.assertEqual(linter.ruby_function_lengths(source), [("process", 1, 9, 6)])
        self.assertEqual(linter.check_syntax("sample.rb", source, "ruby"), [])
        self.assert_ruby_syntax_ok(source)

    def test_terminator_like_prefix_does_not_close_heredoc(self):
        source = (
            "text = <<~TEXT\n"
            "TEXT_EXTRA\n"
            "def fake(a, b, c, d, e, f)\n"
            "end\n"
            "  TEXT\n"
            "def after_exact_terminator\n"
            "  work\n"
            "end\n"
        )

        self.assertEqual(linter.ruby_function_lengths(source), [("after_exact_terminator", 6, 3, 0)])
        self.assertEqual(linter.check_syntax("sample.rb", source, "ruby"), [])
        self.assert_ruby_syntax_ok(source)

    def test_unclosed_heredoc_is_reported_at_opener_line(self):
        source = "text = <<~MISSING\n"
        source += "def hidden\n  end\n"
        self.assert_ruby_syntax_error(source)
        issues = linter.check_syntax("sample.rb", source, "ruby")

        self.assertEqual(len(issues), 1)
        self.assertEqual(
            (issues[0].path, issues[0].line, issues[0].kind),
            ("sample.rb", 1, "syntax_error"),
        )
        self.assertIn("heredoc", issues[0].message)

    def test_unclosed_fake_string_marker_does_not_report_heredoc(self):
        source = 'text = "<<~MISSING"\n'
        source += "def visible\n  work\nend\n"

        self.assertEqual(linter.check_syntax("sample.rb", source, "ruby"), [])
        self.assertEqual(linter.ruby_function_lengths(source), [("visible", 2, 3, 0)])

    def test_function_length_limit_is_enforced_after_fake_comment_marker(self):
        source = "# <<~FAKE\n"
        source += "def too_long\n"
        source += "  work\n" * 51
        source += "end\n"

        self.assertEqual(linter.ruby_function_lengths(source)[0][2:], (53, 0))
        self.assertGreater(linter.ruby_function_lengths(source)[0][2], 50)

    def test_parameter_limit_is_enforced_after_fake_marker(self):
        source = 'marker = "<<~FAKE"\n'
        source += "def many(a, b, c, d, e, f)\n  work\nend\n"

        self.assertGreater(linter.ruby_function_lengths(source)[0][3], 5)

    def test_nesting_limit_is_enforced_after_fake_marker(self):
        source = 'marker = "<<~FAKE"\n'
        source += "def nested\n  if one\n    if two\n      work\n    end\n  end\nend\n"

        issues = linter.check_nesting_depth("sample.rb", source, "ruby", 1)
        self.assertEqual([issue.kind for issue in issues], ["nesting_depth"])

    def test_public_cli_reports_code_after_fake_marker(self):
        source = 'marker = "<<~FAKE"\n'
        source += "def too_long(a, b, c, d, e, f)\n"
        source += "  work\n" * 4
        source += "end\n"
        config = {
            "include_extensions": [".rb"],
            "max_function_lines": 3,
            "max_parameters": 5,
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".code-linter.json").write_text(json.dumps(config), encoding="utf-8")
            (root / "sample.rb").write_text(source, encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "code-linter.py"),
                    "--root",
                    str(root),
                    "--config",
                    ".code-linter.json",
                    "--mode",
                    "all",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("title=function_length", result.stdout)
        self.assertIn("title=max_parameters", result.stdout)
        self.assertIn("file=sample.rb", result.stdout)


if __name__ == "__main__":
    unittest.main()
