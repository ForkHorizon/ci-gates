import argparse
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location(
    "audit_fixes_linter", SCRIPTS / "code-linter.py"
)
linter = importlib.util.module_from_spec(spec)
sys.modules["audit_fixes_linter"] = linter
spec.loader.exec_module(linter)


class SyntaxAndParserTests(unittest.TestCase):
    def test_invalid_python_is_always_a_syntax_error(self):
        issues = linter.check_syntax("broken.py", "def broken(:\n    pass\n", "python")
        self.assertEqual([issue.kind for issue in issues], ["syntax_error"])

    def test_unclosed_c_style_function_is_a_syntax_error(self):
        issues = linter.check_syntax(
            "broken.cs", "void Broken() {\n    Work();\n", "csharp"
        )
        self.assertEqual([issue.kind for issue in issues], ["syntax_error"])

    def test_multiline_javascript_arrow_is_measured(self):
        source = "const process = (\n    a, b, c, d, e, f\n) => {\n    work();\n}\n"
        self.assertEqual(
            linter.brace_function_lengths(source, "javascript"),
            [("process", 1, 5, 6)],
        )

    def test_csharp_expression_body_parameters_are_measured(self):
        source = "public int Sum(int a, int b, int c, int d, int e, int f) => a + b;"
        self.assertEqual(linter.brace_function_lengths(source, "csharp")[0][3], 6)

    def test_ruby_no_parentheses_and_multiline_parameters_are_measured(self):
        plain = "def process a, b, c, d, e, f\n  nil\nend\n"
        multiline = "def process(\n  a, b, c, d, e, f\n)\n  nil\nend\n"
        self.assertEqual(linter.ruby_function_lengths(plain)[0][3], 6)
        self.assertEqual(linter.ruby_function_lengths(multiline)[0][3], 6)

    def test_ruby_strings_and_heredocs_do_not_close_a_method(self):
        source = 'def long_method\n  puts "end"\n  text = <<~TEXT\nend\nTEXT\n'
        source += "  work\n" * 50 + "end\n"
        self.assertEqual(linter.ruby_function_lengths(source)[0][2], 56)
        self.assertEqual(linter.check_syntax("x.rb", "items << CONSTANT\n", "ruby"), [])

    def test_javascript_regex_brace_does_not_close_a_function(self):
        source = (
            "function longMethod() {\n  const matcher = /}/;\n"
            + "  work();\n" * 50
            + "}\n"
        )
        self.assertEqual(linter.brace_function_lengths(source, "javascript")[0][2], 53)

    def test_additional_supported_function_forms_are_measured(self):
        cases = [
            (
                "items.map((value) => {\n  return value;\n});",
                "javascript",
                "<anonymous>",
                1,
            ),
            ("static func ==(a: Item, b: Item) -> Bool { true }", "swift", "==", 2),
            ("subscript(a: Int, b: Int) -> Int { a }", "swift", "subscript", 2),
            ("fun `when`(a: Int, b: Int) { }", "kotlin", "when", 2),
            ("def [](a, b)\n nil\nend\n", "ruby", "[]", 2),
        ]
        for source, language, name, parameters in cases:
            with self.subTest(language=language, name=name):
                functions = linter.function_lengths(source, language)
                self.assertEqual((functions[0][0], functions[0][3]), (name, parameters))

    def test_bodyless_declaration_parameters_are_measured(self):
        source = "public abstract void Run(int a, int b, int c, int d, int e, int f);"
        self.assertEqual(linter.brace_function_lengths(source, "csharp")[0][3], 6)

    def test_php_hash_comments_and_heredocs_are_masked(self):
        source = "<?php\n# if ($fake) {\n$text = <<<TEXT\nif ($fake) {\nTEXT;\nfunction run() {}\n"
        self.assertEqual(linter.check_syntax("x.php", source, "php"), [])
        self.assertEqual(linter.brace_function_lengths(source, "php")[0][0], "run")


class NestingTests(unittest.TestCase):
    def test_brace_free_csharp_nesting_is_measured(self):
        source = "void Run() {\n if (a)\n  if (b)\n   if (c)\n    Work();\n}\n"
        self.assertEqual(
            len(linter.check_nesting_depth("x.cs", source, "csharp", 2)), 1
        )

    def test_ruby_end_nesting_is_measured(self):
        source = (
            "def run\n if a\n  while b\n   if c\n    work\n   end\n  end\n end\nend\n"
        )
        self.assertEqual(len(linter.check_nesting_depth("x.rb", source, "ruby", 2)), 1)

    def test_php_alternative_nesting_is_measured(self):
        source = "if ($a):\n if ($b):\n  work();\n endif;\nendif;\n"
        self.assertEqual(len(linter.check_nesting_depth("x.php", source, "php", 1)), 1)

    def test_labeled_loop_is_measured(self):
        source = "outer: for (let i = 0; i < 1; i++) {\n  work();\n}\n"
        self.assertEqual(
            len(linter.check_nesting_depth("x.js", source, "javascript", 0)), 1
        )


