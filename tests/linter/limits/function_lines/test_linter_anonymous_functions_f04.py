import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[4] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

spec = importlib.util.spec_from_file_location("linter_checker", SCRIPTS_DIR / "code-linter.py")
linter_checker = importlib.util.module_from_spec(spec)
sys.modules["linter_checker"] = linter_checker
spec.loader.exec_module(linter_checker)


LIMITS = {
    "max_file_lines": 100,
    "max_function_lines": 3,
    "max_nesting_depth": 10,
    "max_parameters": 2,
    "max_comment_lines": 20,
    "max_doc_comment_lines": 20,
    "max_types_per_file": 20,
}


class AnonymousFunctionLimitTests(unittest.TestCase):
    def issues(self, filename, source):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / filename
            path.write_text(source, encoding="utf-8")
            return linter_checker.check_paths(root, [path], LIMITS)

    def test_javascript_function_expression_reports_both_limits_at_declaration(self):
        source = """const f = function (a, b = 1, ...rest) {
  x();
  y();
  z();
};
"""
        self.assertEqual(
            linter_checker.brace_function_lengths(source, "javascript"),
            [("<anonymous>", 1, 5, 3)],
        )
        issues = self.issues("sample.js", source)
        self.assertEqual(
            [(issue.kind, issue.line) for issue in issues],
            [
                ("function_length", 1),
                ("max_parameters", 1),
            ],
        )

    def test_javascript_nested_function_expression_callbacks_keep_each_location(self):
        source = """const values = items.map(function (item, index, extra) {
  return items.map(function (value, position, meta) {
    return value;
  });
});
"""
        self.assertEqual(
            linter_checker.brace_function_lengths(source, "javascript"),
            [
                ("<anonymous>", 2, 3, 3),
                ("<anonymous>", 1, 5, 3),
            ],
        )
        issues = self.issues("nested.js", source)
        self.assertEqual(
            [(issue.kind, issue.line, issue.message) for issue in issues],
            [
                ("max_parameters", 2, "Function '<anonymous>' has 3 parameters; limit is 2."),
                ("function_length", 1, "<anonymous> has 5 lines; function/method limit is 3."),
                ("max_parameters", 1, "Function '<anonymous>' has 3 parameters; limit is 2."),
            ],
        )

    def test_javascript_multiline_destructured_default_and_rest_parameters(self):
        source = """const f = function (
  { id, name },
  options = { enabled: true },
  ...rest
) {
  use(id);
  use(options);
  use(rest);
};
"""
        self.assertEqual(
            linter_checker.brace_function_lengths(source, "javascript"),
            [("<anonymous>", 1, 9, 3)],
        )
        issues = self.issues("multiline.js", source)
        self.assertEqual(
            [(issue.kind, issue.line) for issue in issues],
            [
                ("function_length", 1),
                ("max_parameters", 1),
            ],
        )

    def test_typescript_generic_annotated_function_expression_is_counted(self):
        source = """const f = function <T extends Record<string, unknown>>(
  value: T,
  fallback: T,
  ...rest: T[]
): T {
  return value;
};
"""
        self.assertEqual(
            linter_checker.brace_function_lengths(source, "typescript"),
            [("<anonymous>", 1, 7, 3)],
        )
        issues = self.issues("generic.ts", source)
        self.assertEqual(
            [(issue.kind, issue.line) for issue in issues],
            [
                ("function_length", 1),
                ("max_parameters", 1),
            ],
        )

    def test_swift_typed_capture_list_closure_reports_limits_at_opening_line(self):
        source = """let f = { [weak self] (a: Int, b: Int, c: Int) in
  use(a)
  use(b)
  use(c)
}
"""
        self.assertEqual(
            linter_checker.brace_function_lengths(source, "swift"),
            [("<anonymous>", 1, 5, 3)],
        )
        issues = self.issues("Typed.swift", source)
        self.assertEqual(
            [(issue.kind, issue.line) for issue in issues],
            [
                ("function_length", 1),
                ("max_parameters", 1),
            ],
        )

    def test_swift_untyped_multiline_body_closure_counts_in_parameters(self):
        source = """items.map { a, b, c in
  use(a)
  use(b)
  use(c)
}
"""
        self.assertEqual(
            linter_checker.brace_function_lengths(source, "swift"),
            [("<anonymous>", 1, 5, 3)],
        )
        issues = self.issues("Untyped.swift", source)
        self.assertEqual(
            [(issue.kind, issue.line) for issue in issues],
            [
                ("function_length", 1),
                ("max_parameters", 1),
            ],
        )

    def test_csharp_expression_lambda_is_one_line_and_checks_parameters(self):
        source = """Func<int, int, int, int> f = (a, b, c) => a + b + c;
"""
        self.assertEqual(
            linter_checker.brace_function_lengths(source, "csharp"),
            [("<anonymous>", 1, 1, 3)],
        )
        issues = self.issues("Expression.cs", source)
        self.assertEqual(
            [(issue.kind, issue.line) for issue in issues],
            [
                ("max_parameters", 1),
            ],
        )

    def test_csharp_block_lambda_and_nested_lambda_are_both_checked(self):
        source = """Action<int, int, int> f = (a, b, c) => {
  var inner = (x, y, z) => {
    use(x);
    use(y);
    use(z);
  };
  use(a);
};
"""
        self.assertEqual(
            linter_checker.brace_function_lengths(source, "csharp"),
            [
                ("<anonymous>", 2, 5, 3),
                ("<anonymous>", 1, 8, 3),
            ],
        )
        issues = self.issues("Nested.cs", source)
        self.assertEqual(
            [(issue.kind, issue.line) for issue in issues],
            [
                ("function_length", 2),
                ("max_parameters", 2),
                ("function_length", 1),
                ("max_parameters", 1),
            ],
        )

    def test_valid_nonviolating_anonymous_constructs_remain_silent(self):
        sources = {
            "valid.js": "const f = (a, b) => a + b;\n",
            "valid.swift": "let f = { (a: Int, b: Int) in a + b }\n",
            "valid.cs": "Func<int, int, int> f = (a, b) => a + b;\n",
        }
        for filename, source in sources.items():
            with self.subTest(filename=filename):
                self.assertEqual(self.issues(filename, source), [])

    def test_public_code_linter_reports_anonymous_function_issues(self):
        source = """const f = function (a, b, c) {
  x();
  y();
  z();
};
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "sample.js").write_text(source, encoding="utf-8")
            (root / ".code-linter.json").write_text(
                '{"max_file_lines": 100, "max_function_lines": 3, '
                '"max_parameters": 2, "max_nesting_depth": 10, '
                '"max_comment_lines": 20, "max_doc_comment_lines": 20, '
                '"max_types_per_file": 20}\n',
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / "code-linter.py"), "--root", str(root)],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn("title=function_length", result.stdout)
        self.assertIn("title=max_parameters", result.stdout)
        self.assertIn("file=sample.js", result.stdout)
        self.assertIn("line=1", result.stdout)
        self.assertIn("Code Linter failed: 2 issue(s)", result.stdout)


if __name__ == "__main__":
    unittest.main()
