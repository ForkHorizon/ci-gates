import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[4] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
spec = importlib.util.spec_from_file_location("shell_function_linter", SCRIPTS_DIR / "code-linter.py")
linter = importlib.util.module_from_spec(spec)
sys.modules["shell_function_linter"] = linter
spec.loader.exec_module(linter)

from code_linter.shell import shell_function_lengths, shell_syntax_issues


LIMITS = {
    "max_file_lines": 100,
    "max_function_lines": 50,
    "max_nesting_depth": 10,
    "max_parameters": 1,
    "max_comment_lines": 20,
    "max_doc_comment_lines": 20,
    "max_types_per_file": 20,
}


class ShellMultilineFunctionBraceTests(unittest.TestCase):
    def assert_lengths(self, source, expected):
        self.assertEqual(shell_function_lengths(source), expected)
        self.assertEqual(linter.function_lengths(source, "shell"), expected)

    def assert_valid_shell(self, source):
        self.assertEqual(shell_syntax_issues("fixture.sh", source), [])

    def test_same_line_parenthesized_function_remains_compatible(self):
        source = "build() { work; }\n"
        self.assert_lengths(source, [("build", 1, 1, 0)])

    def test_same_line_function_keyword_without_parentheses_remains_compatible(self):
        source = "function build { work; }\n"
        self.assert_lengths(source, [("build", 1, 1, 0)])

    def test_same_line_function_keyword_with_parentheses_remains_compatible(self):
        source = "function build() { work; }\n"
        self.assert_lengths(source, [("build", 1, 1, 0)])

    def test_parenthesized_function_with_brace_on_next_line_is_measured(self):
        source = "build()\n{\n  work\n}\n"
        self.assert_valid_shell(source)
        self.assert_lengths(source, [("build", 1, 4, 0)])

    def test_function_keyword_with_brace_on_next_line_is_measured(self):
        source = "function build\n{\n  work\n}\n"
        self.assert_valid_shell(source)
        self.assert_lengths(source, [("build", 1, 4, 0)])

    def test_function_keyword_and_parentheses_with_brace_on_next_line_is_measured(self):
        source = "function build()\n{\n  work\n}\n"
        self.assert_valid_shell(source)
        self.assert_lengths(source, [("build", 1, 4, 0)])

    def test_tabs_and_whitespace_between_declaration_and_brace_are_allowed(self):
        source = "build() \t\n \t{\n\twork\n}\n"
        self.assert_valid_shell(source)
        self.assert_lengths(source, [("build", 1, 4, 0)])

    def test_line_continuation_before_next_line_brace_is_measured(self):
        source = "build() \\\n{\n  work\n}\n"
        self.assert_valid_shell(source)
        self.assert_lengths(source, [("build", 1, 4, 0)])

    def test_continuations_between_function_keyword_name_and_brace_are_measured(self):
        cases = (
            "function \\\nbuild \\\n{\n  work\n}\n",
            "function build \\\n() \\\n{\n  work\n}\n",
            "function \\\nbuild() \\\n{\n  work\n}\n",
        )
        for source in cases:
            with self.subTest(source=source):
                self.assert_valid_shell(source)
                self.assert_lengths(source, [("build", 1, 5, 0)])

    def test_comments_and_blank_lines_between_declaration_and_brace_are_allowed(self):
        source = "build() # declaration\n# keep waiting\n\n{ # opening body\n  work\n}\n"
        self.assert_valid_shell(source)
        self.assert_lengths(source, [("build", 1, 6, 0)])

    def test_nested_group_braces_do_not_close_the_outer_function_early(self):
        source = """build()
{
  if true; then
    {
      work
    }
  fi
}
"""
        self.assert_valid_shell(source)
        self.assert_lengths(source, [("build", 1, 8, 0)])

    def test_nested_case_for_and_if_control_structures_do_not_create_functions(self):
        source = """build()
{
  for item in one two; do
    case "$item" in
      one) if true; then work; fi ;;
    esac
  done
}
"""
        self.assert_valid_shell(source)
        self.assert_lengths(source, [("build", 1, 8, 0)])

    def test_multiple_multiline_functions_preserve_source_order(self):
        source = """first()
{
  one
}
second()
{
  two
}
"""
        self.assert_valid_shell(source)
        self.assert_lengths(source, [("first", 1, 4, 0), ("second", 5, 4, 0)])

    def test_hyphenated_function_name_is_measured(self):
        source = "build-release()\n{\n  work\n}\n"
        self.assert_valid_shell(source)
        self.assert_lengths(source, [("build-release", 1, 4, 0)])

    def test_comments_containing_function_text_do_not_create_phantoms(self):
        source = "# fake() {\nreal()\n{\n  # fake() {\n  work\n}\n"
        self.assert_valid_shell(source)
        self.assert_lengths(source, [("real", 2, 5, 0)])

    def test_quoted_function_text_and_braces_do_not_create_phantoms(self):
        source = "real()\n{\n  printf '%s\\n' 'fake() {'\n  work\n}\n"
        self.assert_valid_shell(source)
        self.assert_lengths(source, [("real", 1, 5, 0)])

    def test_control_structures_are_not_reported_as_functions(self):
        source = """if true; then
  work
fi
for item in one; do
  work "$item"
done
"""
        self.assert_valid_shell(source)
        self.assert_lengths(source, [])

    def test_malformed_declaration_does_not_swallow_a_later_valid_function(self):
        source = """broken()
echo not-a-body
valid()
{
  work
}
"""
        self.assert_lengths(source, [("valid", 3, 4, 0)])

    def test_same_line_function_clears_stale_pending_declaration(self):
        source = "broken()\nvalid() { work; }\n{\n  work\n}\n"
        self.assert_lengths(source, [("valid", 2, 1, 0)])

    def test_quote_only_command_clears_pending_declaration(self):
        source = "broken()\n'not a comment'\n{\n  work\n}\n"
        self.assert_lengths(source, [])

    def test_incomplete_declaration_at_end_fails_closed(self):
        source = "broken()\n"
        self.assert_lengths(source, [])

    def test_brace_line_with_unrelated_code_does_not_activate_pending_function(self):
        source = """fake()
{ echo work; }
valid()
{
  work
}
"""
        self.assert_valid_shell(source)
        self.assert_lengths(source, [("valid", 3, 4, 0)])

    def test_public_function_limit_reports_multiline_shell_function(self):
        source = """build()
{
  one
  two
}
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "build.sh"
            path.write_text(source, encoding="utf-8")
            issues = linter.check_paths(root, [path], {**LIMITS, "max_function_lines": 3})
        self.assertEqual([(issue.kind, issue.line) for issue in issues], [("function_length", 1)])

    def test_public_function_limit_reports_continued_shell_declaration(self):
        source = """function \\
