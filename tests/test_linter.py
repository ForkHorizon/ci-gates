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
    # 1. Nesting Depth Tests
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

    # -------------------------------------------------------------------------
    # 2. Max Parameters Tests
    # -------------------------------------------------------------------------
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

    def test_brace_max_parameters(self):
        swift_code = """
func process(a: Int, b: Int, c: Int, d: Int, e: Int, f: Int) {
    print(a)
}
"""
        lengths = linter_checker.brace_function_lengths(swift_code, "swift")
        self.assertEqual(len(lengths), 1)
        name, start, length, pcount = lengths[0]
        self.assertEqual(pcount, 6)

    # -------------------------------------------------------------------------
    # 3. Comment Lines Block Tests
    # -------------------------------------------------------------------------
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

    # -------------------------------------------------------------------------
    # 4. Types Per File Tests
    # -------------------------------------------------------------------------
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


if __name__ == "__main__":
    unittest.main()
