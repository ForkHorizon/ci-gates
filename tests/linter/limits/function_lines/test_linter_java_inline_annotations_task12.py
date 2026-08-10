import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[4] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
spec = importlib.util.spec_from_file_location("java_annotation_linter", SCRIPTS_DIR / "code-linter.py")
linter = importlib.util.module_from_spec(spec)
sys.modules["java_annotation_linter"] = linter
spec.loader.exec_module(linter)


LIMITS = {
    "max_file_lines": 100,
    "max_function_lines": 3,
    "max_nesting_depth": 10,
    "max_parameters": 2,
    "max_comment_lines": 20,
    "max_doc_comment_lines": 20,
    "max_types_per_file": 20,
}


class JavaInlineAnnotationTests(unittest.TestCase):
    def lengths(self, source):
        return linter.brace_function_lengths(source, "java")

    def issues(self, source, filename="Sample.java", limits=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / filename
            path.write_text(source, encoding="utf-8")
            return linter.check_paths(root, [path], limits or LIMITS)

    def test_override_method_with_three_parameters_is_detected(self):
        source = "@Override public void run(int a, int b, int c) { work(); }\n"
        self.assertEqual(self.lengths(source), [("run", 1, 1, 3)])

    def test_suppress_warnings_annotation_arguments_do_not_change_count(self):
        source = '@SuppressWarnings("unchecked") public void run(int a, int b, int c) { work(); }\n'
        self.assertEqual(self.lengths(source), [("run", 1, 1, 3)])

    def test_custom_annotation_with_named_argument_is_detected(self):
        source = "@Transactional(readOnly = true) public void save(int a, int b, int c) { work(); }\n"
        self.assertEqual(self.lengths(source), [("save", 1, 1, 3)])

    def test_multiple_same_line_annotations_are_removed_in_order(self):
        source = "@A @B(value = 1) public void run(int a, int b, int c) { work(); }\n"
        self.assertEqual(self.lengths(source), [("run", 1, 1, 3)])

    def test_nested_annotation_parentheses_arrays_and_quotes_are_balanced(self):
        source = (
            '@Outer(value = {@Inner(value = {1, 2}), @Other(text = "(" )}) '
            "public void run(int a, int b, int c) { work(); }\n"
        )
        self.assertEqual(self.lengths(source), [("run", 1, 1, 3)])

    def test_annotation_followed_by_generic_method_is_detected(self):
        source = "@A public <T> T convert(T first, T second, T third) { return first; }\n"
        self.assertEqual(self.lengths(source), [("convert", 1, 1, 3)])

    def test_annotated_bounded_generic_method_is_detected(self):
        source = "@A public <T extends Comparable<T>> T convert(T a, T b, T c) { return a; }\n"
        self.assertEqual(self.lengths(source), [("convert", 1, 1, 3)])

    def test_annotated_multi_parameter_generic_method_is_detected(self):
        source = "@A public <K, V> Map<K, V> convert(K a, V b, K c) { return null; }\n"
        self.assertEqual(self.lengths(source), [("convert", 1, 1, 3)])

    def test_annotation_followed_by_constructor_is_detected(self):
        source = "class Widget {\n    @Inject public Widget(int a, int b, int c) { init(); }\n}\n"
        self.assertEqual(self.lengths(source), [("Widget", 2, 1, 3)])

    def test_annotation_on_own_line_remains_detected(self):
        source = "@Override\npublic void run(int a, int b, int c) { work(); }\n"
        self.assertEqual(self.lengths(source), [("run", 2, 1, 3)])

    def test_ordinary_unannotated_java_method_remains_detected(self):
        source = "public void run(int a, int b, int c) { work(); }\n"
        self.assertEqual(self.lengths(source), [("run", 1, 1, 3)])

    def test_java_anonymous_class_method_with_inline_annotation_is_detected(self):
        source = "Runnable task = new Runnable() {\n    @Override public void run() { work(); }\n};\n"
        self.assertEqual(self.lengths(source), [("run", 2, 1, 0)])

    def test_annotation_like_text_inside_string_does_not_trigger_a_phantom_method(self):
        source = 'String text = "@Override public void fake(int a, int b, int c) { }";\n'
        self.assertEqual(self.lengths(source), [])

    def test_annotation_like_text_inside_comment_does_not_trigger_a_phantom_method(self):
        source = "// @Override public void fake(int a, int b, int c) { }\n"
        self.assertEqual(self.lengths(source), [])

    def test_malformed_annotation_arguments_fail_closed_without_phantom_method(self):
        source = "@A(value = {1, 2} public void fake(int a, int b, int c) { work(); }\n"
        self.assertEqual(self.lengths(source), [])
        self.assertEqual(self.issues(source), [])

    def test_same_line_annotation_and_multiple_declarations_keep_source_order(self):
        source = (
            "@A public void first() { one(); }\n"
            "@B public void second(int a, int b, int c) { two(); }\n"
            "public void first() { three(); }\n"
        )
        self.assertEqual(
            self.lengths(source),
            [("first", 1, 1, 0), ("second", 2, 1, 3), ("first", 3, 1, 0)],
        )

    def test_public_cli_reports_function_length_for_annotated_method(self):
        source = """class Sample {
    @Override public void run(int a, int b) {
        one();
        two();
        three();
    }
}
"""
        issues = self.issues(source)
        self.assertEqual([(issue.kind, issue.line) for issue in issues], [("function_length", 2)])

    def test_public_cli_reports_max_parameters_for_annotated_method(self):
        source = "@Override public void run(int a, int b, int c) { work(); }\n"
        issues = self.issues(source)
        self.assertEqual([(issue.kind, issue.line) for issue in issues], [("max_parameters", 1)])

    def test_public_cli_reports_max_parameters_for_bounded_generic_method(self):
        source = "@A public <T extends Comparable<T>> T convert(T a, T b, T c) { return a; }\n"
        issues = self.issues(source)
        self.assertEqual([(issue.kind, issue.line) for issue in issues], [("max_parameters", 1)])

    def test_public_cli_diagnostics_include_both_configured_violations(self):
        source = """class Sample {
    @Override public void run(int a, int b, int c) {
        one();
        two();
        three();
    }
}
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Sample.java").write_text(source, encoding="utf-8")
            (root / ".code-linter.json").write_text(
                '{"max_file_lines": 100, "max_function_lines": 3, "max_parameters": 2, '
                '"max_nesting_depth": 10, "max_comment_lines": 20, "max_doc_comment_lines": 20, '
                '"max_types_per_file": 20}\n',
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / "code-linter.py"), "--root", str(root)],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("title=function_length", result.stdout)
        self.assertIn("title=max_parameters", result.stdout)
        self.assertIn("file=Sample.java", result.stdout)
        self.assertIn("line=2", result.stdout)

    def test_csharp_bracket_attributes_remain_detected(self):
        source = "[Obsolete] public void Run(int a, int b, int c) { work(); }\n"
        self.assertEqual(linter.brace_function_lengths(source, "csharp"), [("Run", 1, 1, 3)])

    def test_cpp_bracket_annotations_remain_detected(self):
        source = "[nodiscard] int run(int a, int b, int c) { return a; }\n"
        self.assertEqual(linter.brace_function_lengths(source, "cpp"), [("run", 1, 1, 3)])

    def test_java_call_like_blocks_with_annotation_prefix_are_not_declarations(self):
        source = "@A service.run(a, b, c) { fake(); fake(); fake(); }\n"
        self.assertEqual(self.lengths(source), [])


if __name__ == "__main__":
    unittest.main()
