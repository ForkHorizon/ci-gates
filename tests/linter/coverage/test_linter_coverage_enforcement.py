import argparse
import contextlib
import importlib
import importlib.util
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
runner = importlib.import_module("code_linter.runner")
spec = importlib.util.spec_from_file_location("coverage_enforcement_linter", SCRIPTS / "code-linter.py")
linter = importlib.util.module_from_spec(spec)
sys.modules["coverage_enforcement_linter"] = linter
assert spec.loader is not None
spec.loader.exec_module(linter)


def fail_open_for(filename, error):
    original_open = Path.open

    def open_path(path, *args, **kwargs):
        if path.name == filename:
            raise error
        return original_open(path, *args, **kwargs)

    return open_path


class CoverageEnforcementTestCase(unittest.TestCase):
    def create_repo(self, root, files, config=None):
        (root / ".code-linter.json").write_text(config or "{}\n", encoding="utf-8")
        for name, content in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "add", "."], cwd=root, check=True)

    def args(self, **overrides):
        values = {"mode": "all", "base": "", "head": "", "config": ".code-linter.json"}
        values.update(overrides)
        return argparse.Namespace(**values)

    def inventory(self, root):
        config = linter.load_config(root / ".code-linter.json")
        return linter.collect_path_inventory(root, config, self.args())


