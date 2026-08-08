import sys
import unittest
from pathlib import Path

# Add scripts directory to path to import code-linter.py
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import importlib.util

spec = importlib.util.spec_from_file_location("linter_checker", SCRIPTS_DIR / "code-linter.py")
linter_checker = importlib.util.module_from_spec(spec)
sys.modules["linter_checker"] = linter_checker
spec.loader.exec_module(linter_checker)


def scanned_line(code, language):
    """Code left on a single line once comments and string bodies are removed."""
    return linter_checker.scan_c_style_lines(code, language)[0][1]


class LinterCheckerRulesTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "max_file_lines": 300,
            "max_function_lines": 50,
            "max_nesting_depth": 4,
            "max_parameters": 5,
            "max_comment_lines": 5,
            "max_types_per_file": 2,
        }

    # -------------------------------------------------------------------------
    # Basic Rule Tests
    # -------------------------------------------------------------------------
    def test_nesting_depth_pass(self):
        code = """
def valid_nesting():
    if True:
        for i in range(10):
            if i > 5:
                print(i)
"""
        issues = linter_checker.check_nesting_depth("test.py", code, "python", 4)
        self.assertEqual(len(issues), 0, "Should pass when nesting depth is <= 4")

    def test_nesting_depth_fail(self):
        code = """
def deep_nesting():
    if True:
        for i in range(10):
            if i > 5:
                while i < 8:
                    if i == 7:
                        print(i)
"""
        issues = linter_checker.check_nesting_depth("test.py", code, "python", 4)
        self.assertGreater(len(issues), 0, "Should fail when nesting depth exceeds 4")
        self.assertEqual(issues[0].kind, "nesting_depth")

    def test_max_parameters_pass(self):
        code = """
def calculate(a, b, c, d, e):
    return a + b + c + d + e
"""
        lengths = linter_checker.python_function_lengths(code)
        self.assertEqual(len(lengths), 1)
        name, start, length, pcount = lengths[0]
        self.assertEqual(pcount, 5)
        self.assertLessEqual(pcount, 5, "Should pass when parameters <= 5")

    def test_max_parameters_fail(self):
        code = """
def calculate_too_many(a, b, c, d, e, f):
    return a + b + c + d + e + f
"""
        lengths = linter_checker.python_function_lengths(code)
        self.assertEqual(len(lengths), 1)
        name, start, length, pcount = lengths[0]
        self.assertEqual(pcount, 6)
        self.assertGreater(pcount, 5, "Should fail when parameters > 5")

    def test_comment_block_pass(self):
        code = """
# Line 1 comment
# Line 2 comment
# Line 3 comment
def foo():
    pass
"""
        issues = linter_checker.check_comment_blocks("test.py", code, "python", 5)
        self.assertEqual(len(issues), 0, "Should pass when consecutive comments <= 5")

    def test_comment_block_fail(self):
        code = """
# Line 1 comment
# Line 2 comment
# Line 3 comment
# Line 4 comment
# Line 5 comment
# Line 6 comment
def foo():
    pass
"""
        issues = linter_checker.check_comment_blocks("test.py", code, "python", 5)
        self.assertEqual(len(issues), 1, "Should fail when consecutive comments > 5")
        self.assertEqual(issues[0].kind, "comment_block")

    def test_types_per_file_pass(self):
        code = """
class First:
    pass

class Second:
    pass
"""
        issues = linter_checker.check_types_per_file("test.py", code, "python", 2)
        self.assertEqual(len(issues), 0, "Should pass when types <= 2")

    def test_types_per_file_fail(self):
        code = """
class First:
    pass

class Second:
    pass

class Third:
    pass
"""
        issues = linter_checker.check_types_per_file("test.py", code, "python", 2)
        self.assertEqual(len(issues), 1, "Should fail when types > 2")
        self.assertEqual(issues[0].kind, "types_per_file")

    # -------------------------------------------------------------------------
    # 20 Advanced Edge-Case Tests
    # -------------------------------------------------------------------------

    # 1. Multi-line signatures with generics and constraints
    def test_multiline_generic_function_signature_parameters(self):
        swift_code = """
func process<T: Equatable, U: Collection>(
    a: T,
    b: U,
    c: [String: Any],
    d: (Int) -> Void,
    e: Double,
    f: String
) {
    print(a)
}
"""
        lengths = linter_checker.brace_function_lengths(swift_code, "swift")
        self.assertEqual(len(lengths), 1)
        name, start, length, pcount = lengths[0]
        self.assertEqual(pcount, 6, "Should accurately count 6 parameters across multi-line signature")

    # 2. Escaped quotes and braces inside string literals
    def test_escaped_quotes_and_braces_in_strings(self):
        swift_code = """
let json = "{\\\"key\\\": \\\"{ val }\\\"; func fake() {}\"}"
func realFunc() {
    let x = 1
}
"""
        lengths = linter_checker.brace_function_lengths(swift_code, "swift")
        self.assertEqual(len(lengths), 1)
        self.assertEqual(lengths[0][0], "realFunc", "Should ignore fake functions and braces inside strings")

    # 3. Python async decorators, varargs, and kwargs
    def test_python_async_decorators_varargs_kwargs(self):
        code = """
@decorator(a=1, b=2)
async def complex_fn(a, b, *args, c=1, d=2, **kwargs):
    pass
"""
        lengths = linter_checker.python_function_lengths(code)
        self.assertEqual(len(lengths), 1)
        self.assertEqual(lengths[0][3], 6, "Should count positional, kwonly, varargs and kwargs (total 6)")

    # 4. Shebangs, docstrings, and C-style block comments vs single line comments
    def test_comments_with_shebang_and_docstrings(self):
        code = """#!/usr/bin/env python3
\"\"\"
Multi-line docstring
line 2
line 3
line 4
line 5
line 6
\"\"\"
# comment 1
# comment 2
def foo():
    pass
"""
        issues = linter_checker.check_comment_blocks("test.py", code, "python", 5)
        self.assertEqual(len(issues), 0, "Docstrings and shebangs should not count as consecutive # comment blocks")

    # 5. Deeply nested control flow with ternaries
    def test_deep_nested_control_flow_with_ternaries(self):
        cs_code = """
void Test() {
    if (a ? b : c) {
        for (int i = 0; i < 10; i++) {
            if (i > 5) {
                while (true) {
                    if (ok) {
                        break;
                    }
                }
            }
        }
    }
}
"""
        issues = linter_checker.check_nesting_depth("Test.cs", cs_code, "csharp", 4)
        self.assertGreater(len(issues), 0, "Should flag nesting depth exceeding 4")

    # 6. Multiple nested and inner types
    def test_multiple_nested_and_inner_types(self):
        swift_code = """
class Outer {
    class Inner1 {}
    struct Inner2 {}
    enum Inner3 {}
}
"""
        issues = linter_checker.check_types_per_file("Types.swift", swift_code, "swift", 1)
        self.assertEqual(len(issues), 0, "Types nested inside Outer are one unit of reading, not four")

    # 7. Swift backticked identifiers and initializers
    def test_swift_backticked_identifiers_and_initializers(self):
        swift_code = """
func `default`(a: Int, b: Int) {}
init(a: Int, b: Int, c: Int, d: Int, e: Int, f: Int) {}
"""
        lengths = linter_checker.brace_function_lengths(swift_code, "swift")
        names = [item[0] for item in lengths]
        self.assertIn("default", names)
        self.assertIn("init", names)

    # 8. Python type hints with nested subscription commas
    def test_python_type_hints_with_nested_subscription_commas(self):
        code = """
from typing import Callable, Dict, Any

def handler(cb: Callable[[int, str, Dict[str, Any]], bool], data: dict):
    pass
"""
        lengths = linter_checker.python_function_lengths(code)
        self.assertEqual(len(lengths), 1)
        self.assertEqual(lengths[0][3], 2, "Should count 2 params despite commas in Callable[[...]] type hint")

    # 9. Go function signature with multiple return values
    def test_go_function_signature_with_multiple_return_values(self):
        go_code = """
func Compute(a, b, c int, d string, e float64, f bool) (res1 int, res2 string, err error) {
    return
}
"""
        lengths = linter_checker.brace_function_lengths(go_code, "go")
        self.assertEqual(len(lengths), 1)
        self.assertEqual(lengths[0][3], 6, "Should count 6 input parameters and ignore return parameter list")

    # 10. Comments interspersed with blank lines
    def test_comments_interspersed_with_blank_lines(self):
        code = """
# Line 1
# Line 2
# Line 3

# Line 4
# Line 5
# Line 6
"""
        issues = linter_checker.check_comment_blocks("test.py", code, "python", 5)
        self.assertEqual(len(issues), 0, "Blank line should reset consecutive comment line count")

    # 11. Switch case sibling nesting depth
    def test_switch_case_sibling_nesting_depth(self):
        swift_code = """
func check(val: Int) {
    switch val {
    case 1: print(1)
    case 2: print(2)
    case 3: print(3)
    case 4: print(4)
    case 5: print(5)
    default: break
    }
}
"""
        issues = linter_checker.check_nesting_depth("check.swift", swift_code, "swift", 4)
        self.assertEqual(len(issues), 0, "Sibling cases should not accumulate nesting depth")

    # 12. Rust impl blocks and trait definitions
    def test_rust_impl_blocks_and_trait_definitions(self):
        rust_code = """
struct MyStruct;
trait MyTrait {}
impl MyTrait for MyStruct {}
"""
        issues = linter_checker.check_types_per_file("lib.rs", rust_code, "rust", 2)
        self.assertEqual(len(issues), 0, "Should count struct and trait (2) and not count impl as type definition")

    # 13. C# attributes and generic return types
    def test_csharp_attributes_and_generic_return_types(self):
        cs_code = """
[HttpGet]
[ProducesResponseType(typeof(List<Item>), 200)]
public async Task<List<Item>> GetItems(int a, int b, int c, int d, int e, int f) {
    return null;
}
"""
        lengths = linter_checker.brace_function_lengths(cs_code, "csharp")
        self.assertEqual(len(lengths), 1)
        self.assertEqual(lengths[0][3], 6, "Attributes and generic return types should not disrupt parameter counting")

    # 14. Single line expression functions
    def test_single_line_expression_functions(self):
        kt_code = """fun add(a: Int, b: Int) = a + b"""
        lengths = linter_checker.brace_function_lengths(kt_code, "kotlin")
        self.assertEqual(len(lengths), 1)
        self.assertEqual(lengths[0][2], 1, "Single line function should be reported as length 1")

    # 15. Closures and lambdas inside functions
    def test_closures_and_lambdas_inside_functions(self):
        swift_code = """
func calculate() {
    let items = [1, 2, 3]
    items.map { x in x * 2 }
    items.filter { y in y > 1 }
}
"""
        lengths = linter_checker.brace_function_lengths(swift_code, "swift")
        self.assertEqual(len(lengths), 1)
        self.assertEqual(lengths[0][0], "calculate")

    # 16. Python 3.10+ match/case nesting
    def test_python_match_case_nesting(self):
        code = """
def parse(data):
    match data:
        case {"type": "A"}:
            if True:
                for x in range(5):
                    if x > 2:
                        while x < 4:
                            print(x)
"""
        issues = linter_checker.check_nesting_depth("parse.py", code, "python", 4)
        self.assertGreater(len(issues), 0, "Python match/case blocks should count toward nesting depth")

    # 17. Multi-line raw string literals
    def test_multiline_raw_string_literals(self):
        code = """
def test_fn():
    sql = \"\"\"
    class FakeClass:
        def fake_method():
            pass
    # comment 1
    # comment 2
    # comment 3
    # comment 4
    # comment 5
    # comment 6
    \"\"\"
"""
        issues = linter_checker.check_types_per_file("test.py", code, "python", 2)
        self.assertEqual(len(issues), 0, "Class inside string literal should not be counted as top-level type")

    # 18. Language overrides config
    def test_language_overrides_config(self):
        config = {
            "max_file_lines": 300,
            "max_function_lines": 50,
            "language_overrides": {
                "swift": {"max_function_lines": 10}
            }
        }
        swift_limits = linter_checker.limits_for_language(config, "swift")
        py_limits = linter_checker.limits_for_language(config, "python")
        self.assertEqual(swift_limits["max_function_lines"], 10)
        self.assertEqual(py_limits["max_function_lines"], 50)

    # 19. Glob pattern ignore matcher
    def test_glob_pattern_ignore_matcher(self):
        ignore_patterns = ["DerivedData", "*.gen.swift", "**/vendor/*"]
        self.assertTrue(linter_checker.should_ignore("App/DerivedData/Build/Cache.swift", ignore_patterns))
        self.assertTrue(linter_checker.should_ignore("App/Sources/Model.gen.swift", ignore_patterns))
        self.assertFalse(linter_checker.should_ignore("App/Sources/Model.swift", ignore_patterns))

    # 20. Comprehensive full-file stress test with all six rules combined
    def test_full_file_all_six_rules_stress_test(self):
        # Synthetic file violating max_comment_lines, max_types_per_file, max_parameters, nesting_depth
        python_code = """
# Comment 1
# Comment 2
# Comment 3
# Comment 4
# Comment 5
# Comment 6

class Type1:
    pass

class Type2:
    pass

class Type3:
    def overloaded_method(p1, p2, p3, p4, p5, p6):
        if True:
            for i in range(1):
                if i == 0:
                    while i < 1:
                        if i == 0:
                            print(i)
"""
        config = {
            "max_file_lines": 10,
            "max_function_lines": 5,
            "max_nesting_depth": 4,
            "max_parameters": 5,
            "max_comment_lines": 5,
            "max_types_per_file": 2,
        }
        # Mock Path and check_paths
        from unittest.mock import MagicMock
        mock_path = MagicMock()
        mock_path.suffix = ".py"
        mock_path.read_text.return_value = python_code
        mock_path.resolve.return_value = Path("/tmp/StressTest.py")

        mock_root = Path("/tmp")
        issues = linter_checker.check_paths(mock_root, [mock_path], config)

        issue_kinds = {issue.kind for issue in issues}
        self.assertIn("file_length", issue_kinds)
        self.assertIn("function_length", issue_kinds)
        self.assertIn("max_parameters", issue_kinds)
        self.assertIn("nesting_depth", issue_kinds)
        self.assertIn("comment_block", issue_kinds)
        self.assertIn("types_per_file", issue_kinds)


