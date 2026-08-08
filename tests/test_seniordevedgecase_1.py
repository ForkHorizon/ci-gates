import importlib.util
import sys
import unittest
from pathlib import Path

# Add scripts directory to path to import code-linter.py
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

spec = importlib.util.spec_from_file_location("linter_checker", SCRIPTS_DIR / "code-linter.py")
linter_checker = importlib.util.module_from_spec(spec)
sys.modules["linter_checker"] = linter_checker
spec.loader.exec_module(linter_checker)


def scanned_line(code, language):
    """Code left on a single line once comments and string bodies are removed."""
    return linter_checker.scan_c_style_lines(code, language)[0][1]


class SeniorDevEdgeCaseTestsPart1(unittest.TestCase):
    def test_url_in_string_literal_not_truncated_by_comment_stripper(self):
        code = 'let url = "https://example.com/api"; let x = 1;'
        line = scanned_line(code, "swift")
        self.assertIn(
            "x",
            line,
            "URL slashes '//' inside string literal must not truncate the line",
        )

    def test_python_elif_chain_not_flagged_as_deep_nesting(self):
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
        self.assertEqual(
            len(issues),
            0,
            "Flat if/elif/elif/elif/elif chain should NOT be flagged as deep nesting",
        )

    def test_multiline_signature_with_default_equals_value(self):
        swift_code = """
func createView(
    width: Double = 100.0,
    height: Double = 200.0
) {
    let a = 1
}
"""
        lengths = linter_checker.brace_function_lengths(swift_code, "swift")
        self.assertEqual(len(lengths), 1)
        self.assertEqual(lengths[0][0], "createView")
        self.assertEqual(
            lengths[0][2],
            6,
            "Multi-line signature with '=' must not treat function as a 1-line expression",
        )

    def test_closure_or_tuple_first_parameter_in_swift(self):
        swift_code = """
func execute(action: (Int, String) -> Void, count: Int) {
    print(count)
}
"""
        lengths = linter_checker.brace_function_lengths(swift_code, "swift")
        self.assertEqual(len(lengths), 1)
        self.assertEqual(lengths[0][0], "execute")
        self.assertEqual(
            lengths[0][3],
            2,
            "Should count 2 parameters for execute, not parse closure tuple",
        )

    def test_default_array_parameter_comma_counting(self):
        code = """
def process(items=[1, 2, 3, 4, 5, 6], factor=2):
    pass
"""
        lengths = linter_checker.python_function_lengths(code)
        self.assertEqual(len(lengths), 1)
        self.assertEqual(
            lengths[0][3],
            2,
            "Default list [1,2,3,4,5,6] commas must not be counted as function parameters",
        )

    def test_default_string_parameter_with_commas(self):
        code = """
def format_text(template="hello, beautiful, world", flag=True):
    pass
"""
        lengths = linter_checker.python_function_lengths(code)
        self.assertEqual(len(lengths), 1)
        self.assertEqual(
            lengths[0][3],
            2,
            "Commas inside string default arguments must not increase parameter count",
        )

    def test_multiline_string_literals_in_js_template_strings(self):
        js_code = """
const sql = `
  SELECT * FROM users
  WHERE class = 'admin'
  /* comment inside string */
`;
function realFunc() {}
"""
        lengths = linter_checker.brace_function_lengths(js_code, "javascript")
        self.assertEqual(len(lengths), 1)
        self.assertEqual(lengths[0][0], "realFunc")

    def test_rust_lifetime_annotation_not_treated_as_single_quote_string(self):
        rust_code = """
fn process<'a, 'b>(x: &'a str, y: &'b str) {
    let z = { 1 };
}
"""
        lengths = linter_checker.brace_function_lengths(rust_code, "rust")
        self.assertEqual(len(lengths), 1)
        self.assertEqual(lengths[0][0], "process")

    def test_nested_block_comments_in_swift(self):
        swift_code = """
/* outer comment
   /* nested inner comment */
   still inside outer comment */
func activeFunc() {
    print(1)
}
"""
        lengths = linter_checker.brace_function_lengths(swift_code, "swift")
        self.assertEqual(len(lengths), 1)
        self.assertEqual(lengths[0][0], "activeFunc")

    def test_csharp_method_invocation_at_line_start_not_detected_as_function(self):
        cs_code = """
void Main() {
    CalculateTotal(1, 2, 3);
    LogMessage("done");
}
"""
        lengths = linter_checker.brace_function_lengths(cs_code, "csharp")
        names = [item[0] for item in lengths]
        self.assertNotIn(
            "CalculateTotal",
            names,
            "Method invocation at line start must not be detected as function",
        )

    def test_ignore_pattern_with_leading_dot_slash(self):
        patterns = ["./DerivedData", "./build"]
        self.assertTrue(linter_checker.should_ignore("DerivedData/Build/Cache.swift", patterns))

    def test_block_comments_in_c_style_languages_count_towards_comment_limit(self):
        code = """
/*
 * Line 1
 * Line 2
 * Line 3
 * Line 4
 * Line 5
 * Line 6
 */
def foo():
    pass
"""
        issues = linter_checker.check_comment_blocks("test.cs", code, "csharp", 5)
        self.assertGreater(
            len(issues),
            0,
            "Multi-line block comment exceeding line limit must produce issue",
        )

    def test_swift_string_interpolation_with_braces(self):
        swift_code = """
func format() {
    let s = "Items: \\(items.map { $0 * 2 })"
}
"""
        lengths = linter_checker.brace_function_lengths(swift_code, "swift")
        self.assertEqual(len(lengths), 1)
        self.assertEqual(lengths[0][0], "format")

    def test_python_nested_class_counted_in_types_per_file(self):
        code = """
class Outer:
    class Inner:
        pass
class Third:
    pass
"""
        issues = linter_checker.check_types_per_file("test.py", code, "python", 2)
        self.assertEqual(len(issues), 0, "Nested Python classes do not count towards types_per_file")

    def test_csharp_where_generic_constraint_class_not_type_definition(self):
        cs_code = """
public class Service {
    public void Save<T>(T item) where T : class {
    }
}
"""
        issues = linter_checker.check_types_per_file("Service.cs", cs_code, "csharp", 2)
        self.assertEqual(
            len(issues),
            0,
            "C# 'where T : class' constraint must not be counted as type definition",
        )

    def test_allman_style_braces_nesting_depth_consistency(self):
        allman = """
void Foo()
{
    if (a)
    {
        if (b)
        {
            if (c)
            {
                if (d)
                {
                    if (e)
                    {
                        DoWork();
                    }
                }
            }
        }
    }
}
"""
        issues = linter_checker.check_nesting_depth("Foo.cs", allman, "csharp", 4)
        self.assertGreater(len(issues), 0, "Allman style braces exceeding depth limit must be flagged")


if __name__ == "__main__":
    unittest.main()
