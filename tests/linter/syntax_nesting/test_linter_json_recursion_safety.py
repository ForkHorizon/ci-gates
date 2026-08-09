import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
from code_linter.json_safety import MAX_JSON_DEPTH
from code_linter.syntax import tomllib

spec = importlib.util.spec_from_file_location("json_recursion_linter", SCRIPTS / "code-linter.py")
linter = importlib.util.module_from_spec(spec)
sys.modules["json_recursion_linter"] = linter
spec.loader.exec_module(linter)


def nested_json(depth: int, leaf: str = "0") -> str:
    openings = []
    for index in range(depth):
        if index % 2:
            openings.append('{"value":')
        else:
            openings.append("[")
    closings = ["]" if index % 2 == 0 else "}" for index in reversed(range(depth))]
    return "".join(openings) + leaf + "".join(closings)


def deeply_nested_policy(depth: int) -> str:
    return (
        '{"coverage_exceptions": '
        + ("[" * depth)
        + '{"pattern": "generated.py", "reason": "vendor"}'
        + ("]" * depth)
        + "}"
    )


class SourceJSONRecursionTests(unittest.TestCase):
    def test_shallow_json_object_remains_valid(self):
        self.assertEqual(
            linter.check_syntax("config.json", '{"name": "ci", "enabled": true}', "json"),
            [],
        )

    def test_json_arrays_and_objects_remain_valid(self):
        source = '{"items": [{"id": 1}, {"id": 2}], "empty": []}'
        self.assertEqual(linter.check_syntax("data.json", source, "json"), [])

    def test_deep_but_valid_json_at_safe_boundary_remains_valid(self):
        self.assertEqual(linter.check_syntax("nested.json", nested_json(MAX_JSON_DEPTH), "json"), [])

    def test_source_json_exceeding_python_recursion_is_structured(self):
        issues = linter.check_syntax(
            "too-deep.json",
            nested_json(max(sys.getrecursionlimit() * 2, MAX_JSON_DEPTH + 1)),
            "json",
        )
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].kind, "syntax_error")
        self.assertEqual(issues[0].line, 1)
        self.assertEqual(issues[0].message, "JSON syntax error: nesting is too deep.")

    def test_malformed_json_remains_a_structured_syntax_error(self):
        issues = linter.check_syntax("broken.json", '{"items": [}', "json")
        self.assertEqual([issue.kind for issue in issues], ["syntax_error"])
        self.assertEqual(issues[0].line, 1)
        self.assertIn("JSON syntax error:", issues[0].message)

    def test_source_json_duplicate_keys_keep_json_loader_semantics(self):
        source = '{"name": "first", "name": "last"}'
        self.assertEqual(linter.check_syntax("duplicate.json", source, "json"), [])

    def test_json_brackets_inside_strings_do_not_count_as_nesting(self):
        source = '{"text": "' + ("[" * (MAX_JSON_DEPTH + 1)) + '"}'
        self.assertEqual(linter.check_syntax("brackets.json", source, "json"), [])

    def test_large_flat_json_within_file_limit_remains_valid(self):
        source = "{" + ",".join(f'"key{index}": {index}' for index in range(20_000)) + "}"
        self.assertLess(len(source.encode("utf-8")), linter.MAX_FILE_BYTES)
        self.assertEqual(linter.check_syntax("large.json", source, "json"), [])

    def test_public_cli_reports_source_recursion_without_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".code-linter.json").write_text("{}\n", encoding="utf-8")
            (root / "too-deep.json").write_text(
                nested_json(max(sys.getrecursionlimit() * 2, MAX_JSON_DEPTH + 1)),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "code-linter.py"),
                    "--root",
                    str(root),
                    "--mode",
                    "all",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            combined = result.stdout + result.stderr
            self.assertEqual(result.returncode, 1)
            self.assertIn("title=syntax_error", combined)
            self.assertIn("JSON syntax error: nesting is too deep.", combined)
            self.assertNotIn("Traceback", combined)
            self.assertNotIn("RecursionError", combined)


