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


class SwiftMultilineClosureTests(unittest.TestCase):
    def functions(self, source):
        return linter_checker.brace_function_lengths(source, "swift")

    def issues(self, filename, source, limits=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / filename
            path.write_text(source, encoding="utf-8")
            return linter_checker.check_paths(root, [path], limits or LIMITS)

    def assert_parses_as_swift(self, source):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.swift"
            path.write_text(source, encoding="utf-8")
            result = subprocess.run(
                ["swiftc", "-parse", str(path)],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_single_line_closure_remains_detected(self):
        source = "let closure = { (a: Int, b: Int, c: Int) in a + b + c }\n"
        self.assertEqual(self.functions(source), [("<anonymous>", 1, 1, 3)])

    def test_multiline_explicit_typed_parameters_are_detected(self):
        source = """let closure = {
    (a: Int,
     b: Int,
     c: Int)
    in
    a + b + c
}
"""
        self.assertEqual(self.functions(source), [("<anonymous>", 1, 7, 3)])

    def test_multiline_implicit_parameter_list_is_detected(self):
        source = """let closure = {
    value
    in
    value
}
"""
        self.assertEqual(self.functions(source), [("<anonymous>", 1, 5, 1)])

    def test_multiline_capture_list_and_typed_parameters_are_detected(self):
        source = """let closure = { [weak owner]
    (a: Int, b: Int, c: Int)
    in
    owner?.use(a)
    owner?.use(b)
    owner?.use(c)
}
"""
        self.assertEqual(self.functions(source), [("<anonymous>", 1, 7, 3)])

    def test_closure_opening_brace_on_following_line_is_detected(self):
        source = """let closure =
{
    (a: Int, b: Int, c: Int)
    in
    a + b + c
}
"""
        self.assertEqual(self.functions(source), [("<anonymous>", 2, 5, 3)])

    def test_closure_passed_as_an_argument_is_detected(self):
        source = """let result = values.map(
    {
        (a: Int, b: Int, c: Int)
        in
        a + b + c
    }
)
"""
        self.assertEqual(self.functions(source), [("<anonymous>", 2, 5, 3)])

    def test_multiline_trailing_closure_after_call_arguments_is_detected(self):
        source = """let result = values.map() {
    (a: Int, b: Int, c: Int)
    in
    a + b + c
}
"""
        self.assertEqual(self.functions(source), [("<anonymous>", 1, 5, 3)])

    def test_assigned_closure_is_detected_at_assignment_line(self):
        source = """let transform = {
    (value: Int, fallback: Int, extra: Int)
    in
    value + fallback + extra
}
"""
        self.assertEqual(self.functions(source), [("<anonymous>", 1, 5, 3)])

    def test_returned_closure_is_detected_inside_named_function(self):
        source = """func makeClosure() -> (Int, Int, Int) -> Int {
    return {
        (a: Int, b: Int, c: Int)
        in
        a + b + c
    }
}
"""
        self.assertEqual(
            self.functions(source),
            [("<anonymous>", 2, 5, 3), ("makeClosure", 1, 7, 0)],
        )

    def test_nested_multiline_closures_keep_each_start_line_and_parameters(self):
        source = """let outer = {
    (a: Int, b: Int, c: Int)
    in
    values.map(
        {
            (x: Int, y: Int, z: Int)
            in
            x + y + z
        }
    )
}
"""
        self.assertEqual(
            self.functions(source),
            [("<anonymous>", 5, 5, 3), ("<anonymous>", 1, 11, 3)],
        )

    def test_generic_and_type_heavy_parameters_are_counted_at_top_level(self):
        source = """let closure = {
    (values: [Result<[String: Set<Int>], Error>],
     fallback: (Int, String) -> Bool,
     result: Swift.Result<Int, Error>)
    in
    values.isEmpty && fallback(1, "value") && result != nil
}
"""
        self.assertEqual(self.functions(source), [("<anonymous>", 1, 7, 3)])

    def test_comments_and_strings_containing_in_do_not_trigger_early_detection(self):
        source = """let closure = {
    (a: Int, b: Int, c: Int) // the word in is only a comment
    in
    let text = "in is data, not the marker"
    return a + b + c
}
"""
        self.assertEqual(self.functions(source), [("<anonymous>", 1, 6, 3)])

    def test_incomplete_closure_without_marker_is_not_classified(self):
        source = """let incomplete = {
    (a: Int, b: Int, c: Int)
"""
        self.assertEqual(self.functions(source), [])

    def test_multiline_closure_line_accounting_is_deterministic(self):
        source = """let closure = {
    value
    in
    value
}
"""
        first = self.functions(source)
        second = self.functions(source)
        self.assertEqual(first, second)
        self.assertEqual(first[0][1:3], (1, 5))

    def test_function_length_limit_reports_multiline_closure_at_opening_line(self):
        source = """let closure = {
    (a: Int, b: Int, c: Int)
    in
    use(a)
    use(b)
    use(c)
}
"""
        issues = self.issues("Closure.swift", source)
        self.assertEqual(
            [(issue.kind, issue.line) for issue in issues],
            [("function_length", 1), ("max_parameters", 1)],
        )

    def test_parameter_limit_reports_multiline_closure(self):
        source = """let closure = {
    (a: Int, b: Int, c: Int)
    in
    a + b + c
}
"""
        issues = self.issues("Parameters.swift", source, {**LIMITS, "max_function_lines": 10})
        self.assertEqual(
            [(issue.kind, issue.line) for issue in issues],
            [("max_parameters", 1)],
        )

    def test_nesting_limit_counts_control_flow_inside_closure_but_not_closure_brace(
        self,
    ):
        source = """func run() {
    let closure = {
        value
        in
        if outer {
            if inner {
                use(value)
            }
        }
    }
}
"""
        issues = linter_checker.check_nesting_depth("Nesting.swift", source, "swift", 1)
        self.assertEqual([(issue.kind, issue.line) for issue in issues], [("nesting_depth", 6)])

    def test_control_block_without_in_is_not_classified_as_a_closure(self):
        source = """func run(a: Int, b: Int, c: Int) {
    if a > 0 {
        use(a)
    }
    for item in items {
        use(item)
    }
}
"""
        self.assertEqual(self.functions(source), [("run", 1, 8, 3)])

    def test_public_cli_reports_multiline_closure_limits(self):
        source = """let closure = {
    (a: Int, b: Int, c: Int)
    in
    use(a)
    use(b)
    use(c)
}
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Closure.swift").write_text(source, encoding="utf-8")
            (root / ".code-linter.json").write_text(
                '{"max_file_lines": 100, "max_function_lines": 3, '
                '"max_parameters": 2, "max_nesting_depth": 10, '
                '"max_comment_lines": 20, "max_doc_comment_lines": 20, '
                '"max_types_per_file": 20}\n',
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "code-linter.py"),
                    "--root",
                    str(root),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn("title=function_length", result.stdout)
        self.assertIn("title=max_parameters", result.stdout)
        self.assertIn("file=Closure.swift", result.stdout)
        self.assertIn("line=1", result.stdout)


if __name__ == "__main__":
    unittest.main()
