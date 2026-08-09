import importlib.util
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("php_closure_linter", SCRIPTS / "code-linter.py")
linter = importlib.util.module_from_spec(spec)
sys.modules["php_closure_linter"] = linter
spec.loader.exec_module(linter)


class PhpClosureStructuralTests(unittest.TestCase):
    def assert_valid_php(self, source):
        php = shutil.which("php")
        if not php:
            return
        with tempfile.NamedTemporaryFile("w", suffix=".php", encoding="utf-8") as fixture:
            fixture.write(source)
            fixture.flush()
            result = subprocess.run([php, "-l", fixture.name], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def assert_functions(self, source, expected):
        self.assert_valid_php(source)
        self.assertEqual(linter.function_lengths(source, "php"), expected)

    def test_assignment_anonymous_function_is_measured(self):
        self.assert_functions(
            "<?php\n$worker = function ($value) { return $value; };\n",
            [("<anonymous>", 2, 1, 1)],
        )

    def test_returned_anonymous_function_is_measured(self):
        self.assert_functions(
            "<?php\nfunction factory() {\n    return function ($value) { return $value; };\n}\n",
            [("<anonymous>", 3, 1, 1), ("factory", 2, 3, 0)],
        )

    def test_passed_as_argument_anonymous_function_is_measured(self):
        self.assert_functions(
            "<?php\narray_map(function ($value) { return $value; }, $values);\n",
            [("<anonymous>", 2, 1, 1)],
        )

    def test_use_capture_list_does_not_change_parameter_count(self):
        self.assert_functions(
            "<?php\n$worker = function ($value, &$other) use ($offset, &$factor) { return $value; };\n",
            [("<anonymous>", 2, 1, 2)],
        )

    def test_typed_default_parameters_are_counted(self):
        self.assert_functions(
            "<?php\n$worker = function (int $value = 1, ?string $label = null) { return $label; };\n",
            [("<anonymous>", 2, 1, 2)],
        )

    def test_variadic_and_reference_parameters_are_counted(self):
        self.assert_functions(
            "<?php\n$worker = function (&$first, ...$rest) { return $rest; };\n",
            [("<anonymous>", 2, 1, 2)],
        )

    def test_multiline_anonymous_signature_keeps_start_line_and_parameters(self):
        source = """<?php
$worker = function (
    int $first,
    string $second,
    ...$rest
) use ($captured) {
    return $first;
};
"""
        self.assert_functions(source, [("<anonymous>", 2, 7, 3)])

    def test_anonymous_body_brace_on_next_line_keeps_line_accounting(self):
        source = """<?php
$worker = function ($value)
{
    return $value;
};
"""
        self.assert_functions(source, [("<anonymous>", 2, 4, 1)])

    def test_assignment_arrow_closure_is_measured_as_one_line(self):
        self.assert_functions(
            "<?php\n$worker = fn(int $value, ...$rest) => $value;\n",
            [("<anonymous>", 2, 1, 2)],
        )

    def test_multiline_arrow_closure_keeps_start_line_and_parameters(self):
        source = """<?php
$worker = fn(
    int $value = 1,
    ?string $label = null,
    ...$rest
) => $value;
"""
        self.assert_functions(source, [("<anonymous>", 2, 1, 3)])

    def test_nested_anonymous_closures_are_reported_in_close_order(self):
        source = """<?php
$outer = function ($value) {
    $inner = fn($nested) => $nested;
    return function ($again) { return $again; };
};
"""
        self.assert_functions(
            source,
            [
                ("<anonymous>", 3, 1, 1),
                ("<anonymous>", 4, 1, 1),
                ("<anonymous>", 2, 4, 1),
            ],
        )

    def test_closure_inside_named_method_is_measured_separately(self):
        source = """<?php
class Worker {
    public function run($input) {
        return array_map(fn($value) => $value, $input);
    }
}
"""
        self.assert_functions(
            source,
            [("<anonymous>", 4, 1, 1), ("run", 3, 3, 1)],
        )

    def test_function_and_fn_tokens_inside_comments_and_strings_are_ignored(self):
        source = """<?php
$message = "function ($fake) { } fn($alsoFake) => 1";
// function ($commented) { } fn($commented) => 1
function real($value) { return $value; }
"""
        self.assert_functions(source, [("real", 4, 1, 1)])

    def test_real_named_function_remains_named(self):
        self.assert_functions(
            "<?php\nfunction named($first, $second) { return $first; }\n",
            [("named", 2, 1, 2)],
        )

    def test_incomplete_anonymous_function_does_not_emit_a_partial_function(self):
        source = "<?php\n$worker = function ($value)\n"
        self.assertEqual(linter.function_lengths(source, "php"), [])

    def test_fn_without_arrow_does_not_emit_a_call_as_a_closure(self):
        source = "<?php\n$result = fn($value);\n"
        self.assertEqual(linter.function_lengths(source, "php"), [])

    def test_line_accounting_survives_opaque_content_before_closure(self):
        source = """<?php
$literal = "function ($fake) { }";
/* fn($fake) => 1 */

$worker = fn($value) => $value;
"""
        self.assert_functions(source, [("<anonymous>", 5, 1, 1)])

    def test_function_length_limit_applies_to_anonymous_function(self):
        source = "<?php\n$worker = function ($value) {\n" + "    work();\n" * 3 + "}\n"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".code-linter.json").write_text(
                '{"include_extensions": [".php"], "max_function_lines": 3}\n',
                encoding="utf-8",
            )
            (root / "fixture.php").write_text(source, encoding="utf-8")
            issues = linter.check_paths(root, [root / "fixture.php"], linter.load_config(root / ".code-linter.json"))
        self.assertEqual([(issue.kind, issue.line) for issue in issues], [("function_length", 2)])

    def test_parameter_limit_applies_to_arrow_closure(self):
        source = "<?php\n$worker = fn($a, $b, $c, $d, $e, $f) => $a;\n"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".code-linter.json").write_text(
                '{"include_extensions": [".php"], "max_parameters": 5}\n',
                encoding="utf-8",
            )
            (root / "fixture.php").write_text(source, encoding="utf-8")
            issues = linter.check_paths(root, [root / "fixture.php"], linter.load_config(root / ".code-linter.json"))
        self.assertEqual([(issue.kind, issue.line) for issue in issues], [("max_parameters", 2)])

    def test_nesting_limit_applies_inside_anonymous_function(self):
        source = """<?php
$worker = function () {
    if ($one) {
        if ($two) {
            return 1;
        }
    }
};
"""
        issues = linter.check_nesting_depth("fixture.php", source, "php", 1)
        self.assertEqual([(issue.kind, issue.line) for issue in issues], [("nesting_depth", 4)])

    def test_heredoc_fake_closures_remain_opaque_before_real_closure(self):
        source = """<?php
$document = <<<TEXT
function ($fake) { if ($one) { fake(); } }
fn($fake) => 1;
TEXT;
$worker = function ($value) { return $value; };
"""
        self.assert_functions(source, [("<anonymous>", 6, 1, 1)])

    def test_public_cli_reports_arrow_parameter_violation(self):
        source = "<?php\n$worker = fn($a, $b, $c, $d, $e, $f) => $a;\n"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".code-linter.json").write_text(
                '{"include_extensions": [".php"], "max_parameters": 5}\n',
                encoding="utf-8",
            )
            (root / "fixture.php").write_text(source, encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "code-linter.py"),
                    "--root",
                    str(root),
                    "--config",
                    ".code-linter.json",
                    "--mode",
                    "all",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("max_parameters", result.stdout)
        self.assertIn("<anonymous>", result.stdout)


if __name__ == "__main__":
    unittest.main()
