import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("template_interpolation_linter", SCRIPTS / "code-linter.py")
linter = importlib.util.module_from_spec(spec)
sys.modules["template_interpolation_linter"] = linter
spec.loader.exec_module(linter)


class JavaScriptTemplateInterpolationTests(unittest.TestCase):
    def test_plain_interpolation_expression_remains_valid_code(self):
        source = "const message = `hello ${name}`;\n"
        self.assertEqual(linter.check_syntax("fixture.js", source, "javascript"), [])
        self.assertEqual(linter.brace_function_lengths(source, "javascript"), [])

    def test_arrow_function_inside_interpolation_is_measured(self):
        source = "const value = `result: ${(a, b, c) => a + b + c}`;\n"
        self.assertEqual(
            linter.brace_function_lengths(source, "javascript"),
            [("value", 1, 1, 3)],
        )

    def test_named_function_expression_inside_interpolation_is_measured(self):
        source = "const value = `${function render(a) { return a; }}`;\n"
        self.assertEqual(linter.brace_function_lengths(source, "javascript"), [("render", 1, 1, 1)])

    def test_multiline_interpolation_function_keeps_declaration_line_and_length(self):
        source = "const value = `prefix ${function render(a) {\n  first();\n  second();\n  third();\n}}`;\n"
        self.assertEqual(
            linter.brace_function_lengths(source, "javascript"),
            [("render", 1, 5, 1)],
        )

    def test_interpolation_function_parameters_are_counted(self):
        source = "const value = `${function render(a, b, c, d) { return a; }}`;\n"
        self.assertEqual(linter.brace_function_lengths(source, "javascript")[0][3], 4)

    def test_control_flow_nesting_inside_interpolation_is_checked(self):
        source = "const value = `${(() => {\nif (ready) {\nif (complete) { work(); }\nreturn 1;\n}\n})()}`;\n"
        issues = linter.check_nesting_depth("fixture.js", source, "javascript", 1)
        self.assertEqual([(issue.kind, issue.line) for issue in issues], [("nesting_depth", 3)])

    def test_nested_object_braces_do_not_close_interpolation_early(self):
        source = "const value = `${({ config: { enabled: true }, run: function run(a, b) { return a; } })}`;\n"
        self.assertEqual(linter.brace_function_lengths(source, "javascript"), [("run", 1, 1, 2)])
        self.assertEqual(linter.check_syntax("fixture.js", source, "javascript"), [])

    def test_nested_template_literal_interpolation_is_scanned(self):
        source = "const value = `outer ${`inner ${function render(a, b, c) { return a; }}`}`;\n"
        self.assertEqual(linter.brace_function_lengths(source, "javascript"), [("render", 1, 1, 3)])

    def test_escaped_backtick_does_not_end_template_literal(self):
        source = "const text = `literal \\` function fake(a, b, c) { } still text`;\n"
        self.assertEqual(linter.check_syntax("fixture.js", source, "javascript"), [])
        self.assertEqual(linter.brace_function_lengths(source, "javascript"), [])

    def test_interpolation_text_inside_normal_string_is_opaque(self):
        source = 'const text = "${function fake(a, b, c) { } if (fake) {}}";\n'
        self.assertEqual(linter.check_syntax("fixture.js", source, "javascript"), [])
        self.assertEqual(linter.brace_function_lengths(source, "javascript"), [])

    def test_comments_inside_interpolation_are_masked_but_code_after_them_is_scanned(self):
        source = "const value = `${/* function fake(a, b, c) { } */ function real(a, b, c) { return a; }}`;\n"
        self.assertEqual(linter.brace_function_lengths(source, "javascript"), [("real", 1, 1, 3)])

    def test_typescript_annotations_and_generics_inside_interpolation_are_supported(self):
        source = "const value = `${function <T extends Record<string, unknown>>(a: T, b: T, c: T): T { return a; }}`;\n"
        self.assertEqual(linter.brace_function_lengths(source, "typescript"), [("<anonymous>", 1, 1, 3)])

    def test_multiple_interpolations_each_contribute_functions(self):
        source = "const value = `first: ${function first() { return 1; }}\nsecond: ${function second(a, b) { return a + b; }}`;\n"
        self.assertEqual(
            linter.brace_function_lengths(source, "javascript"),
            [("first", 1, 1, 0), ("second", 2, 1, 2)],
        )

    def test_unclosed_interpolation_reports_syntax_error(self):
        source = "const value = `${function broken() { return 1; }`;\n"
        issues = linter.check_syntax("src/broken.js", source, "javascript")
        self.assertEqual(len(issues), 1)
        self.assertEqual(
            (issues[0].path, issues[0].line, issues[0].kind, issues[0].message),
            ("src/broken.js", 1, "syntax_error", "Unterminated comment or string."),
        )

    def test_unclosed_interpolation_brace_reports_syntax_error(self):
        source = "const value = `${{ value: 1 }`;\n"
        self.assertEqual(linter.check_syntax("broken.ts", source, "typescript")[0].kind, "syntax_error")

    def test_code_looking_template_text_stays_opaque(self):
        source = "const docs = `function fake(a, b, c) { if (x) { y(); } } // prose`;\n"
        self.assertEqual(linter.check_syntax("docs.js", source, "javascript"), [])
        self.assertEqual(linter.brace_function_lengths(source, "javascript"), [])
        self.assertEqual(linter.check_nesting_depth("docs.js", source, "javascript", 0), [])

    def test_escaped_interpolation_marker_stays_template_text(self):
        source = "const docs = `literal \\${function fake(a, b, c) { }`;\n"
        self.assertEqual(linter.check_syntax("docs.js", source, "javascript"), [])
        self.assertEqual(linter.brace_function_lengths(source, "javascript"), [])

    def test_public_cli_reports_interpolation_function_limits(self):
        source = "const value = `${function render(a, b, c) {\n  one();\n  two();\n  three();\n}}`;\n"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "sample.js").write_text(source, encoding="utf-8")
            (root / ".code-linter.json").write_text(
                '{"max_file_lines": 100, "max_function_lines": 3, "max_parameters": 2, '
                '"max_nesting_depth": 10, "max_comment_lines": 20, "max_doc_comment_lines": 20, '
                '"max_types_per_file": 20}\n',
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(SCRIPTS / "code-linter.py"), "--root", str(root)],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("title=function_length", result.stdout)
        self.assertIn("title=max_parameters", result.stdout)
        self.assertIn("file=sample.js", result.stdout)
        self.assertIn("line=1", result.stdout)


if __name__ == "__main__":
    unittest.main()
