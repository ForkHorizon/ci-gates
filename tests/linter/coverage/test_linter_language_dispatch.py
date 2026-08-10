import tempfile
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

from code_linter import config, runner, syntax


EXPECTED_EXTENSIONS = {
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".hh": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".hxx": "cpp",
    ".m": "objective_c",
    ".mm": "objective_c",
    ".dart": "dart",
    ".scala": "scala",
    ".sc": "scala",
    ".groovy": "groovy",
    ".gradle": "groovy",
    ".sh": "shell",
    ".bash": "shell",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".swift": "swift",
    ".cs": "csharp",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".py": "python",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".go": "go",
    ".rs": "rust",
    ".php": "php",
    ".rb": "ruby",
}

SYNTAX_CHECKER_CASES = {
    "python": "python_syntax_issues",
    "json": "config_syntax_issues",
    "toml": "config_syntax_issues",
    "gitignore": "gitignore_syntax_issues",
    "ruby": "ruby_syntax_issues",
    "shell": "shell_syntax_issues",
    "yaml": "yaml_syntax_issues",
}
C_STYLE_LANGUAGES = set(EXPECTED_EXTENSIONS.values()) - set(SYNTAX_CHECKER_CASES)


def record_calls(bucket):
    return lambda *args: bucket.append(args) or []


class LanguageDispatchTests(unittest.TestCase):
    def test_every_supported_extension_has_an_explicit_language_contract(self):
        self.assertEqual(set(config.LANGUAGE_BY_EXTENSION), set(EXPECTED_EXTENSIONS))
        for extension, expected_language in EXPECTED_EXTENSIONS.items():
            with self.subTest(extension=extension):
                self.assertEqual(config.LANGUAGE_BY_EXTENSION[extension], expected_language)
                self.assertEqual(config.language_for_path(Path(f"fixture{extension}")), expected_language)

    def test_every_extension_reaches_the_public_check_path_with_its_language(self):
        observed = {}

        def observe(relative, text, language, limits):
            observed[relative] = language
            return []

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for extension in EXPECTED_EXTENSIONS:
                path = root / f"fixture{extension}"
                path.write_text("value = 1\n", encoding="utf-8")
                with patch.object(runner, "source_issues", side_effect=observe):
                    self.assertEqual(runner.check_path(root, path, config.initial_config()), [])

        expected = {f"fixture{extension}": language for extension, language in EXPECTED_EXTENSIONS.items()}
        self.assertEqual(observed, expected)

    def test_each_specialized_syntax_checker_has_a_direct_dispatch_case(self):
        for language, checker_name in SYNTAX_CHECKER_CASES.items():
            with self.subTest(language=language):
                marker = [f"{language}-sentinel"]
                with patch.object(syntax, checker_name, return_value=marker) as checker:
                    self.assertIs(syntax.check_syntax("fixture", "source", language), marker)
                expected_args = (
                    ("fixture", "source", language) if language in {"json", "toml"} else ("fixture", "source")
                )
                checker.assert_called_once_with(*expected_args)

    def test_each_c_style_language_reaches_the_shared_syntax_checker(self):
        for language in sorted(C_STYLE_LANGUAGES):
            with self.subTest(language=language):
                marker = [f"{language}-sentinel"]
                with patch.object(syntax, "c_style_syntax_issues", return_value=marker) as checker:
                    self.assertIs(syntax.check_syntax("fixture", "source", language), marker)
                checker.assert_called_once_with("fixture", "source", language)

    def test_structural_dispatch_runs_for_each_non_syntax_only_language(self):
        structural_languages = set(EXPECTED_EXTENSIONS.values()) - {"yaml", "gitignore"}
        for language in sorted(structural_languages):
            with self.subTest(language=language):
                calls = {name: [] for name in ("function", "nesting", "comments", "types")}

                with (
                    patch.object(runner, "check_syntax", return_value=[]),
                    patch.object(runner, "function_issues", side_effect=record_calls(calls["function"])),
                    patch.object(runner, "check_nesting_depth", side_effect=record_calls(calls["nesting"])),
                    patch.object(runner, "check_comment_blocks", side_effect=record_calls(calls["comments"])),
                    patch.object(runner, "check_types_per_file", side_effect=record_calls(calls["types"])),
                ):
                    self.assertEqual(runner.source_issues("fixture", "source", language, config.LIMIT_DEFAULTS), [])

                for checker_name, checker_calls in calls.items():
                    with self.subTest(checker=checker_name):
                        self.assertEqual(len(checker_calls), 1)
                        self.assertEqual(checker_calls[0][2], language)


if __name__ == "__main__":
    unittest.main()
