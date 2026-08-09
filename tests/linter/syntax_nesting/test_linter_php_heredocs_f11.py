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
spec = importlib.util.spec_from_file_location("php_heredoc_linter", SCRIPTS / "code-linter.py")
linter = importlib.util.module_from_spec(spec)
sys.modules["php_heredoc_linter"] = linter
spec.loader.exec_module(linter)


class PhpHeredocLexicalStateTests(unittest.TestCase):
    def assert_valid_php(self, source):
        php = shutil.which("php")
        if not php:
            return
        with tempfile.NamedTemporaryFile("w", suffix=".php", encoding="utf-8") as fixture:
            fixture.write(source)
            fixture.flush()
            result = subprocess.run([php, "-l", fixture.name], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def assert_following_function(self, source, name="run", parameters=6):
        self.assert_valid_php(source)
        self.assertEqual(
            linter.brace_function_lengths(source, "php")[-1][::3],
            (name, parameters),
        )

    def test_marker_inside_double_quoted_string_does_not_hide_following_function(self):
        source = """<?php
$example = "<<<FAKE";
function run($a, $b, $c, $d, $e, $f) {
    return $a;
}
"""
        self.assert_following_function(source)

    def test_marker_inside_single_quoted_string_does_not_hide_following_function(self):
        source = """<?php
$example = '<<<FAKE';
function run($a, $b, $c, $d, $e, $f) {
    return $a;
}
"""
        self.assert_following_function(source)

    def test_marker_inside_double_quoted_nowdoc_looking_string_is_opaque(self):
        source = """<?php
$example = "<<<'FAKE'";
function run($a, $b, $c, $d, $e, $f) {
    return $a;
}
"""
        self.assert_following_function(source)

    def test_marker_inside_line_comment_does_not_hide_following_function(self):
        source = """<?php
// <<<FAKE
function run($a, $b, $c, $d, $e, $f) {
    return $a;
}
"""
        self.assert_following_function(source)

    def test_marker_inside_hash_comment_does_not_hide_following_function(self):
        source = """<?php
# <<<FAKE
function run($a, $b, $c, $d, $e, $f) {
    return $a;
}
"""
        self.assert_following_function(source)

    def test_marker_inside_multiline_comment_does_not_hide_following_function(self):
        source = """<?php
/* comment starts <<<FAKE
   braces { and a fake function() stay in the comment
*/
function run($a, $b, $c, $d, $e, $f) {
    return $a;
}
"""
        self.assert_following_function(source)

    def test_escaped_quote_before_marker_keeps_string_opaque(self):
        source = """<?php
$example = "escaped quote: \\\" and marker <<<FAKE";
function run($a, $b, $c, $d, $e, $f) {
    return $a;
}
"""
        self.assert_following_function(source)

    def test_near_marker_with_extra_angle_bracket_does_not_start_heredoc(self):
        source = """<?php
$example = "<<<<FAKE";
function run($a, $b, $c, $d, $e, $f) {
    return $a;
}
"""
        self.assert_following_function(source)

    def test_malformed_heredoc_opener_does_not_hide_following_function(self):
        source = """<?php
$example = <<<;
function run($a, $b, $c, $d, $e, $f) {
    return $a;
}
"""
        self.assertEqual(linter.brace_function_lengths(source, "php")[-1][0], "run")

    def test_real_heredoc_content_hides_fake_functions_and_braces(self):
        for label in ("TEXT", "text", "_text", "MixedCase"):
            with self.subTest(label=label):
                source = f"""<?php
$document = <<<{label}
function fake($a, $b, $c, $d, $e, $f) {{
   if ($one) {{ if ($two) {{ work(); }} }}
}}
{label};
"""
                self.assert_valid_php(source)
                self.assertEqual(linter.check_syntax("fixture.php", source, "php"), [])
                self.assertEqual(linter.function_lengths(source, "php"), [])
                self.assertEqual(linter.check_nesting_depth("fixture.php", source, "php", 0), [])

    def test_real_nowdoc_content_hides_interpolation_like_php_code(self):
        source = """<?php
$document = <<<'TEXT'
function fake($a, $b, $c, $d, $e, $f) { return {$value}; }
if ($one) { if ($two) { work(); } }
TEXT;
"""
        self.assert_valid_php(source)
        self.assertEqual(linter.check_syntax("fixture.php", source, "php"), [])
        self.assertEqual(linter.function_lengths(source, "php"), [])
        self.assertEqual(linter.check_nesting_depth("fixture.php", source, "php", 0), [])

    def test_indented_heredoc_closer_with_semicolon_resumes_scanning(self):
        source = """<?php
$document = <<<TEXT
opaque { function fake() {} }
    TEXT;
function after($a, $b, $c, $d, $e, $f) { return $a; }
"""
        self.assert_following_function(source, name="after")

    def test_heredoc_closer_without_semicolon_resumes_scanning(self):
        source = """<?php
$document = <<<TEXT
opaque { function fake() {} }
TEXT
function after($a, $b, $c, $d, $e, $f) { return $a; }
"""
        self.assertEqual(linter.check_syntax("fixture.php", source, "php"), [])
        self.assertEqual(linter.brace_function_lengths(source, "php")[-1][0], "after")

    def test_multiline_function_declaration_after_heredoc_is_measured(self):
        source = """<?php
$document = <<<TEXT
function fake($a, $b, $c, $d, $e, $f) {}
TEXT;
function run(
    $a,
    $b,
    $c,
    $d,
    $e,
    $f
) {
    return $a;
}
"""
        self.assert_following_function(source)

    def test_nested_php_expression_text_inside_heredoc_remains_opaque(self):
        source = """<?php
$document = <<<TEXT
{$outer[$index ? 0 : 1]} { if ($one) { if ($two) { fake(); } } }
TEXT;
function run($a, $b, $c, $d, $e, $f) { return $a; }
"""
        self.assert_following_function(source)

    def test_multiple_heredoc_blocks_preserve_code_between_and_after_them(self):
        source = """<?php
$first = <<<FIRST
function fake_first($a, $b, $c, $d, $e, $f) {}
FIRST;
function middle($a, $b, $c, $d, $e, $f) { return $a; }
$second = <<<'SECOND'
function fake_second($a, $b, $c, $d, $e, $f) {}
SECOND;
function after($a, $b, $c, $d, $e, $f) { return $a; }
"""
        self.assert_valid_php(source)
        self.assertEqual(
            [item[0] for item in linter.function_lengths(source, "php")],
            ["middle", "after"],
        )

    def test_real_code_before_and_after_nowdoc_keeps_line_accounting(self):
        source = """<?php
function before($a) { return $a; }
$document = <<<'TEXT'
function hidden($a, $b, $c, $d, $e, $f) {}
TEXT;
function after($a) { return $a; }
"""
        self.assert_valid_php(source)
        self.assertEqual(
            linter.function_lengths(source, "php"),
            [("before", 2, 1, 1), ("after", 6, 1, 1)],
        )

    def test_function_length_and_parameter_limits_survive_fake_marker_string(self):
        source = (
            '<?php\n$example = "<<<FAKE";\nfunction enforce($a, $b, $c, $d, $e, $f) {\n' + "    work();\n" * 51 + "}\n"
        )
        functions = linter.brace_function_lengths(source, "php")
        self.assertEqual(functions[0][0], "enforce")
        self.assertEqual(functions[0][2:], (53, 6))

    def test_nesting_limit_survives_fake_marker_comment(self):
        source = """<?php
// <<<FAKE
function enforce() {
    if ($one) {
        if ($two) {
            work();
        }
    }
}
"""
        issues = linter.check_nesting_depth("fixture.php", source, "php", 1)
        self.assertEqual([(issue.kind, issue.line) for issue in issues], [("nesting_depth", 5)])

    def test_unclosed_heredoc_reports_last_source_line(self):
        source = """<?php
$document = <<<TEXT
unterminated { function fake() {} }
"""
        issues = linter.check_syntax("src/fixture.php", source, "php")
        self.assertEqual(
            [(issue.path, issue.line, issue.kind, issue.message) for issue in issues],
            [("src/fixture.php", 3, "syntax_error", "Unterminated comment or string.")],
        )

    def test_public_cli_enforces_function_after_fake_marker_string(self):
        source = """<?php
$example = "<<<FAKE";
function enforce($a, $b, $c, $d, $e, $f) { return $a; }
"""
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
        self.assertNotIn("Code Linter passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
