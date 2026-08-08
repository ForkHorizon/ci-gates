import importlib.util
import sys
import unittest
from pathlib import Path

# Add scripts directory to path to import code-linter.py
SCRIPTS_DIR = Path(__file__).resolve().parents[4] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

spec = importlib.util.spec_from_file_location("linter_checker", SCRIPTS_DIR / "code-linter.py")
linter_checker = importlib.util.module_from_spec(spec)
sys.modules["linter_checker"] = linter_checker
spec.loader.exec_module(linter_checker)


def scanned_line(code, language):
    """Code left on a single line once comments and string bodies are removed."""
    return linter_checker.scan_c_style_lines(code, language)[0][1]


class LinterCheckerRulesTestsPart1(unittest.TestCase):
    def setUp(self):
        self.config = {
            "max_file_lines": 300,
            "max_function_lines": 50,
            "max_nesting_depth": 4,
            "max_parameters": 5,
            "max_comment_lines": 5,
            "max_types_per_file": 2,
        }

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
        _name, _start, _length, pcount = lengths[0]
        self.assertEqual(pcount, 5)
        self.assertLessEqual(pcount, 5, "Should pass when parameters <= 5")

    def test_max_parameters_fail(self):
        code = """
def calculate_too_many(a, b, c, d, e, f):
    return a + b + c + d + e + f
"""
        lengths = linter_checker.python_function_lengths(code)
        self.assertEqual(len(lengths), 1)
        _name, _start, _length, pcount = lengths[0]
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
        _name, _start, _length, pcount = lengths[0]
        self.assertEqual(
            pcount,
            6,
            "Should accurately count 6 parameters across multi-line signature",
        )

    def test_escaped_quotes_and_braces_in_strings(self):
        swift_code = """
let json = "{\\\"key\\\": \\\"{ val }\\\"; func fake() {}\"}"
func realFunc() {
    let x = 1
}
"""
        lengths = linter_checker.brace_function_lengths(swift_code, "swift")
        self.assertEqual(len(lengths), 1)
        self.assertEqual(
            lengths[0][0],
            "realFunc",
            "Should ignore fake functions and braces inside strings",
        )

    def test_python_async_decorators_varargs_kwargs(self):
        code = """
@decorator(a=1, b=2)
async def complex_fn(a, b, *args, c=1, d=2, **kwargs):
    pass
"""
        lengths = linter_checker.python_function_lengths(code)
        self.assertEqual(len(lengths), 1)
        self.assertEqual(
            lengths[0][3],
            6,
            "Should count positional, kwonly, varargs and kwargs (total 6)",
        )

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
        self.assertEqual(
            len(issues),
            0,
            "Docstrings and shebangs should not count as consecutive # comment blocks",
        )

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

    def test_multiple_nested_and_inner_types(self):
        swift_code = """
class Outer {
    class Inner1 {}
    struct Inner2 {}
    enum Inner3 {}
}
"""
        issues = linter_checker.check_types_per_file("Types.swift", swift_code, "swift", 1)
        self.assertEqual(
            len(issues),
            0,
            "Types nested inside Outer are one unit of reading, not four",
        )

    def test_swift_backticked_identifiers_and_initializers(self):
        swift_code = """
func `default`(a: Int, b: Int) {}
init(a: Int, b: Int, c: Int, d: Int, e: Int, f: Int) {}
"""
        lengths = linter_checker.brace_function_lengths(swift_code, "swift")
        names = [item[0] for item in lengths]
        self.assertIn("default", names)
        self.assertIn("init", names)

    def test_python_type_hints_with_nested_subscription_commas(self):
        code = """
from typing import Callable, Dict, Any

def handler(cb: Callable[[int, str, Dict[str, Any]], bool], data: dict):
    pass
"""
        lengths = linter_checker.python_function_lengths(code)
        self.assertEqual(len(lengths), 1)
        self.assertEqual(
            lengths[0][3],
            2,
            "Should count 2 params despite commas in Callable[[...]] type hint",
        )


if __name__ == "__main__":
    unittest.main()
