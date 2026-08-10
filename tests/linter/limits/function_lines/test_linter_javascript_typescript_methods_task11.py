import importlib.util
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[4] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

spec = importlib.util.spec_from_file_location("javascript_typescript_linter", SCRIPTS_DIR / "code-linter.py")
linter = importlib.util.module_from_spec(spec)
sys.modules["javascript_typescript_linter"] = linter
spec.loader.exec_module(linter)


LIMITS = {
    "max_file_lines": 100,
    "max_function_lines": 3,
    "max_nesting_depth": 1,
    "max_parameters": 2,
    "max_comment_lines": 20,
    "max_doc_comment_lines": 20,
    "max_types_per_file": 20,
}


class ModernJavaScriptTypeScriptMethodTests(unittest.TestCase):
    def lengths(self, source, language="javascript"):
        return linter.brace_function_lengths(source, language)

    def issues(self, filename, source, limits=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / filename
            path.write_text(source, encoding="utf-8")
            return linter.check_paths(root, [path], limits or LIMITS)

    def test_private_instance_method_is_detected_and_named(self):
        source = "class Worker {\n  #run(a, b) {\n    work(a, b);\n  }\n}\n"
        self.assertEqual(self.lengths(source), [("#run", 2, 3, 2)])

    def test_private_static_async_method_is_detected(self):
        source = "class Worker {\n  static async #load(a, b) {\n    return fetch(a, b);\n  }\n}\n"
        self.assertEqual(self.lengths(source), [("#load", 2, 3, 2)])

    def test_private_generator_and_async_generator_methods_are_detected(self):
        source = """class Worker {
  *#values(a, b) {
    yield a + b;
  }
  async *#stream(a, b) {
    yield await read(a, b);
  }
}
"""
        self.assertEqual(
            self.lengths(source),
            [("#values", 2, 3, 2), ("#stream", 5, 3, 2)],
        )

    def test_typescript_access_modifiers_and_async_static_combinations_are_detected(
        self,
    ):
        source = """class Service {
  public run(a, b) {
    return a + b;
  }
  private async load(a, b) {
    return await fetch(a, b);
  }
  protected static save(a, b) {
    persist(a, b);
  }
}
"""
        self.assertEqual(
            self.lengths(source, "typescript"),
            [("run", 2, 3, 2), ("load", 5, 3, 2), ("save", 8, 3, 2)],
        )

    def test_abstract_and_declare_typescript_method_signatures_are_measured(self):
        source = """abstract class Service {
  abstract public run(a, b): void;
}
declare class External {
  private load(a, b): Promise<void>;
}
"""
        self.assertEqual(
            self.lengths(source, "typescript"),
            [("run", 2, 1, 2), ("load", 5, 1, 2)],
        )

    def test_computed_method_name_is_detected_without_treating_expression_as_code(self):
        source = """class Service {
  [methodName](a, b) {
    return a + b;
  }
}
"""
        self.assertEqual(self.lengths(source, "javascript"), [("[methodName]", 2, 3, 2)])

    def test_private_field_arrow_function_is_detected(self):
        source = """class Worker {
  #run = (a, b) => {
    work(a, b);
  };
}
"""
        self.assertEqual(self.lengths(source), [("#run", 2, 3, 2)])

    def test_static_private_field_async_arrow_function_is_detected(self):
        source = """class Worker {
  static #load = async (a, b) => {
    return await fetch(a, b);
  };
}
"""
        self.assertEqual(self.lengths(source), [("#load", 2, 3, 2)])

    def test_multiline_private_method_parameters_and_next_line_brace_keep_metadata(
        self,
    ):
        source = """class Worker {
  private #run(
    first,
    second
  )
  {
    work(first, second);
  }
}
"""
        self.assertEqual(self.lengths(source, "typescript"), [("#run", 2, 7, 2)])

    def test_nested_classes_report_inner_private_method_with_deterministic_lines(self):
        source = """class Outer {
  class Inner {
    #run(a, b) {
      work(a, b);
    }
  }
}
"""
        self.assertEqual(self.lengths(source), [("#run", 3, 3, 2)])

    def test_comments_and_strings_containing_method_like_text_are_ignored(self):
        source = """// class Fake { #ignored(a, b) { nope(); } }
const text = "private #alsoIgnored(a, b) { nope(); }";
class Real {
  #run(a, b) {
    work(a, b);
  }
}
"""
        self.assertEqual(self.lengths(source), [("#run", 4, 3, 2)])

    def test_malformed_private_or_modifier_header_fails_closed(self):
        source = """class Broken {
  private #missing(a, b)
  cleanup: {
    work();
  }
  public run(a, b
  {
    work();
  }
}
"""
        self.assertEqual(self.lengths(source, "typescript"), [])

    def test_malformed_label_with_same_line_body_does_not_create_phantom_method(self):
        source = """class Broken {
  private #missing(a, b)
  cleanup: { work(); }
}
"""
        self.assertEqual(self.lengths(source, "typescript"), [])

    def test_private_method_function_and_parameter_limits_are_enforced(self):
        source = "class Worker {\n  #run(a, b, c) {\n    work();\n    work();\n    work();\n  }\n}\n"
        found = self.issues("worker.js", source)
        self.assertEqual({issue.kind for issue in found}, {"function_length", "max_parameters"})
        self.assertTrue(any("#run" in issue.message for issue in found))

    def test_private_method_nesting_limit_is_enforced_for_control_flow(self):
        source = """class Worker {
  #run(a, b) {
    if (ready) {
      if (complete) {
        work(a, b);
      }
    }
  }
}
"""
        found = self.issues("worker.js", source, {**LIMITS, "max_function_lines": 10})
        self.assertEqual([issue.kind for issue in found], ["nesting_depth"])
        self.assertEqual(found[0].line, 4)

    def test_public_cli_reports_modern_method_limit_violations(self):
        source = "class Worker {\n  private #run(a, b, c) {\n    work();\n    work();\n    work();\n  }\n}\n"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "worker.ts").write_text(source, encoding="utf-8")
            config = root / "config.json"
            config.write_text(
                '{"max_function_lines": 3, "max_parameters": 2, "max_nesting_depth": 4}',
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "code-linter.py"),
                    "--root",
                    str(root),
                    "--config",
                    str(config),
                    "--mode",
                    "all",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertNotEqual(result.returncode, 0)
        output = result.stdout + result.stderr
        self.assertIn("#run", output)
        self.assertIn("max_parameters", output)

    def test_node_accepts_valid_private_method_fixture_when_available(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node is unavailable")
        source = "class Worker { #run(a, b) { return a + b; } static async #load() {} }\n"
        with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as fixture:
            fixture.write(source)
            path = fixture.name
        try:
            result = subprocess.run([node, "--check", path], capture_output=True, text=True, check=False)
        finally:
            Path(path).unlink()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_ordinary_functions_object_methods_and_constructor_remain_measured(self):
        source = """function helper(a, b) {
  return a + b;
}
class Service {
  constructor(a, b) {
    this.value = a + b;
  }
}
const object = { run(a, b) {
  return a + b;
} };
"""
        self.assertEqual(
            self.lengths(source),
            [("helper", 1, 3, 2), ("constructor", 5, 3, 2), ("run", 9, 3, 2)],
        )

    def test_control_blocks_are_not_reported_as_methods(self):
        source = """if (ready) {
  work();
}
for (const item of items) {
  consume(item);
}
"""
        self.assertEqual(self.lengths(source), [])

    def test_template_interpolation_behavior_is_preserved(self):
        source = "const value = `${(a, b) => a + b}`;\n"
        self.assertEqual(self.lengths(source), [("value", 1, 1, 2)])

    def test_multiline_template_interpolation_private_method_text_is_literal(self):
        source = "const text = `private #notCode(a, b) {\n  nope();\n}`;\n"
        self.assertEqual(self.lengths(source), [])


if __name__ == "__main__":
    unittest.main()
