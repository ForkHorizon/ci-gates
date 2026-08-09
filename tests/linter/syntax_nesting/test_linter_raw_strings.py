import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("raw_strings_linter", SCRIPTS / "code-linter.py")
linter = importlib.util.module_from_spec(spec)
sys.modules["raw_strings_linter"] = linter
spec.loader.exec_module(linter)


class RawStringScannerTests(unittest.TestCase):
    def assert_no_structural_issues(self, source, language):
        self.assertEqual(linter.check_syntax("fixture", source, language), [])
        self.assertEqual(linter.function_lengths(source, language), [])
        self.assertEqual(linter.check_nesting_depth("fixture", source, language, 0), [])

    def test_rust_plain_multiline_raw_string_hides_fake_function_and_braces(self):
        source = 'let sample = r"\nfn fake(a, b, c, d, e, f) {\n    if first { second(); }\n}\n";\n'
        self.assert_no_structural_issues(source, "rust")

    def test_rust_hash_raw_string_hides_quotes_comments_and_fake_declarations(self):
        source = 'let sample = r#"\nfn fake(a, b, c, d, e, f) { /* } */ }\n"quoted" and // not a comment\n"#;\n'
        self.assert_no_structural_issues(source, "rust")

    def test_rust_multihash_raw_string_requires_all_hashes_to_close(self):
        source = (
            'let sample = r###"\n'
            "fn fake(a, b, c, d, e, f) { if nested { work(); } }\n"
            'contains "# and "## but neither closes\n'
            '"###;\n'
        )
        self.assert_no_structural_issues(source, "rust")

    def test_rust_mismatching_hash_count_is_unterminated_at_last_line(self):
        source = 'let sample = r##"\nfn fake(a, b, c, d, e, f) { }\n"#;\n'
        issues = linter.check_syntax("src/sample.rs", source, "rust")
        self.assertEqual(len(issues), 1)
        self.assertEqual(
            (issues[0].path, issues[0].line, issues[0].kind, issues[0].message),
            ("src/sample.rs", 3, "syntax_error", "Unterminated comment or string."),
        )

    def test_rust_extra_closing_hash_does_not_match_exact_hash_count(self):
        source = 'let sample = r##"\nfn fake(a, b, c, d, e, f) { }\n"###;\n'
        issues = linter.check_syntax("src/sample.rs", source, "rust")
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].kind, "syntax_error")
        self.assertEqual(issues[0].message, "Unterminated comment or string.")

    def test_rust_real_functions_before_and_after_raw_string_are_preserved(self):
        source = (
            "fn before(a) { work(); }\n"
            'let sample = r##"\n'
            "fn fake(a, b, c, d, e, f) { if a { b(); } }\n"
            '"##;\n'
            "fn after(b) { work(); }\n"
        )
        self.assertEqual(
            linter.function_lengths(source, "rust"),
            [("before", 1, 1, 1), ("after", 5, 1, 1)],
        )

    def test_c_empty_delimiter_raw_string_hides_multiline_fake_function(self):
        source = (
            'const char *sample = R"(\n'
            "void fake(int a, int b, int c, int d, int e, int f) {\n"
            "    if (ready) { work(); }\n"
            "}\n"
            ')";\n'
        )
        self.assert_no_structural_issues(source, "c")

    def test_cpp_custom_delimiter_raw_string_hides_delimiter_like_content(self):
        source = (
            'auto sample = R"PAYLOAD(\n'
            "void fake(int a, int b, int c, int d, int e, int f) { }\n"
            ')PAYLOADX" is content, as are braces { }\n'
            ')PAYLOAD";\n'
        )
        self.assert_no_structural_issues(source, "cpp")

    def test_cpp_raw_string_does_not_close_on_wrong_delimiter(self):
        source = (
            'auto sample = R"TAG(\n'
            "void fake(int a, int b, int c, int d, int e, int f) {\n"
            "    if (one) { if (two) { work(); } }\n"
            ')OTHER" remains content\n'
            ')TAG";\n'
        )
        self.assert_no_structural_issues(source, "cpp")

    def test_adjacent_cpp_raw_strings_are_each_consumed(self):
        source = (
            'auto sample = R"(void fake(int a, int b, int c, int d, int e, int f) {})"'
            'R"TAG(void also_fake(int a, int b, int c, int d, int e, int f) {})TAG";\n'
        )
        self.assert_no_structural_issues(source, "cpp")

    def test_unterminated_cpp_raw_string_reports_last_line_and_path(self):
        source = 'auto sample = R"END(\nvoid fake(int a, int b, int c, int d, int e, int f) {\n'
        issues = linter.check_syntax("include/sample.hpp", source, "cpp")
        self.assertEqual(len(issues), 1)
        self.assertEqual(
            (issues[0].path, issues[0].line, issues[0].kind, issues[0].message),
            ("include/sample.hpp", 2, "syntax_error", "Unterminated comment or string."),
        )

    def test_c_raw_string_does_not_hide_real_code_after_terminator(self):
        source = (
            "void before(int a) { work(); }\n"
            'const char *sample = R"DOC(fake { void hidden(int a, int b, int c, int d, int e, int f) {} })DOC";\n'
            "void after(int b) { work(); }\n"
        )
        self.assertEqual(
            linter.function_lengths(source, "c"),
            [("before", 1, 1, 1), ("after", 3, 1, 1)],
        )

    def test_public_code_linter_script_ignores_raw_string_samples(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".code-linter.json").write_text('{"include_extensions": [".rs", ".cpp"]}\n', encoding="utf-8")
            (root / "sample.rs").write_text(
                'let docs = r###"\nfn fake(a, b, c, d, e, f) { if a { b(); } }\n"###;\n',
                encoding="utf-8",
            )
            (root / "sample.cpp").write_text(
                'auto docs = R"TAG(\nvoid fake(int a, int b, int c, int d, int e, int f) {}\n)TAG";\n',
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(SCRIPTS / "code-linter.py"), "--root", str(root)],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Code Linter passed", result.stdout)
        self.assertNotIn("max_parameters", result.stdout)
        self.assertNotIn("nesting_depth", result.stdout)


if __name__ == "__main__":
    unittest.main()
