import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[4] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
spec = importlib.util.spec_from_file_location("objective_c_mixed_linter", SCRIPTS_DIR / "code-linter.py")
linter = importlib.util.module_from_spec(spec)
sys.modules["objective_c_mixed_linter"] = linter
spec.loader.exec_module(linter)


LIMITS = {
    "max_file_lines": 100,
    "max_function_lines": 20,
    "max_nesting_depth": 10,
    "max_parameters": 2,
    "max_comment_lines": 20,
    "max_doc_comment_lines": 20,
    "max_types_per_file": 20,
}


class ObjectiveCMixedCRegressionTests(unittest.TestCase):
    def test_c_function_in_objective_c_file_keeps_parameter_enforcement(self):
        source = """int helper(int first, int second, int third) {
    return first + second + third;
}
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "Mixed.m"
            path.write_text(source, encoding="utf-8")
            issues = linter.check_paths(root, [path], LIMITS)
        self.assertEqual(
            [(issue.kind, issue.line) for issue in issues],
            [("max_parameters", 1)],
        )


if __name__ == "__main__":
    unittest.main()
