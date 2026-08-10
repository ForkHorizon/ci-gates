import importlib.util
import sys
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[4] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
spec = importlib.util.spec_from_file_location("javascript_review7_linter", SCRIPTS_DIR / "code-linter.py")
linter = importlib.util.module_from_spec(spec)
sys.modules["javascript_review7_linter"] = linter
spec.loader.exec_module(linter)


class ModernJavaScriptReview7Tests(unittest.TestCase):
    def lengths(self, source, language="typescript"):
        return linter.brace_function_lengths(source, language)

    def test_same_line_arrow_declarations_are_all_enforced(self):
        source = "const first = (a,b,c) => a; const second = (x,y,z) => x;\n"
        self.assertEqual(self.lengths(source, "javascript"), [("first", 1, 1, 3), ("second", 1, 1, 3)])

    def test_generic_constraint_braces_do_not_shorten_method_body(self):
        source = """class Worker {
  run<T extends {
    callback: (value: Value) => { result: Result }
  }>(first, second, third) {
    return first;
  }
}
"""
        self.assertEqual(self.lengths(source), [("run", 2, 5, 3)])

    def test_same_line_declaration_namespace_and_class_methods_are_all_measured(self):
        source = "declare namespace N { interface I { run(a,b,c); } } declare class E { load(a,b,c): Promise<void>; }\n"
        self.assertEqual(self.lengths(source), [("run", 1, 1, 3), ("load", 1, 1, 3)])

    def test_comparison_before_nested_block_counts_as_body(self):
        source = """function outer() {
  if (a < b) {
    work();
  }
}
"""
        self.assertEqual(self.lengths(source, "javascript"), [("outer", 1, 5, 0)])


if __name__ == "__main__":
    unittest.main()
