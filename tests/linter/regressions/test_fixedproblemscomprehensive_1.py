import importlib.util
import sys
import unittest
from pathlib import Path

# Add scripts directory to path to import code-linter.py
SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

spec = importlib.util.spec_from_file_location("linter_checker", SCRIPTS_DIR / "code-linter.py")
linter_checker = importlib.util.module_from_spec(spec)
sys.modules["linter_checker"] = linter_checker
spec.loader.exec_module(linter_checker)


def scanned_line(code, language):
    """Code left on a single line once comments and string bodies are removed."""
    return linter_checker.scan_c_style_lines(code, language)[0][1]


class FixedProblemsComprehensiveTestSuitePart1(unittest.TestCase):
    def test_problem1_1_https_url_in_string_not_truncated(self):
        code = 'let url = "https://domain.com/path"; let x = 1;'
        line = scanned_line(code, "swift")
        self.assertIn(
            "x",
            line,
            "URL slashes '//' inside string literal must not truncate the line",
        )

    def test_problem1_2_http_url_with_query_params(self):
        code = 'const ep = "http://api.internal:8080/v1?a=1//2"; const active = true;'
        line = scanned_line(code, "typescript")
        self.assertIn("active", line)

    def test_problem1_3_block_comment_slashes_inside_string(self):
        code = 'let s = "/* fake block comment */"; let y = 2;'
        line = scanned_line(code, "swift")
        self.assertIn("y", line)

    def test_problem1_4_rust_lifetime_annotation_with_types(self):
        rust_code = "fn foo<'a, 'b>(x: &'a i32, y: &'b i32) -> &'a i32 { let z = 1; }"
        clean = linter_checker.strip_strings(rust_code, "rust")
        self.assertIn("foo", clean)
        self.assertIn("z", clean)

    def test_problem1_5_swift_string_interpolation_unquoted(self):
        swift_code = 'let msg = "Count is \\(items.count)"; let done = true;'
        line = scanned_line(swift_code, "swift")
        self.assertIn("done", line)

    def test_problem2_1_flat_elif_chain_5_branches(self):
        code = """
def check_val(x):
    if x == 1:
        pass
    elif x == 2:
        pass
    elif x == 3:
        pass
    elif x == 4:
        pass
    elif x == 5:
        pass
"""
        issues = linter_checker.check_nesting_depth("test.py", code, "python", 4)
        self.assertEqual(len(issues), 0, "Flat 5-branch if/elif chain must not trigger nesting error")

    def test_problem2_2_flat_elif_chain_10_branches(self):
        code = "\n".join(["def handle(x):", "    if x == 0: pass"] + [f"    elif x == {i}: pass" for i in range(1, 10)])
        issues = linter_checker.check_nesting_depth("test.py", code, "python", 4)
        self.assertEqual(
            len(issues),
            0,
            "Flat 10-branch if/elif chain must not trigger nesting error",
        )

    def test_problem2_3_nested_if_inside_elif_correct_depth(self):
        code = """
def process(x, y):
    if x == 1:
        pass
    elif x == 2:
        if y == 1:
            pass
"""
        issues = linter_checker.check_nesting_depth("test.py", code, "python", 4)
        self.assertEqual(len(issues), 0)

    def test_problem2_4_elif_inside_for_loop(self):
        code = """
def run(items):
    for item in items:
        if item == 1:
            pass
        elif item == 2:
            pass
        elif item == 3:
            pass
"""
        issues = linter_checker.check_nesting_depth("test.py", code, "python", 4)
        self.assertEqual(len(issues), 0)

    def test_problem2_5_async_for_with_elif_chain(self):
        code = """
async def run_async(stream):
    async for item in stream:
        if item == 'a':
            pass
        elif item == 'b':
            pass
"""
        issues = linter_checker.check_nesting_depth("test.py", code, "python", 4)
        self.assertEqual(len(issues), 0)

    def test_problem3_1_default_list_arg_with_commas(self):
        code = "def f(a=[1, 2, 3, 4], b=2):\n    pass"
        lengths = linter_checker.python_function_lengths(code)
        self.assertEqual(lengths[0][3], 2)

    def test_problem3_2_default_string_arg_with_commas(self):
        code = 'def f(msg="a, b, c, d", count=1):\n    pass'
        lengths = linter_checker.python_function_lengths(code)
        self.assertEqual(lengths[0][3], 2)

    def test_problem3_3_default_dict_arg_with_commas(self):
        code = 'def f(config={"a": 1, "b": 2}, mode="fast"):\n    pass'
        lengths = linter_checker.python_function_lengths(code)
        self.assertEqual(lengths[0][3], 2)

    def test_problem3_4_closure_parameter_in_swift(self):
        swift_code = "func exec(action: (Int, String) -> Void, x: Int) {\n    print(x)\n}"
        lengths = linter_checker.brace_function_lengths(swift_code, "swift")
        self.assertEqual(lengths[0][3], 2)

    def test_problem3_5_generic_dictionary_parameter_csharp(self):
        cs_code = "void Process(Dictionary<string, List<int>> map, int timeout) {}"
        lengths = linter_checker.brace_function_lengths(cs_code, "csharp")
        self.assertEqual(lengths[0][3], 2)

    def test_problem4_1_swift_multiline_default_param(self):
        swift_code = "func view(\n    width: Double = 1.0,\n    height: Double = 2.0\n) {\n    let a = 1\n}"
        lengths = linter_checker.brace_function_lengths(swift_code, "swift")
        self.assertEqual(lengths[0][0], "view")
        self.assertEqual(lengths[0][2], 6)

    def test_problem4_2_ts_multiline_default_param(self):
        ts_code = "function render(\n    x: number = 0,\n    y: number = 0\n) {\n    const a = 1;\n}"
        lengths = linter_checker.brace_function_lengths(ts_code, "typescript")
        self.assertEqual(lengths[0][0], "render")
        self.assertEqual(lengths[0][2], 6)

    def test_problem4_3_python_multiline_default_param(self):
        code = "def build(\n    a: int = 1,\n    b: int = 2\n):\n    pass"
        lengths = linter_checker.python_function_lengths(code)
        self.assertEqual(lengths[0][0], "build")

    def test_problem4_4_csharp_multiline_default_param(self):
        cs_code = "void Init(\n    int width = 800,\n    int height = 600\n) {\n    int x = 0;\n}"
        lengths = linter_checker.brace_function_lengths(cs_code, "csharp")
        self.assertEqual(lengths[0][0], "Init")

    def test_problem4_5_kotlin_multiline_default_param(self):
        kt_code = 'fun create(\n    name: String = "default",\n    count: Int = 0\n) {\n    val a = 1\n}'
        lengths = linter_checker.brace_function_lengths(kt_code, "kotlin")
        self.assertEqual(lengths[0][0], "create")

    def test_problem5_1_leading_dot_slash_ignore(self):
        self.assertTrue(linter_checker.should_ignore("build/out.js", ["./build"]))

    def test_problem5_2_leading_dot_backslash_ignore(self):
        self.assertTrue(linter_checker.should_ignore("dist/bundle.js", [".\\dist"]))

    def test_problem5_3_config_merge_preserves_default_git(self):
        config = linter_checker.load_config(Path("/nonexistent_config.json"))
        self.assertIn(".git", config["ignore"])

    def test_problem5_4_config_merge_preserves_node_modules(self):
        config = linter_checker.load_config(Path("/nonexistent_config.json"))
        self.assertIn("node_modules", config["ignore"])

    def test_problem5_5_nested_glob_ignore_pattern(self):
        self.assertTrue(linter_checker.should_ignore("src/vendor/lib.js", ["**/vendor/*"]))

    def test_problem6_1_csharp_block_comment_over_limit(self):
        code = "int seed = 0;\n/*\n" + "\n".join([f" * Line {i}" for i in range(7)]) + "\n */\nvoid foo() {}"
        issues = linter_checker.check_comment_blocks("test.cs", code, "csharp", 5)
        self.assertGreater(len(issues), 0)

    def test_problem6_2_java_block_comment_under_limit(self):
        code = "/*\n * Line 1\n * Line 2\n */\nvoid foo() {}"
        issues = linter_checker.check_comment_blocks("test.java", code, "java", 5)
        self.assertEqual(len(issues), 0)

    def test_problem6_3_ts_block_comment_over_limit(self):
        code = "const seed = 0;\n/*\n" + "\n".join([f" * Line {i}" for i in range(8)]) + "\n */\nfunction foo() {}"
        issues = linter_checker.check_comment_blocks("test.ts", code, "typescript", 5)
        self.assertGreater(len(issues), 0)

    def test_problem6_4_swift_block_comment_interspersed(self):
        code = "/* comment 1 */\n\n/* comment 2 */\nfunc foo() {}"
        issues = linter_checker.check_comment_blocks("test.swift", code, "swift", 5)
        self.assertEqual(len(issues), 0)

    def test_problem6_5_php_block_comment_over_limit(self):
        code = "$seed = 0;\n/*\n" + "\n".join([f" * Line {i}" for i in range(7)]) + "\n */\nfunction foo() {}"
        issues = linter_checker.check_comment_blocks("test.php", code, "php", 5)
        self.assertGreater(len(issues), 0)

    def test_problem7_1_python_nested_class_in_class(self):
        code = "class Outer:\n    class Inner:\n        pass"
        issues = linter_checker.check_types_per_file("test.py", code, "python", 1)
        self.assertEqual(len(issues), 0)

    def test_problem7_2_python_class_in_function(self):
        code = "def foo():\n    class Dynamic:\n        pass"
        issues = linter_checker.check_types_per_file("test.py", code, "python", 0)
        self.assertEqual(len(issues), 0)

    def test_problem7_3_python_class_in_if_block(self):
        code = "if True:\n    class Conditional:\n        pass"
        issues = linter_checker.check_types_per_file("test.py", code, "python", 0)
        self.assertEqual(len(issues), 0)

    def test_problem7_4_python_multiple_nested_classes_exceeds(self):
        code = "class A:\n    class B:\n        pass\nclass C:\n    pass"
        self.assertEqual(len(linter_checker.check_types_per_file("test.py", code, "python", 2)), 0)
        issues = linter_checker.check_types_per_file("test.py", code, "python", 1)
        self.assertEqual(len(issues), 1)
        self.assertIn("A, C", issues[0].message)
        self.assertNotIn("B", issues[0].message)

    def test_problem7_5_python_top_level_and_nested_classes(self):
        code = "class Base:\n    pass\nclass Derived(Base):\n    class Config:\n        pass"
        issues = linter_checker.check_types_per_file("test.py", code, "python", 1)
        self.assertEqual(len(issues), 1)
        self.assertIn("File defines 2 types (Base, Derived)", issues[0].message)

    def test_problem8_1_csharp_method_call_at_line_start(self):
        cs_code = "void Main() {\n    CalculateTotal(1, 2);\n}"
        lengths = linter_checker.brace_function_lengths(cs_code, "csharp")
        names = [item[0] for item in lengths]
        self.assertNotIn("CalculateTotal", names)

    def test_problem8_2_java_method_call_at_line_start(self):
        java_code = 'void main() {\n    System.out.println("msg");\n}'
        lengths = linter_checker.brace_function_lengths(java_code, "java")
        names = [item[0] for item in lengths]
        self.assertNotIn("System", names)


if __name__ == "__main__":
    unittest.main()
