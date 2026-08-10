import importlib.util
import sys
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[4] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
spec = importlib.util.spec_from_file_location("javascript_adversarial_linter", SCRIPTS_DIR / "code-linter.py")
linter = importlib.util.module_from_spec(spec)
sys.modules["javascript_adversarial_linter"] = linter
spec.loader.exec_module(linter)


class ModernJavaScriptAdversarialTests(unittest.TestCase):
    def lengths(self, source, language="typescript"):
        return linter.brace_function_lengths(source, language)

    def test_same_line_class_field_object_does_not_shift_method_scope(self):
        source = """class Worker { field = {};
  #run(first, second, third) { return first; }
}
"""
        self.assertEqual(self.lengths(source, "javascript"), [("#run", 2, 1, 3)])

    def test_deeply_nested_computed_method_name_is_measured(self):
        source = "class Worker { [obj[a[b[c]]]](first, second, third) { return first; } }\n"
        self.assertEqual(self.lengths(source, "javascript"), [("[obj[a[b[c]]]]", 1, 1, 3)])

    def test_prefixed_bigint_method_names_are_measured(self):
        source = """class Worker {
  0x1n(first, second, third) { return first; }
  0b1n(first, second, third) { return first; }
  0o7n(first, second, third) { return first; }
}
"""
        self.assertEqual(
            self.lengths(source, "javascript"),
            [("0x1n", 2, 1, 3), ("0b1n", 3, 1, 3), ("0o7n", 4, 1, 3)],
        )

    def test_multiline_return_object_method_is_measured(self):
        source = """function outer() {
  return {
    run(first, second, third) { return first; }
  };
}
"""
        self.assertEqual(
            self.lengths(source, "javascript"),
            [("run", 3, 1, 3), ("outer", 1, 5, 0)],
        )

    def test_same_line_malformed_function_recovers_valid_function(self):
        source = "function broken(first, second, third); function valid(first, second, third) { return first; }\n"
        self.assertEqual(self.lengths(source, "javascript"), [("valid", 1, 1, 3)])

    def test_multiline_typed_arrow_field_with_object_return_is_measured(self):
        source = """class Worker {
  private run = (first: number, second: number, third: number):
    { value: number } => ({ value: first });
}
"""
        self.assertEqual(self.lengths(source), [("run", 2, 2, 3)])

    def test_multiple_same_line_private_methods_are_all_measured(self):
        source = "class Worker { #first(a, b, c) {} #second(a, b, c) {} }\n"
        self.assertEqual(
            self.lengths(source, "javascript"),
            [("#first", 1, 1, 3), ("#second", 1, 1, 3)],
        )

    def test_exported_object_computed_method_is_measured(self):
        source = "export default { [factory()](first, second, third) { return first; } };\n"
        self.assertEqual(self.lengths(source, "javascript"), [("[factory()]", 1, 1, 3)])

    def test_same_line_string_literal_method_is_measured(self):
        source = 'class Worker { "run"(first, second, third) {} }\n'
        self.assertEqual(self.lengths(source, "javascript"), [('"run"', 1, 1, 3)])

    def test_call_expression_object_method_is_measured(self):
        source = "consume({ run(first, second, third) { return first; } });\n"
        self.assertEqual(self.lengths(source, "javascript"), [("run", 1, 1, 3)])

    def test_same_line_arrow_field_before_method_is_measured(self):
        source = "class Worker { run = (first, second, third) => ({x: first}); next(first, second, third) {} }\n"
        self.assertEqual(
            self.lengths(source, "javascript"),
            [("run", 1, 1, 3), ("next", 1, 1, 3)],
        )

    def test_same_line_sibling_method_order_is_preserved(self):
        source = "class Worker { a(first, second, third) {} b(first, second, third) {} c(first, second, third) {} }\n"
        self.assertEqual(
            self.lengths(source, "javascript"),
            [("a", 1, 1, 3), ("b", 1, 1, 3), ("c", 1, 1, 3)],
        )


if __name__ == "__main__":
    unittest.main()