class PolicyJSONRecursionTests(unittest.TestCase):
    def load_config(self, body: str):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / ".code-linter.json"
        path.write_text(body, encoding="utf-8")
        return path, linter.load_config(path)

    def assert_config_rejected(self, body: str, expected_message: str | None = None):
        path, _ = self._config_path(body)
        stderr = StringIO()
        with self.assertRaises(SystemExit) as raised, redirect_stderr(stderr):
            linter.load_config(path)
        self.assertEqual(raised.exception.code, 2)
        output = stderr.getvalue()
        self.assertIn("::error", output)
        if expected_message:
            self.assertIn(expected_message, output)
        return output

    def _config_path(self, body: str):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / ".code-linter.json"
        path.write_text(body, encoding="utf-8")
        return path, directory

    def test_deeply_nested_policy_config_is_structured_and_exits_two(self):
        output = self.assert_config_rejected(
            deeply_nested_policy(max(sys.getrecursionlimit() * 2, MAX_JSON_DEPTH + 1)),
            "Invalid JSON config: nesting is too deep.",
        )
        self.assertNotIn("Traceback", output)
        self.assertNotIn("RecursionError", output)

    def test_malformed_policy_json_keeps_structured_config_error(self):
        output = self.assert_config_rejected('{"max_file_lines": }', "Invalid JSON config:")
        self.assertNotIn("Traceback", output)

    def test_shallow_duplicate_policy_key_is_rejected(self):
        self.assert_config_rejected('{"max_file_lines": 10, "max_file_lines": 20}', "Duplicate JSON key")

    def test_deep_duplicate_policy_key_is_rejected(self):
        body = '{"language_overrides": {"python": {"max_file_lines": 10, "max_file_lines": 20}}}'
        self.assert_config_rejected(body, "Duplicate JSON key 'max_file_lines'")

    def test_duplicate_policy_keys_inside_array_objects_are_rejected(self):
        body = '{"coverage_exceptions": [{"pattern": "one.py", "reason": "vendor"}, {"pattern": "two.py", "pattern": "other.py", "reason": "generated"}]}'
        self.assert_config_rejected(body, "Duplicate JSON key 'pattern'")

    def test_duplicate_policy_key_at_nested_and_top_level_scopes_is_rejected(self):
        body = '{"max_file_lines": 10, "language_overrides": {"python": {"max_parameters": 3, "max_parameters": 4}}, "max_file_lines": 20}'
        self.assert_config_rejected(body, "Duplicate JSON key 'max_parameters'")

    def test_config_error_preserves_github_escaping_and_exit_code(self):
        body = '{"max_file_lines": 10, "max_file_lines": 20}'
        path, _ = self._config_path(body)
        stderr = StringIO()
        with self.assertRaises(SystemExit) as raised, redirect_stderr(stderr):
            linter.load_config(path)
        self.assertEqual(raised.exception.code, 2)
        output = stderr.getvalue()
        self.assertIn("::error file=", output)
        self.assertIn("Duplicate JSON key 'max_file_lines'", output)
        self.assertTrue(output.endswith("\n"))

    def test_public_cli_reports_policy_recursion_with_exit_two_and_no_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / ".code-linter.json"
            config.write_text(deeply_nested_policy(sys.getrecursionlimit() * 2), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "code-linter.py"),
                    "--root",
                    str(root),
                    "--mode",
                    "all",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("Invalid JSON config: nesting is too deep.", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertNotIn("RecursionError", result.stderr)

    def test_toml_and_yaml_syntax_paths_are_unaffected(self):
        if tomllib is None:
            self.skipTest("TOML validation requires Python 3.11+")
        self.assertEqual(
            linter.check_syntax("settings.toml", 'name = "ci"\nitems = [1, 2]\n', "toml"),
            [],
        )
        self.assertEqual(
            linter.check_syntax("settings.yaml", "name: ci\nitems:\n  - one\n", "yaml"),
            [],
        )

    def test_deep_json_result_is_deterministic_on_available_supported_interpreters(
        self,
    ):
        probe = """
import sys
sys.path.insert(0, sys.argv[1])
from code_linter import check_syntax
from code_linter.json_safety import MAX_JSON_DEPTH
text = '[' * (MAX_JSON_DEPTH + 1) + '0' + ']' * (MAX_JSON_DEPTH + 1)
issues = check_syntax('probe.json', text, 'json')
print(issues[0].kind, issues[0].line, issues[0].message)
"""
        interpreters = [shutil.which(name) for name in ("python3.11", "python3.14")]
        interpreters = [path for path in interpreters if path]
        if not interpreters:
            self.skipTest("Python 3.11 and 3.14 are not installed")
        for executable in interpreters:
            with self.subTest(executable=executable):
                result = subprocess.run(
                    [executable, "-c", probe, str(SCRIPTS)],
                    capture_output=True,
                    text=True,
                    check=False,
                    env={**os.environ, "PYTHONPATH": str(SCRIPTS)},
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(
                    result.stdout.strip(),
                    "syntax_error 1 JSON syntax error: nesting is too deep.",
                )
                self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
