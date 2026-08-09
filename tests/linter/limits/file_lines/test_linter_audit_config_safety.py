import argparse
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("audit_fixes_linter", SCRIPTS / "code-linter.py")
linter = importlib.util.module_from_spec(spec)
sys.modules["audit_fixes_linter"] = linter
spec.loader.exec_module(linter)


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
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(SystemExit) as raised:
            linter.main(["--root", directory, "--config", "missing.json"])
        self.assertEqual(raised.exception.code, 2)

    def test_duplicate_top_level_key_is_rejected_when_first_value_is_effective(self):
        self.assert_rejected('{"max_file_lines": 1, "max_file_lines": 100}')

    def test_duplicate_top_level_key_is_rejected_when_last_value_would_win(self):
        self.assert_rejected('{"max_file_lines": 100, "max_file_lines": 1}')

    def test_duplicate_language_override_key_is_rejected(self):
        body = '{"language_overrides": {"python": {"max_file_lines": 10, "max_file_lines": 20}}}'
        self.assert_rejected(body)

    def test_duplicate_language_override_name_is_rejected(self):
        body = '{"language_overrides": {"python": {"max_file_lines": 10}, "python": {"max_file_lines": 20}}}'
        self.assert_rejected(body)

    def test_duplicate_exception_object_key_is_rejected(self):
        body = '{"coverage_exceptions": [{"pattern": "generated.py", "reason": "vendor", "reason": "generated"}]}'
        self.assert_rejected(body)

    def test_duplicate_policy_object_key_inside_array_is_rejected(self):
        body = '{"coverage_exceptions": [{"pattern": "one.py", "reason": "generated"}, {"pattern": "two.py", "pattern": "other.py", "reason": "vendor"}]}'
        self.assert_rejected(body)

    def test_duplicate_keys_at_different_nesting_levels_are_rejected(self):
        body = '{"max_file_lines": 100, "language_overrides": {"python": {"max_file_lines": 10, "max_file_lines": 20}}, "max_file_lines": 200}'
        self.assert_rejected(body)

    def test_unicode_escaped_key_colliding_with_literal_key_is_rejected(self):
        body = '{"max_file_lines": 100, "\\u006dax_file_lines": 200}'
        self.assert_rejected(body)

    def test_duplicate_unicode_key_is_rejected_inside_nested_object(self):
        body = '{"language_overrides": {"python": {"max_file_lines": 10, "\\u006dax_file_lines": 20}}}'
        self.assert_rejected(body)

    def test_distinct_nested_keys_remain_valid(self):
        body = '{"max_file_lines": 100, "language_overrides": {"python": {"max_file_lines": 10, "max_parameters": 3}}, "coverage_exceptions": [{"pattern": "generated.py", "reason": "vendor"}]}'
        self.assertEqual(self.load_body(body)["language_overrides"]["python"]["max_parameters"], 3)

    def test_duplicate_config_error_reports_path_key_and_stable_exit_code(self):
        body = '{"max_file_lines": 100, "max_file_lines": 200}'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".code-linter.json"
            path.write_text(body, encoding="utf-8")
            stderr = StringIO()
            with self.assertRaises(SystemExit) as raised, redirect_stderr(stderr):
                linter.load_config(path)
            self.assertEqual(raised.exception.code, 2)
            self.assertIn("::error", stderr.getvalue())
            self.assertIn(f"file={path}", stderr.getvalue())
            self.assertIn("Duplicate JSON key 'max_file_lines'", stderr.getvalue())

    def test_public_cli_rejects_duplicate_config_with_exit_code_two(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "duplicate.json"
            config_path.write_text('{"max_file_lines": 1, "max_file_lines": 2}\n', encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPTS / "code-linter.py"), "--root", str(root), "--config", str(config_path)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("Duplicate JSON key 'max_file_lines'", result.stderr)

    def test_duplicate_key_cannot_change_enforced_file_line_policy(self):
        body = '{"max_file_lines": 1, "max_file_lines": 100}'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / ".code-linter.json"
            source = root / "too_long.py"
            config_path.write_text(body, encoding="utf-8")
            source.write_text("value = 1\\n" * 10, encoding="utf-8")
            with self.assertRaises(SystemExit) as raised:
                linter.load_config(config_path)
            self.assertEqual(raised.exception.code, 2)

    def test_duplicate_key_in_array_object_cannot_change_exception_policy(self):
        body = '{"coverage_exceptions": [{"pattern": "generated.py", "pattern": "other.py", "reason": "vendor"}]}'
        self.assert_rejected(body)

    def test_duplicate_key_with_other_valid_nested_objects_fails_before_validation(self):
        body = '{"language_overrides": {"python": {"max_file_lines": 10, "max_file_lines": 20}}, "coverage_exceptions": [{"pattern": "generated.py", "reason": "vendor"}], "max_file_lines": 100}'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            path.write_text(body, encoding="utf-8")
            with self.assertRaises(SystemExit) as raised:
                linter.load_config(path)
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
            args = argparse.Namespace(mode="all", base="", head="", config=config_path.name)
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
            base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
            config_path.write_text('{"max_file_lines": 250}\n', encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "policy"], cwd=root, check=True)
            args = argparse.Namespace(mode="changed", base=base, head="HEAD", config=config_path.name)
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
            args = argparse.Namespace(mode="all", base="", head="", config=".code-linter.json")
            with self.assertRaises(SystemExit):
                linter.collect_paths(root, linter.load_config(root / ".code-linter.json"), args)

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
        workflow = (ROOT / ".github/workflows/code-linter.yml").read_text(encoding="utf-8")
        self.assertNotIn('mode="${{ inputs.mode }}"', workflow)
        self.assertNotIn('--config "${{ inputs.config }}"', workflow)
        self.assertNotIn('--model "${{ inputs.explain-model }}"', workflow)
        self.assertIn("persist-credentials: false", workflow)
        self.assertIn("contents: read", workflow)
        self.assertNotIn("gates-ref:", workflow)
        self.assertIn("ref: main", workflow)


if __name__ == "__main__":
    unittest.main()
