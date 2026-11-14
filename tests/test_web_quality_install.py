import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from ci_scope_adapters import commands_for


def web_check(workdir: str = "."):
    return type("Check", (), {"type": "web-quality", "workdir": workdir, "config": None, "params": {}})()


class WebQualityInstallTests(unittest.TestCase):
    def commands(self, files: dict[str, str]) -> list[list[str]]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, text in files.items():
                (root / name).write_text(text)
            commands = commands_for(web_check(), root, ROOT, ("base", "head"))
            return [[part.replace(directory, "<root>") for part in command] for command in commands]

    def test_a_clean_checkout_installs_the_frozen_lockfile_without_scripts_before_the_compiler_runs(self):
        found = self.commands({"pnpm-lock.yaml": "", "package.json": "{}"})
        self.assertEqual(found[0], ["pnpm", "install", "--frozen-lockfile", "--ignore-scripts"])
        self.assertEqual(found[1], ["node", "<root>/node_modules/typescript/bin/tsc", "--noEmit"])

    def test_npm_and_yarn_lockfiles_pick_their_own_manager(self):
        self.assertEqual(self.commands({"package-lock.json": ""})[0], ["npm", "ci", "--ignore-scripts"])
        self.assertEqual(self.commands({"yarn.lock": ""})[0], ["yarn", "install", "--frozen-lockfile", "--ignore-scripts"])

    def test_declared_tools_run_after_the_install_even_though_they_are_not_installed_yet(self):
        manifest = json.dumps({"devDependencies": {"eslint": "9", "typescript": "7"}})
        found = self.commands({"pnpm-lock.yaml": "", "package.json": manifest})
        self.assertEqual([command[0] for command in found], ["pnpm", "node", "<root>/node_modules/.bin/eslint"])

    def test_no_lockfile_means_no_install_and_the_compiler_still_reports_what_is_missing(self):
        found = self.commands({"package.json": "{}"})
        self.assertEqual(found, [["node", "<root>/node_modules/typescript/bin/tsc", "--noEmit"]])

    def test_an_installed_compiler_skips_the_install(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "pnpm-lock.yaml").write_text("")
            compiler = root / "node_modules/typescript/bin/tsc"
            compiler.parent.mkdir(parents=True)
            compiler.touch()
            self.assertEqual(commands_for(web_check(), root, ROOT, ("b", "h")), [["node", str(compiler), "--noEmit"]])