class SeniorDevEdgeCaseTests(unittest.TestCase):
    # 21. URL in string literal destroyed by comment stripper
    def test_url_in_string_literal_not_truncated_by_comment_stripper(self):
        code = 'let url = "https://example.com/api"; let x = 1;'
        line = scanned_line(code, "swift")
        self.assertIn("x", line, "URL slashes '//' inside string literal must not truncate the line")

    # 22. Python flat elif chain false positive in nesting depth
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
        self.assertEqual(len(issues), 0, "Flat if/elif/elif/elif/elif chain should NOT be flagged as deep nesting")

    # 23. Multi-line signature with default parameter '=' cleared prematurely
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
        self.assertEqual(lengths[0][2], 6, "Multi-line signature with '=' must not treat function as a 1-line expression")

    # 24. Closure parameter with tuple in signature
    def test_closure_or_tuple_first_parameter_in_swift(self):
        swift_code = """
func execute(action: (Int, String) -> Void, count: Int) {
    print(count)
}
"""
        lengths = linter_checker.brace_function_lengths(swift_code, "swift")
        self.assertEqual(len(lengths), 1)
        self.assertEqual(lengths[0][0], "execute")
        self.assertEqual(lengths[0][3], 2, "Should count 2 parameters for execute, not parse closure tuple")

    # 25. Default array parameter with internal commas
    def test_default_array_parameter_comma_counting(self):
        code = """
def process(items=[1, 2, 3, 4, 5, 6], factor=2):
    pass
"""
        lengths = linter_checker.python_function_lengths(code)
        self.assertEqual(len(lengths), 1)
        self.assertEqual(lengths[0][3], 2, "Default list [1,2,3,4,5,6] commas must not be counted as function parameters")

    # 26. Default string parameter containing commas
    def test_default_string_parameter_with_commas(self):
        code = """
def format_text(template="hello, beautiful, world", flag=True):
    pass
"""
        lengths = linter_checker.python_function_lengths(code)
        self.assertEqual(len(lengths), 1)
        self.assertEqual(lengths[0][3], 2, "Commas inside string default arguments must not increase parameter count")

    # 27. Multi-line string literals (JS template literal / Python docstring)
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

    # 28. Rust lifetime annotation misidentified as single-quoted string
    def test_rust_lifetime_annotation_not_treated_as_single_quote_string(self):
        rust_code = """
fn process<'a, 'b>(x: &'a str, y: &'b str) {
    let z = { 1 };
}
"""
        lengths = linter_checker.brace_function_lengths(rust_code, "rust")
        self.assertEqual(len(lengths), 1)
        self.assertEqual(lengths[0][0], "process")

    # 29. Nested block comments in Swift / Kotlin / Rust
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

    # 30. Method invocation at start of line misidentified as function declaration
    def test_csharp_method_invocation_at_line_start_not_detected_as_function(self):
        cs_code = """
void Main() {
    CalculateTotal(1, 2, 3);
    LogMessage("done");
}
"""
        lengths = linter_checker.brace_function_lengths(cs_code, "csharp")
        names = [item[0] for item in lengths]
        self.assertNotIn("CalculateTotal", names, "Method invocation at line start must not be detected as function")

    # 31. Ignore pattern with leading dot-slash
    def test_ignore_pattern_with_leading_dot_slash(self):
        patterns = ["./DerivedData", "./build"]
        self.assertTrue(linter_checker.should_ignore("DerivedData/Build/Cache.swift", patterns))

    # 32. Multi-line block comments count towards comment limit
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
        self.assertGreater(len(issues), 0, "Multi-line block comment exceeding line limit must produce issue")

    # 33. Swift string interpolation containing braces
    def test_swift_string_interpolation_with_braces(self):
        swift_code = """
func format() {
    let s = "Items: \\(items.map { $0 * 2 })"
}
"""
        lengths = linter_checker.brace_function_lengths(swift_code, "swift")
        self.assertEqual(len(lengths), 1)
        self.assertEqual(lengths[0][0], "format")

    # 34. Python nested class defined inside function or condition
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

    # 35. C# generic constraint 'where T : class' false positive
    def test_csharp_where_generic_constraint_class_not_type_definition(self):
        cs_code = """
public class Service {
    public void Save<T>(T item) where T : class {
    }
}
"""
        issues = linter_checker.check_types_per_file("Service.cs", cs_code, "csharp", 2)
        self.assertEqual(len(issues), 0, "C# 'where T : class' constraint must not be counted as type definition")

    # 36. Allman style vs K&R style brace nesting consistency
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

    # 37. Go multi-line receiver function definition
    def test_go_multiline_receiver_function(self):
        go_code = """
func (
    s *Server
) Process(a int) {
    return
}
"""
        lengths = linter_checker.brace_function_lengths(go_code, "go")
        self.assertEqual(len(lengths), 1)
        self.assertEqual(lengths[0][0], "Process", "Go multiline receiver function signature should be detected")

    # 38. Config ignore override preserves defaults or extends them cleanly
    def test_config_ignore_override_preserves_or_merges(self):
        config = linter_checker.load_config(Path("/nonexistent_config.json"))
        self.assertIn(".git", config["ignore"])
        self.assertIn("node_modules", config["ignore"])

    # 39. C++ / C# enum class type detection
    def test_cpp_enum_class_type_detection(self):
        cpp_code = """
enum class Status {
    OK,
    ERROR
};
class Handler {};
class Controller {};
"""
        issues = linter_checker.check_types_per_file("main.cpp", cpp_code, "csharp", 2)
        self.assertEqual(len(issues), 1, "enum class Status + 2 classes = 3 types, should exceed limit 2")

    # 40. GitHub Actions error message relative path formatting
    def test_github_path_formatting_for_error_annotation(self):
        rel_path = linter_checker.github_path(Path("src/app.py"))
        self.assertTrue(isinstance(rel_path, str) and len(rel_path) > 0)


