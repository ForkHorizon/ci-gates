import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from code_linter.yaml import yaml_syntax_issues


class YamlDuplicateKeyTests(unittest.TestCase):
    def issues(self, source, path="workflow.yml"):
        return yaml_syntax_issues(path, source)

    def assert_duplicate(self, source, line, key, path="workflow.yml"):
        issues = self.issues(source, path)
        self.assertEqual(len(issues), 1)
        issue = issues[0]
        self.assertEqual((issue.kind, issue.path, issue.line), ("duplicate_key", path, line))
        self.assertEqual(issue.message, f"Duplicate YAML key {key!r}.")

    def test_duplicate_top_level_key_reports_second_key_line(self):
        self.assert_duplicate("name: first\nname: second\n", 2, "name")

    def test_duplicate_top_level_key_is_rejected_when_first_value_would_win(self):
        self.assert_duplicate("name: first\nname: second\n", 2, "name")

    def test_duplicate_top_level_key_is_rejected_when_last_value_would_win(self):
        self.assert_duplicate("name: second\nname: first\n", 2, "name")

    def test_duplicate_nested_mapping_key_reports_nested_line(self):
        source = "jobs:\n  build:\n    runs-on: ubuntu-latest\n    runs-on: macos-latest\n"
        self.assert_duplicate(source, 4, "runs-on")

    def test_duplicate_key_in_sequence_mapping_is_rejected(self):
        source = "steps:\n  - name: build\n    name: deploy\n"
        self.assert_duplicate(source, 3, "name")

    def test_quoted_and_unquoted_equivalent_keys_are_duplicates(self):
        self.assert_duplicate('name: plain\n"name": quoted\n', 2, "name")

    def test_distinct_mapping_keys_remain_valid(self):
        source = "name: workflow\non: push\njobs:\n  build:\n    runs-on: ubuntu-latest\n"
        self.assertEqual(self.issues(source), [])

    def test_comments_and_colon_like_strings_do_not_create_duplicates(self):
        source = "name: 'text: name: still text' # name: comment\ndescription: \"another: name: string\"\n"
        self.assertEqual(self.issues(source), [])

    def test_malformed_flow_yaml_remains_a_syntax_error(self):
        issues = self.issues("name: [broken\nname: second\n")
        self.assertEqual(len(issues), 1)
        self.assertEqual((issues[0].kind, issues[0].line), ("syntax_error", 1))

    def test_duplicate_like_text_inside_block_scalar_is_ignored(self):
        source = "run: |\n  name: first\n  name: second\nnext: value\n"
        self.assertEqual(self.issues(source), [])

    def test_repeated_keys_in_separate_sequence_mappings_are_valid(self):
        source = "steps:\n  - name: build\n  - name: deploy\n"
        self.assertEqual(self.issues(source), [])

    def test_duplicate_key_after_comment_reports_the_duplicate_line(self):
        source = "name: first\n# name: comment\nname: second # name: trailing\n"
        self.assert_duplicate(source, 3, "name")

    def test_flow_mapping_duplicate_key_is_rejected(self):
        self.assert_duplicate("env: {name: first, name: second}\n", 1, "name")

    def test_public_code_linter_reports_structured_duplicate_key_diagnostic(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".code-linter.json").write_text("{}\n", encoding="utf-8")
            workflow = root / ".github/workflows/quality.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text("name: first\nname: second\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            result = subprocess.run(
                [sys.executable, str(SCRIPTS / "code-linter.py"), "--root", str(root)],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn(
            "::error file=.github/workflows/quality.yml,line=2,title=duplicate_key::Duplicate YAML key 'name'.",
            result.stdout,
        )
        self.assertIn("Code Linter failed: 1 issue(s)", result.stdout)


if __name__ == "__main__":
    unittest.main()
