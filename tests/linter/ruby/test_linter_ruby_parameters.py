import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

spec = importlib.util.spec_from_file_location("ruby_parameter_linter", SCRIPTS_DIR / "code-linter.py")
linter = importlib.util.module_from_spec(spec)
sys.modules["ruby_parameter_linter"] = linter
spec.loader.exec_module(linter)


class RubyMethodParameterTests(unittest.TestCase):
    def test_ordinary_method_counts_each_positional_parameter(self):
        source = "def f(a, b, c)\n  nil\nend\n"
        self.assertEqual(linter.ruby_function_lengths(source), [("f", 1, 3, 3)])

    def test_positional_defaults_with_nested_expression_commas_count_once_each(self):
        source = "def build(path, mode = :safe, retries = (1..3).to_a)\n  nil\nend\n"
        self.assertEqual(linter.ruby_function_lengths(source)[0][3], 3)

    def test_keyword_and_mixed_parameters_are_counted(self):
        source = "def configure(host, port: 443, ssl: true, timeout: 5)\n  nil\nend\n"
        self.assertEqual(linter.ruby_function_lengths(source), [("configure", 1, 3, 4)])

    def test_splat_double_splat_and_block_parameters_are_counted(self):
        source = "def dispatch(event, *args, **options, &block)\n  block.call(event, *args)\nend\n"
        self.assertEqual(linter.ruby_function_lengths(source)[0][3], 4)

    def test_nested_default_arrays_hashes_calls_and_lambda_commas_do_not_split(self):
        source = (
            "def query(filters = { ids: [1, 2], where: predicate(3, 4) }, "
            "callback = ->(value) { value })\n"
            "  callback.call(filters)\n"
            "end\n"
        )
        self.assertEqual(linter.ruby_function_lengths(source)[0][3], 2)

    def test_multiline_signature_preserves_method_identity_and_start_line(self):
        source = "def render(\n  template,\n  locals = { title: 'x,y' },\n  **options\n)\n  nil\nend\n"
        self.assertEqual(linter.ruby_function_lengths(source), [("render", 1, 7, 3)])

    def test_singleton_method_uses_its_full_name_and_counts_parameters(self):
        source = "def self.build(a, b, c)\n  nil\nend\n"
        self.assertEqual(linter.ruby_function_lengths(source), [("self.build", 1, 3, 3)])

    def test_zero_and_one_parameter_methods_remain_at_their_boundaries(self):
        source = "def empty()\nend\n\ndef one(value)\nend\n"
        self.assertEqual(
            linter.ruby_function_lengths(source),
            [("empty", 1, 2, 0), ("one", 4, 2, 1)],
        )

    def test_anonymous_rest_keywords_and_block_parameters_each_count(self):
        source = "def forward(*, **, &)\n  nil\nend\n"
        self.assertEqual(linter.ruby_function_lengths(source)[0][3], 3)

    def test_bare_parameter_list_is_counted_without_parentheses(self):
        source = "def collect first, second = [], third: nil\n  nil\nend\n"
        self.assertEqual(linter.ruby_function_lengths(source)[0][3], 3)

    def test_endless_method_without_parameters_is_not_inflated_by_call_arguments(self):
        source = "def self.value = compute(1, 2, 3)\n"
        self.assertEqual(linter.ruby_function_lengths(source), [("self.value", 1, 1, 0)])

    def test_method_body_calls_do_not_create_parameter_counts(self):
        source = "def marker\n  calculate(first, second, third)\nend\n"
        self.assertEqual(linter.ruby_function_lengths(source), [("marker", 1, 3, 0)])

    def test_public_cli_reports_the_exact_ruby_parameter_limit_violation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".code-linter.json").write_text(
                json.dumps({"max_parameters": 2, "include_extensions": [".rb"]}),
                encoding="utf-8",
            )
            (root / "fixture.rb").write_text("def f(first, second, third)\n  nil\nend\n", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / "code-linter.py"), "--root", str(root)],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn("file=fixture.rb,line=1,title=max_parameters", result.stdout)
        self.assertIn("Function 'f' has 3 parameters; limit is 2.", result.stdout)


if __name__ == "__main__":
    unittest.main()