class FixedProblemsComprehensiveTestSuite(unittest.TestCase):
    # -------------------------------------------------------------------------
    # Problem 1: URL & String Comment Stripping (5 tests)
    # -------------------------------------------------------------------------
    def test_problem1_1_https_url_in_string_not_truncated(self):
        code = 'let url = "https://domain.com/path"; let x = 1;'
        line = scanned_line(code, "swift")
        self.assertIn("x", line, "URL slashes '//' inside string literal must not truncate the line")

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

    # -------------------------------------------------------------------------
    # Problem 2: Python ast.If Nesting False Positives on elif Chains (5 tests)
    # -------------------------------------------------------------------------
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
        self.assertEqual(len(issues), 0, "Flat 10-branch if/elif chain must not trigger nesting error")

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

    # -------------------------------------------------------------------------
    # Problem 3: Parameter Counting for Lists, Strings & Generics (5 tests)
    # -------------------------------------------------------------------------
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

    # -------------------------------------------------------------------------
    # Problem 4: Multi-line Function Signatures with Default Values `=` (5 tests)
    # -------------------------------------------------------------------------
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
        kt_code = "fun create(\n    name: String = \"default\",\n    count: Int = 0\n) {\n    val a = 1\n}"
        lengths = linter_checker.brace_function_lengths(kt_code, "kotlin")
        self.assertEqual(lengths[0][0], "create")

    # -------------------------------------------------------------------------
    # Problem 5: Ignored Path Matching & Config Merging (5 tests)
    # -------------------------------------------------------------------------
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

    # -------------------------------------------------------------------------
    # Problem 6: Multi-line Block Comments /* ... */ (5 tests)
    # -------------------------------------------------------------------------
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

    # -------------------------------------------------------------------------
    # Problem 7: Python Nested Class Detection (5 tests)
    # -------------------------------------------------------------------------
    # types_per_file counts top-level types only: a helper nested inside the type
    # it serves is one unit of reading, not two.
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
        self.assertEqual(
            len(linter_checker.check_types_per_file("test.py", code, "python", 2)), 0
        )
        issues = linter_checker.check_types_per_file("test.py", code, "python", 1)
        self.assertEqual(len(issues), 1)
        self.assertIn("A, C", issues[0].message)
        self.assertNotIn("B", issues[0].message)

    def test_problem7_5_python_top_level_and_nested_classes(self):
        code = "class Base:\n    pass\nclass Derived(Base):\n    class Config:\n        pass"
        issues = linter_checker.check_types_per_file("test.py", code, "python", 1)
        self.assertEqual(len(issues), 1)
        self.assertIn("File defines 2 types (Base, Derived)", issues[0].message)

    # -------------------------------------------------------------------------
    # Problem 8: C#/Java Method Calls & Generic Constraints (5 tests)
    # -------------------------------------------------------------------------
    def test_problem8_1_csharp_method_call_at_line_start(self):
        cs_code = "void Main() {\n    CalculateTotal(1, 2);\n}"
        lengths = linter_checker.brace_function_lengths(cs_code, "csharp")
        names = [item[0] for item in lengths]
        self.assertNotIn("CalculateTotal", names)

    def test_problem8_2_java_method_call_at_line_start(self):
        java_code = "void main() {\n    System.out.println(\"msg\");\n}"
        lengths = linter_checker.brace_function_lengths(java_code, "java")
        names = [item[0] for item in lengths]
        self.assertNotIn("System", names)

    def test_problem8_3_csharp_where_class_constraint(self):
        cs_code = "public class Service {\n    public void Save<T>() where T : class {}\n}"
        issues = linter_checker.check_types_per_file("Service.cs", cs_code, "csharp", 2)
        self.assertEqual(len(issues), 0)

    def test_problem8_4_csharp_where_struct_constraint(self):
        cs_code = "public class Data {\n    public void Load<T>() where T : struct {}\n}"
        issues = linter_checker.check_types_per_file("Data.cs", cs_code, "csharp", 2)
        self.assertEqual(len(issues), 0)

    def test_problem8_5_csharp_where_new_constraint(self):
        cs_code = "public class Factory {\n    public void Create<T>() where T : new() {}\n}"
        issues = linter_checker.check_types_per_file("Factory.cs", cs_code, "csharp", 2)
        self.assertEqual(len(issues), 0)

    # -------------------------------------------------------------------------
    # Problem 9: Go Multi-Line Receiver Functions (5 tests)
    # -------------------------------------------------------------------------
    def test_problem9_1_go_multiline_receiver_basic(self):
        go_code = "func (\n    s *Server\n) Process(a int) {\n    return\n}"
        lengths = linter_checker.brace_function_lengths(go_code, "go")
        self.assertEqual(lengths[0][0], "Process")

    def test_problem9_2_go_pointer_receiver(self):
        go_code = "func (r *Runner) Run() {}"
        lengths = linter_checker.brace_function_lengths(go_code, "go")
        self.assertEqual(lengths[0][0], "Run")

    def test_problem9_3_go_value_receiver(self):
        go_code = "func (c Client) Connect() {}"
        lengths = linter_checker.brace_function_lengths(go_code, "go")
        self.assertEqual(lengths[0][0], "Connect")

    def test_problem9_4_go_multiline_signature(self):
        go_code = "func (s *Server) Handle(\n    req *Request,\n) {\n    return\n}"
        lengths = linter_checker.brace_function_lengths(go_code, "go")
        self.assertEqual(lengths[0][0], "Handle")

    def test_problem9_5_go_function_without_receiver(self):
        go_code = "func Standalone(x int) {}"
        lengths = linter_checker.brace_function_lengths(go_code, "go")
        self.assertEqual(lengths[0][0], "Standalone")

    # -------------------------------------------------------------------------
    # Problem 10: GitHub Actions Error Path Formatting (5 tests)
    # -------------------------------------------------------------------------
    def test_problem10_1_github_path_standard_file(self):
        rel = linter_checker.github_path(Path("src/main.py"))
        self.assertTrue(isinstance(rel, str) and len(rel) > 0)

    def test_problem10_2_github_path_nested_file(self):
        rel = linter_checker.github_path(Path("a/b/c/d.swift"))
        self.assertTrue(isinstance(rel, str) and len(rel) > 0)

    def test_problem10_3_escape_github_message_newlines(self):
        esc = linter_checker.escape_github_message("a\nb")
        self.assertEqual(esc, "a%0Ab")

    def test_problem10_4_escape_github_message_percent(self):
        esc = linter_checker.escape_github_message("100%")
        self.assertEqual(esc, "100%25")

    def test_problem10_5_escape_github_message_carriage(self):
        esc = linter_checker.escape_github_message("a\rb")
        self.assertEqual(esc, "a%0Db")


if __name__ == "__main__":
    unittest.main()


