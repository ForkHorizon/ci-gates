import sys
import unittest
from pathlib import Path

# Add scripts directory to path to import linter.py
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import importlib.util

spec = importlib.util.spec_from_file_location("linter_checker", SCRIPTS_DIR / "linter.py")
linter_checker = importlib.util.module_from_spec(spec)
sys.modules["linter_checker"] = linter_checker
spec.loader.exec_module(linter_checker)


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
        issues = linter_checker.check_types_per_file("Types.swift", swift_code, "swift", 2)
        self.assertEqual(len(issues), 1, "Should count inner classes/structs/enums toward types per file")

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


if __name__ == "__main__":
    unittest.main()
