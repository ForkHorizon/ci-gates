import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[4] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
spec = importlib.util.spec_from_file_location("javascript_edge_linter", SCRIPTS_DIR / "code-linter.py")
linter = importlib.util.module_from_spec(spec)
sys.modules["javascript_edge_linter"] = linter
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


class ModernJavaScriptEdgeCaseTests(unittest.TestCase):
    def lengths(self, source, language="typescript"):
        return linter.brace_function_lengths(source, language)

    def test_bare_private_arrow_field_counts_its_parameter(self):
        source = "class Worker {\n  #run = value => { return value; };\n}\n"
        self.assertEqual(self.lengths(source, "javascript"), [("#run", 2, 1, 1)])

    def test_bare_private_arrow_field_hits_parameter_limit(self):
        source = "class Worker {\n  #run = value => { return value; };\n}\n"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "worker.js"
            path.write_text(source, encoding="utf-8")
            issues = linter.check_paths(root, [path], {**LIMITS, "max_parameters": 0})
        self.assertEqual([issue.kind for issue in issues], ["max_parameters"])

    def test_typed_private_arrow_field_counts_parameters_before_return_annotation(self):
        source = """class Worker {
  #run = (first: number, second: number, third: number): void => {
    return;
  };
}
"""
        self.assertEqual(self.lengths(source), [("#run", 2, 3, 3)])

    def test_typescript_named_access_modified_arrow_field_is_named(self):
        source = "class Worker {\n  private run = (first, second) => first + second;\n}\n"
        self.assertEqual(self.lengths(source), [("run", 2, 1, 2)])

    def test_multiline_private_and_computed_method_headers_are_measured(self):
        source = """class Worker {
  #run
  (first, second) {
    return first + second;
  }
  [
    computedName
  ](first, second) {
    return first + second;
  }
}
"""
        self.assertEqual(
            linter.brace_function_lengths(source, "javascript"),
            [("#run", 2, 4, 2), ("[computedName]", 6, 5, 2)],
        )

    def test_method_body_brace_can_follow_a_multiline_name_and_parameter_list(self):
        source = """class Worker {
  #run
  (first, second)
  {
    return first + second;
  }
}
"""
        self.assertEqual(
            linter.brace_function_lengths(source, "javascript"),
            [("#run", 2, 5, 2)],
        )

    def test_interface_and_declare_class_methods_are_measured(self):
        source = """interface Contract {
  run(first, second): void;
}
declare class External {
  load(first, second): Promise<void>;
}
"""
        self.assertEqual(self.lengths(source), [("run", 2, 1, 2), ("load", 5, 1, 2)])

    def test_multiline_parameter_object_braces_do_not_drop_the_method(self):
        source = """class Worker {
  #run(
    options = {
      enabled: true
    }
  ) {
    return options.enabled;
  }
}
"""
        self.assertEqual(self.lengths(source, "javascript"), [("#run", 2, 7, 1)])

    def test_same_line_private_method_after_class_brace_is_measured(self):
        source = "class Worker { #run(first, second, third) { work(); } }\n"
        self.assertEqual(self.lengths(source, "javascript"), [("#run", 1, 1, 3)])

    def test_same_line_interface_and_ambient_methods_are_measured(self):
        source = (
            "interface Contract { run(first, second): void; }\ndeclare class External { load(first, second): void; }\n"
        )
        self.assertEqual(self.lengths(source), [("run", 1, 1, 2), ("load", 2, 1, 2)])

    def test_split_brace_class_and_interface_methods_are_measured(self):
        source = """class Worker
{
  #run(first, second) { return first + second; }
}
interface Contract
{
  run(first, second);
}
"""
        self.assertEqual(self.lengths(source), [("#run", 3, 1, 2), ("run", 7, 1, 2)])

    def test_interface_overload_without_return_annotation_is_measured(self):
        source = """interface Contract {
  run(first, second);
}
"""
        self.assertEqual(self.lengths(source), [("run", 2, 1, 2)])

    def test_computed_method_expression_with_call_is_measured(self):
        source = "class Worker { [factory()](first, second, third) { return first; } }\n"
        self.assertEqual(self.lengths(source, "javascript"), [("[factory()]", 1, 1, 3)])

    def test_array_destructured_parameter_continuation_is_preserved(self):
        source = """class Worker {
  run(
    [first, second],
    third
  ) {
    return first + third;
  }
}
"""
        self.assertEqual(self.lengths(source, "javascript"), [("run", 2, 6, 2)])

    def test_literal_method_names_are_measured(self):
        source = """class Worker {
  "run"(first, second, third) { return first; }
  1(a, b, c) { return a; }
}
"""
        self.assertEqual(
            self.lengths(source, "javascript"),
            [('"run"', 2, 1, 3), ("1", 3, 1, 3)],
        )

    def test_generic_method_constraint_with_object_type_is_measured(self):
        source = """class Worker {
  run<T extends { enabled: boolean }>(first, second) {
    return first;
  }
}
"""
        self.assertEqual(self.lengths(source), [("run", 2, 3, 2)])

    def test_private_arrow_field_object_return_annotation_is_measured(self):
        source = """class Worker {
  #run = (value: number, other: number): { result: number } => ({ result: value + other });
}
"""
        self.assertEqual(self.lengths(source), [("#run", 2, 1, 2)])

    def test_call_like_line_without_body_is_not_a_method(self):
        source = """class Worker {
  helper(first, second)
}
"""
        self.assertEqual(self.lengths(source), [])

    def test_malformed_pending_header_resets_before_valid_method(self):
        source = """class Worker {
  private #broken(first, second)
  run(first, second) { return first + second; }
}
"""
        self.assertEqual(self.lengths(source), [("run", 3, 1, 2)])


if __name__ == "__main__":
    unittest.main()