class ConfigurationTests(unittest.TestCase):
    def load_body(self, body):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".code-linter.json"
            path.write_text(body, encoding="utf-8")
            return linter.load_config(path)

    def assert_rejected(self, body):
        with self.assertRaises(SystemExit) as raised:
            self.load_body(body)
        self.assertEqual(raised.exception.code, 2)

    def test_malformed_or_disabling_config_is_rejected(self):
        invalid = [
            '{"include_extensions": {}}',
            '{"include_extensions": []}',
            '{"unknown_limit": 1}',
            '{"max_file_lines": 0}',
            '{"max_file_lines": 5.5}',
            '{"max_file_lines": 1000000}',
            '{"ignore": ["*.py"]}',
            '{"language_overrides": {"swift": 10}}',
            '{"language_overrides": {"brainfuck": {"max_file_lines": 10}}}',
            '{"language_overrides": {"swift": {"max_file_line": 10}}}',
        ]
        for body in invalid:
            with self.subTest(body=body):
                self.assert_rejected(body)

    def test_main_rejects_a_missing_config(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(SystemExit) as raised:
                linter.main(["--root", directory, "--config", "missing.json"])
        self.assertEqual(raised.exception.code, 2)

    def test_uppercase_supported_extension_is_scanned(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / ".code-linter.json"
            config_path.write_text("{}\n", encoding="utf-8")
            source = root / "Feature.PY"
            source.write_text("value = 1\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            args = argparse.Namespace(
                mode="all", base="", head="", config=config_path.name
            )
            self.assertEqual(
                linter.collect_paths(root, linter.load_config(config_path), args),
                [source],
            )

    def test_config_change_forces_all_file_scan(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.com"],
                cwd=root,
                check=True,
            )
            subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
            config_path = root / ".code-linter.json"
            config_path.write_text("{}\n", encoding="utf-8")
            source = root / "Feature.py"
            source.write_text("value = 1\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True)
            base = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True
            ).strip()
            config_path.write_text('{"max_file_lines": 250}\n', encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "policy"], cwd=root, check=True)
            args = argparse.Namespace(
                mode="changed", base=base, head="HEAD", config=config_path.name
            )
            self.assertEqual(
                linter.collect_paths(root, linter.load_config(config_path), args),
                [source],
            )


class SafetyAndCommentTests(unittest.TestCase):
    def test_source_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".code-linter.json").write_text("{}\n", encoding="utf-8")
            os.symlink("outside.py", root / "linked.py")
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            args = argparse.Namespace(
                mode="all", base="", head="", config=".code-linter.json"
            )
            with self.assertRaises(SystemExit):
                linter.collect_paths(
                    root, linter.load_config(root / ".code-linter.json"), args
                )

    def test_oversized_source_is_not_read(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "large.py"
            source.write_bytes(b"x" * (linter.MAX_FILE_BYTES + 1))
            issues = linter.check_paths(root, [source], linter.DEFAULT_CONFIG)
            self.assertEqual([issue.kind for issue in issues], ["file_size"])

    def test_doc_comments_have_a_bounded_separate_limit(self):
        source = "\n".join(f"#: line {index}" for index in range(3))
        issues = linter.check_comment_blocks("x.py", source, "python", 1, 2)
        self.assertEqual([issue.kind for issue in issues], ["doc_comment_block"])

    def test_mixed_comment_styles_cannot_reset_the_limit(self):
        source = "/// one\n/// two\n// prose\n/// three\n/// four\n/// five\n"
        issues = linter.check_comment_blocks("x.swift", source, "swift", 5, 50)
        self.assertEqual([issue.kind for issue in issues], ["comment_block"])

    def test_workflow_does_not_embed_inputs_in_shell(self):
        workflow = (ROOT / ".github/workflows/code-linter.yml").read_text(
            encoding="utf-8"
        )
        self.assertNotIn('mode="${{ inputs.mode }}"', workflow)
        self.assertNotIn('--config "${{ inputs.config }}"', workflow)
        self.assertNotIn('--model "${{ inputs.explain-model }}"', workflow)
        self.assertIn("persist-credentials: false", workflow)
        self.assertIn("contents: read", workflow)
        self.assertNotIn("gates-ref:", workflow)
        self.assertIn("ref: main", workflow)


if __name__ == "__main__":
    unittest.main()
