import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS_DIR = Path(__file__).resolve().parents[4] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

spec = importlib.util.spec_from_file_location("source_encoding_linter", SCRIPTS_DIR / "code-linter.py")
linter = importlib.util.module_from_spec(spec)
sys.modules["source_encoding_linter"] = linter
spec.loader.exec_module(linter)
runner = importlib.import_module("code_linter.runner")


class SourceEncodingTests(unittest.TestCase):
    def issues_for(self, filename: str, content: bytes):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / filename
            source.write_bytes(content)
            return linter.check_paths(root, [source], linter.DEFAULT_CONFIG)

    def assert_single_issue(self, filename: str, content: bytes, kind: str, line: int = 1):
        issues = self.issues_for(filename, content)
        self.assertEqual(len(issues), 1)
        issue = issues[0]
        self.assertEqual(issue.path, filename)
        self.assertEqual(issue.line, line)
        self.assertEqual(issue.kind, kind)
        self.assertTrue(issue.message)
        return issue

    def test_truncated_utf8_in_csharp_is_an_encoding_issue_before_syntax(self):
        issue = self.assert_single_issue("Main.cs", b'class Main {\n  string value = "\xe2\x82\n}\n', "encoding", 2)
        self.assertIn("UTF-8", issue.message)
        self.assertNotIn("replacement", issue.message.lower())

    def test_multiple_invalid_bytes_in_javascript_are_one_structured_encoding_issue(self):
        issue = self.assert_single_issue("app.js", b"function main() {}\xff\xfe\xf5\n", "encoding")
        self.assertIn("UTF-8", issue.message)
        self.assertEqual(issue.path, "app.js")

    def test_bad_continuation_byte_in_java_is_rejected(self):
        issue = self.assert_single_issue("Main.java", b'class Main {\n  String value = "\xc3(";\n}\n', "encoding", 2)
        self.assertIn("UTF-8", issue.message)

    def test_mixed_invalid_utf8_and_nul_reports_encoding_without_replacement(self):
        issue = self.assert_single_issue("main.go", b"package main\n\xff\x00\n", "encoding", 2)
        self.assertIn("UTF-8", issue.message)

    def test_nul_in_csharp_code_is_binary_source_issue(self):
        issue = self.assert_single_issue("Main.cs", b"class Main {\x00}\n", "binary_source")
        self.assertIn("U+0000", issue.message)

    def test_nul_inside_javascript_string_is_binary_source_issue(self):
        issue = self.assert_single_issue("app.js", b'const value = "a\x00b";\n', "binary_source")
        self.assertIn("U+0000", issue.message)

    def test_nul_inside_go_comment_is_binary_source_issue(self):
        issue = self.assert_single_issue("main.go", b"// generated note\x00\npackage main\n", "binary_source")
        self.assertIn("U+0000", issue.message)

    def test_control_character_inside_rust_code_is_binary_source_issue(self):
        issue = self.assert_single_issue("main.rs", b"fn main() {\x01\n}\n", "binary_source")
        self.assertIn("U+0001", issue.message)

    def test_del_control_character_inside_php_comment_is_binary_source_issue(self):
        issue = self.assert_single_issue("index.php", b"<?php // generated\x7f\necho 1;\n", "binary_source")
        self.assertIn("U+007F", issue.message)

    def test_all_supported_c_style_family_extensions_reject_invalid_utf8(self):
        cases = {
            "Main.cs": b"class Main {}\xff",
            "Main.java": b"class Main {}\xff",
            "app.ts": b"const value = 1;\xff",
            "main.go": b"package main\xff",
            "main.rs": b"fn main() {}\xff",
            "index.php": b"<?php echo 1;\xff",
        }
        for filename, content in cases.items():
            with self.subTest(filename=filename):
                issue = self.assert_single_issue(filename, content, "encoding")
                self.assertEqual(issue.path, filename)
                self.assertIn("UTF-8", issue.message)

    def test_valid_non_ascii_javascript_source_remains_valid(self):
        issues = self.issues_for("app.js", "const café = 'naïve';\n".encode())
        self.assertEqual(issues, [])

    def test_tabs_newlines_and_c_family_form_feed_remain_legal_source_whitespace(self):
        source = b"int main() {\n\treturn 0;\f\n}\n"
        issues = self.issues_for("main.c", source)
        self.assertFalse([issue for issue in issues if issue.kind in {"encoding", "binary_source"}])

    def test_read_errors_keep_existing_structured_file_read_issue(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "unreadable.java"
            source.write_bytes(b"class Main {}\n")
            with patch.object(runner, "_read_limited_bytes", side_effect=PermissionError("denied")):
                text, error = runner.read_source(source, Path("unreadable.java"))
        self.assertIsNone(text)
        self.assertEqual(error.kind, "file_read")
        self.assertEqual(error.path, Path("unreadable.java"))
        self.assertIn("Unable to read file", error.message)

    def test_public_script_reports_encoding_issue_and_nonzero_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".code-linter.json").write_text("{}\n", encoding="utf-8")
            source = root / "broken.ts"
            source.write_bytes(b"const value = 1;\xff\n")
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            result = subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / "code-linter.py"), "--root", str(root)],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 1)
        report = result.stdout + result.stderr
        self.assertIn("title=encoding", report)
        self.assertIn("file=broken.ts", report)
        self.assertIn("Code Linter failed", report)
        self.assertNotIn("�", report)


if __name__ == "__main__":
    unittest.main()
