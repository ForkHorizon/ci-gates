import argparse
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("coverage_inventory_linter", SCRIPTS / "code-linter.py")
linter = importlib.util.module_from_spec(spec)
sys.modules["coverage_inventory_linter"] = linter
assert spec.loader is not None
spec.loader.exec_module(linter)


class CoverageInventoryTestCase(unittest.TestCase):
    def args(self, **overrides):
        values = {"mode": "all", "base": "", "head": "", "config": ".code-linter.json"}
        values.update(overrides)
        return argparse.Namespace(**values)

    def create_repo(self, root, files, config=None):
        (root / ".code-linter.json").write_text(config or "{}\n", encoding="utf-8")
        for name, content in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "add", "."], cwd=root, check=True)

    def inventory(self, root, loaded_config=None, **args):
        loaded = linter.load_config(root / ".code-linter.json") if loaded_config is None else loaded_config
        return linter.collect_path_inventory(root, loaded, self.args(**args))

    def assert_rejected(self, body):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".code-linter.json"
            path.write_text(body, encoding="utf-8")
            with self.assertRaises(SystemExit) as raised:
                linter.load_config(path)
        self.assertEqual(raised.exception.code, 2)


class CoverageInventoryTests(CoverageInventoryTestCase):
    def test_structural_families_are_mapped_and_residual_surfaces_catalogued(self):
        mapped = {".c", ".cpp", ".h", ".m", ".mm", ".dart", ".scala", ".gradle"}
        residual = {".zsh", ".sql", ".jsonc", ".html", ".proto", ".lua", ".fs"}
        self.assertTrue(mapped.issubset(linter.LANGUAGE_BY_EXTENSION))
        self.assertTrue(residual.issubset(linter.UNSUPPORTED_SURFACE_BY_EXTENSION))
        self.assertIn(".sh", linter.LANGUAGE_BY_EXTENSION)
        self.assertIn(".bash", linter.LANGUAGE_BY_EXTENSION)
        self.assertIn(".json", linter.LANGUAGE_BY_EXTENSION)
        self.assertIn(".yaml", linter.LANGUAGE_BY_EXTENSION)
        self.assertIn(".toml", linter.LANGUAGE_BY_EXTENSION)
        self.assertEqual(linter.LANGUAGE_BY_FILENAME[".gitignore"], "gitignore")

    def test_surface_matching_is_case_insensitive_and_handles_build_names(self):
        self.assertIsNone(linter.unsupported_surface(Path("native.CPP")))
        self.assertIsNone(linter.unsupported_surface(Path("workflow.YAML")))
        self.assertEqual(linter.unsupported_surface(Path("Dockerfile")), ("Docker build", "dockerfile"))
        self.assertEqual(linter.unsupported_surface(Path("Makefile")), ("Make build", "makefile"))

    def test_unknown_text_is_visible_but_docs_and_binary_are_not(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.create_repo(
                root,
                {
                    "src/custom.dsl": "rule allow\n",
                    "src/extensionless": "#!/usr/bin/env custom\nrun()\n",
                    "README": "project notes\n",
                    "docs/guide.md": "# guide\n",
                    "assets/data.bin": "\x00\xff\x00",
                },
            )
            gaps = {gap.path: gap for gap in self.inventory(root).gaps if gap.path != ".code-linter.json"}
            self.assertEqual(gaps["src/custom.dsl"].category, "unknown_text_surface")
            self.assertEqual(gaps["src/extensionless"].category, "unknown_text_surface")
            self.assertNotIn("README", gaps)
            self.assertNotIn("docs/guide.md", gaps)
            self.assertNotIn("assets/data.bin", gaps)

    def test_inventory_selects_structural_files_and_reports_residuals(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.create_repo(
                root,
                {
                    "src/Main.py": "value = 1\n",
                    "src/native.cpp": "int main() { return 0; }\n",
                    ".github/workflows/check.yml": "name: check\n",
                    "vendor/handwritten.py": "value = 2\n",
                },
            )
            inventory = self.inventory(root)
            selected = {path.relative_to(root).as_posix() for path in inventory.selected}
            self.assertEqual(selected, {"src/Main.py", "src/native.cpp", ".github/workflows/check.yml"})
            self.assertEqual(
                {gap.category for gap in inventory.gaps if gap.path != ".code-linter.json"}, {"ignored_source"}
            )

    def test_generated_patterns_and_ignored_sources_are_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.create_repo(
                root,
                {
                    "Generated/Client.py": "value = 1\n",
                    "src/client.generated.py": "value = 1\n",
                    "src/client.g.cs": "class Client {}\n",
                    "src/bundle.min.js": "const x = 1;\n",
                },
                '{"ignore":["Generated/","*.generated.*","*.g.cs","*.min.js"]}\n',
            )
            inventory = self.inventory(root)
            self.assertEqual(len(inventory.selected), 0)
            paths = {gap.path for gap in inventory.gaps if gap.path != ".code-linter.json"}
            self.assertEqual(
                paths, {"Generated/Client.py", "src/bundle.min.js", "src/client.g.cs", "src/client.generated.py"}
            )
            self.assertTrue(
                all(gap.category == "ignored_source" for gap in inventory.gaps if gap.path != ".code-linter.json")
            )

    def test_excluded_extension_and_special_build_files_are_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.create_repo(
                root,
                {
                    "src/Main.py": "value = 1\n",
                    "src/App.js": "const value = 1;\n",
                    "Dockerfile": "FROM alpine\n",
                    "Makefile": "all:\n\ttrue\n",
                },
                '{"include_extensions":[".py"]}\n',
            )
            inventory = self.inventory(root)
            gap_by_path = {gap.path: gap for gap in inventory.gaps}
            self.assertEqual([path.name for path in inventory.selected], ["Main.py"])
            self.assertEqual(gap_by_path["src/App.js"].category, "excluded_extension")
            self.assertEqual(gap_by_path["Dockerfile"].extension, "dockerfile")
            self.assertEqual(gap_by_path["Makefile"].extension, "makefile")

    def test_config_validation_and_active_policy_handling(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.create_repo(root, {"Main.py": "value = 1\n"})
            config = linter.load_config(root / ".code-linter.json")
            self.assertEqual(config["coverage_mode"], "report")
            self.assertEqual(config["coverage_exceptions"], [])
            self.assertEqual(linter.strict_coverage_issues(self.inventory(root), config), [])

    def test_only_the_active_policy_file_gets_loader_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.create_repo(root, {"vendor/.code-linter.json": "{}\n"})
            gaps = {gap.path: gap for gap in self.inventory(root).gaps}
            self.assertEqual(gaps["vendor/.code-linter.json"].category, "ignored_source")

        valid = '{"coverage_mode":"strict","coverage_exceptions":[{"pattern":"vendor/","reason":"third-party mirror"}]}'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".code-linter.json"
            path.write_text(valid, encoding="utf-8")
            self.assertEqual(linter.load_config(path)["coverage_mode"], "strict")

    def test_invalid_coverage_policy_shapes_are_rejected(self):
        invalid = [
            {"coverage_mode": "off"},
            {"coverage_exceptions": "vendor/"},
            {"coverage_exceptions": ["vendor/"]},
            {"coverage_exceptions": [{"pattern": "vendor/"}]},
            {"coverage_exceptions": [{"pattern": "vendor/", "reason": "", "owner": "team"}]},
            {"coverage_exceptions": [{"pattern": "*.py", "reason": "everything"}]},
            {"include_extensions": [".brainfuck"]},
        ]
        for body in invalid:
            with self.subTest(body=body):
                self.assert_rejected(json.dumps(body))

    def test_legacy_api_and_changed_policy_scan_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.create_repo(root, {"Main.py": "value = 1\n", "native.cpp": "int x;\n"})
            config = linter.load_config(root / ".code-linter.json")
            selected = linter.collect_paths(root, config, self.args())
            self.assertEqual({path.name for path in selected}, {"Main.py", "native.cpp"})

            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True)
            base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
            (root / ".code-linter.json").write_text('{"max_file_lines":250}\n', encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "policy"], cwd=root, check=True)
            inventory = self.inventory(root, base=base, head="HEAD", config="config/../.code-linter.json")
            self.assertEqual({path.name for path in inventory.selected}, {"Main.py", "native.cpp"})


if __name__ == "__main__":
    unittest.main()