build \\
{
  one
  two
}
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "build.sh"
            path.write_text(source, encoding="utf-8")
            issues = linter.check_paths(root, [path], {**LIMITS, "max_function_lines": 4})
        self.assertEqual([(issue.kind, issue.line) for issue in issues], [("function_length", 1)])

    def test_public_shell_max_parameters_semantics_remain_zero(self):
        source = "build()\n{\n  work\n}\n"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "build.sh"
            path.write_text(source, encoding="utf-8")
            issues = linter.check_paths(root, [path], {**LIMITS, "max_parameters": 1})
        self.assertEqual(issues, [])

    def test_public_cli_reports_multiline_shell_function_length(self):
        source = """build()
{
  one
  two
}
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "build.sh").write_text(source, encoding="utf-8")
            (root / ".code-linter.json").write_text(
                json.dumps({**LIMITS, "max_function_lines": 3}) + "\n", encoding="utf-8"
            )
            result = subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / "code-linter.py"), "--root", str(root), "--mode", "all"],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("title=function_length", result.stdout)
        self.assertIn("file=build.sh", result.stdout)
        self.assertIn("line=1", result.stdout)

    def test_other_language_function_paths_remain_unchanged(self):
        cases = (
            ("public void run() { work(); }\n", "java", "run"),
            ("function run() { work(); }\n", "javascript", "run"),
            ("void run() { work(); }\n", "cpp", "run"),
        )
        for source, language, name in cases:
            with self.subTest(language=language):
                self.assertEqual(linter.function_lengths(source, language)[0][0], name)


if __name__ == "__main__":
    unittest.main()