class CoverageEnforcementTests(CoverageEnforcementTestCase):
    def test_unreadable_unknown_gap_remains_unapproved_even_with_matching_exception(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.create_repo(
                root,
                {"src/custom.dsl": "rule allow\n"},
                '{"coverage_mode":"strict","coverage_exceptions":[{"pattern":"src/","reason":"external gate"}]}\n',
            )
            config = linter.load_config(root / ".code-linter.json")
            with patch.object(
                Path, "open", autospec=True, side_effect=fail_open_for("custom.dsl", PermissionError("denied"))
            ):
                issues = linter.strict_coverage_issues(self.inventory(root), config)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].kind, "coverage_gap")
        self.assertEqual(issues[0].path, "src/custom.dsl")
        self.assertEqual(
            issues[0].message,
            "Unable to read unknown coverage input. Code Linter cannot determine whether this tracked input is covered.",
        )

    def test_report_cli_warns_for_unreadable_unknown_input_without_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.create_repo(root, {"custom.dsl": "rule allow\n"})
            output = io.StringIO()
            error = io.StringIO()
            with (
                patch.object(
                    Path, "open", autospec=True, side_effect=fail_open_for("custom.dsl", PermissionError("denied"))
                ),
                contextlib.redirect_stdout(output),
                contextlib.redirect_stderr(error),
            ):
                result = linter.main(["--root", str(root)])
        report = output.getvalue() + error.getvalue()
        self.assertEqual(result, 0)
        self.assertIn("coverage_gap", report)
        self.assertIn("file=custom.dsl", report)
        self.assertIn("Unable to read unknown coverage input", report)
        self.assertNotIn("denied", report)
        self.assertNotIn("Traceback", report)

    def test_strict_cli_fails_for_unreadable_extensionless_input_without_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.create_repo(root, {"custom": "run()\n"})
            output = io.StringIO()
            error = io.StringIO()
            with (
                patch.object(
                    Path, "open", autospec=True, side_effect=fail_open_for("custom", OSError("I/O unavailable"))
                ),
                contextlib.redirect_stdout(output),
                contextlib.redirect_stderr(error),
            ):
                result = linter.main(["--root", str(root), "--coverage-mode", "strict"])
        report = output.getvalue() + error.getvalue()
        self.assertEqual(result, 1)
        self.assertIn("coverage_gap", report)
        self.assertIn("file=custom", report)
        self.assertIn("Unable to read unknown coverage input", report)
        self.assertNotIn("I/O unavailable", report)
        self.assertNotIn("Traceback", report)

    def test_known_language_read_errors_remain_file_read_issues(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "main.py"
            source.write_text("value = 1\n", encoding="utf-8")
            with patch.object(runner, "_read_limited_bytes", side_effect=PermissionError("denied")):
                issues = linter.check_paths(root, [source], linter.DEFAULT_CONFIG)
        self.assertEqual([(issue.path, issue.kind) for issue in issues], [("main.py", "file_read")])

    def test_high_impact_brace_families_receive_structural_checks(self):
        snippets = {
            "native.c": "int f(int a, int b, int c, int d, int e, int f) { return a; }\n",
            "native.cpp": "class One {};\nclass Two {};\nclass Three {};\n",
            "native.m": "@interface Thing\n@end\n",
            "native.dart": "class Thing { int run() { return 1; } }\n",
            "native.scala": "class Thing { def run(a: Int) = a }\n",
            "build.gradle": "class Thing { def run() { return 1 } }\n",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.create_repo(root, snippets)
            config = linter.load_config(root / ".code-linter.json")
            issues = linter.check_paths(root, self.inventory(root).selected, config)
            kinds = {issue.kind for issue in issues}
            self.assertIn("max_parameters", kinds)
            self.assertIn("types_per_file", kinds)
            self.assertEqual(kinds - {"max_parameters", "types_per_file"}, set())

    def test_json_and_toml_use_standard_library_syntax_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.create_repo(
                root,
                {"config/bad.json": '{"enabled": true,}\n', "config/bad.toml": "[server\nport = 1\n"},
            )
            config = linter.load_config(root / ".code-linter.json")
            issues = linter.check_paths(root, self.inventory(root).selected, config)
            syntax = {(issue.path, issue.kind) for issue in issues}
            self.assertEqual(syntax, {("config/bad.json", "syntax_error"), ("config/bad.toml", "syntax_error")})

    def test_bash_files_receive_native_syntax_and_structural_checks(self):
        nested = "\n".join(
            [
                "#!/usr/bin/env bash",
                "run() {",
                "  # implementation note",
                "  if true; then",
                "    if true; then",
                "      if true; then",
                "        if true; then",
                "          if true; then",
                "            echo ok",
                "          fi",
                "        fi",
                "      fi",
                "    fi",
                "  fi",
                "}",
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.create_repo(root, {"scripts/run.sh": nested})
            config = linter.load_config(root / ".code-linter.json")
            issues = linter.check_paths(root, self.inventory(root).selected, config)
            self.assertIn("nesting_depth", {issue.kind for issue in issues})
            self.assertNotIn("syntax_error", {issue.kind for issue in issues})

    def test_bash_syntax_errors_block_before_structural_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.create_repo(root, {"scripts/bad.sh": "if true; then\n  echo missing-fi\n"})
            config = linter.load_config(root / ".code-linter.json")
            issues = linter.check_paths(root, self.inventory(root).selected, config)
            self.assertEqual({issue.kind for issue in issues}, {"syntax_error"})

    def test_yaml_workflows_receive_dependency_free_syntax_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.create_repo(
                root,
                {
                    ".github/workflows/check.yml": "name: check\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo ok\n",
                    ".github/workflows/bad.yml": "name: [broken\n",
                },
            )
            config = linter.load_config(root / ".code-linter.json")
            issues = linter.check_paths(root, self.inventory(root).selected, config)
            self.assertEqual(
                [(issue.path, issue.kind) for issue in issues], [(".github/workflows/bad.yml", "syntax_error")]
            )

    def test_gitignore_policy_receives_syntax_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.create_repo(root, {".gitignore": "build/\n!\n"})
            config = linter.load_config(root / ".code-linter.json")
            issues = linter.check_paths(root, self.inventory(root).selected, config)
            self.assertEqual([(issue.path, issue.kind) for issue in issues], [(".gitignore", "syntax_error")])

    def test_coverage_exception_approves_only_matching_residual_gap(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.create_repo(
                root,
                {"vendor/lib.sql": "select 1;\n", "native.sql": "select 2;\n"},
                '{"coverage_mode":"strict","coverage_exceptions":[{"pattern":"vendor/","reason":"third-party mirror"}]}\n',
            )
            config = linter.load_config(root / ".code-linter.json")
            issues = linter.strict_coverage_issues(self.inventory(root), config)
            self.assertEqual([issue.path for issue in issues], ["native.sql"])

    def test_strict_mode_never_approves_ignored_supported_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.create_repo(
                root,
                {"vendor/lib.py": "value = 1\n"},
                '{"coverage_mode":"strict","coverage_exceptions":[{"pattern":"vendor/","reason":"vendor mirror"}]}\n',
            )
            config = linter.load_config(root / ".code-linter.json")
            issues = linter.strict_coverage_issues(self.inventory(root), config)
            self.assertEqual([issue.path for issue in issues], ["vendor/lib.py"])
            self.assertIn("does not accept exclusions", issues[0].message)

    def test_strict_mode_never_approves_excluded_supported_extension(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.create_repo(
                root,
                {"src/app.py": "value = 1\n"},
                '{"coverage_mode":"strict","include_extensions":[".js"],"coverage_exceptions":[{"pattern":"src/","reason":"external gate"}]}\n',
            )
            config = linter.load_config(root / ".code-linter.json")
            issues = linter.strict_coverage_issues(self.inventory(root), config)
            self.assertEqual([issue.path for issue in issues], ["src/app.py"])

    def test_report_mode_warns_without_failing_and_strict_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.create_repo(root, {"native.sql": "select 1;\n"})
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = linter.main(["--root", str(root)])
            self.assertEqual(result, 0)
            self.assertIn("coverage_gap", output.getvalue())
            self.assertIn("Code Linter passed", output.getvalue())
            self.assertEqual(linter.main(["--root", str(root), "--coverage-mode", "strict"]), 1)

    def test_unknown_text_is_blocking_in_strict_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.create_repo(root, {"custom.dsl": "rule allow\n"})
            self.assertEqual(linter.main(["--root", str(root), "--coverage-mode", "strict"]), 1)

    def test_report_annotation_cap_keeps_total_gap_count(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.create_repo(root, {f"native/{index}.sql": "select 1;\n" for index in range(55)})
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = linter.main(["--root", str(root)])
            text = output.getvalue()
            self.assertEqual(result, 0)
            self.assertIn("55 gap(s)", text)
            self.assertIn("suppressed 5 additional", text)
            self.assertEqual(text.count("title=coverage_gap"), 50)


if __name__ == "__main__":
    unittest.main()
