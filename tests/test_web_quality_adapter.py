import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from ci_scope_adapters import commands_for


class WebQualityAdapterTests(unittest.TestCase):
    def test_web_tools_run_only_when_locally_installed_and_pytest_is_fixed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workdir = root / "web"
            binaries = workdir / "node_modules/.bin"
            binaries.mkdir(parents=True)
            (workdir / "package.json").write_text(json.dumps({"scripts": {"typecheck": "tsc --noEmit"}}))
            compiler = workdir / "node_modules/typescript/bin/tsc"
            compiler.parent.mkdir(parents=True)
            compiler.touch()
            (binaries / "eslint").touch()
            check = type(
                "Check",
                (),
                {"type": "web-quality", "workdir": "web", "config": None, "params": {}},
            )()
            commands = commands_for(check, root, ROOT, ("base", "head"))
            self.assertEqual(
                commands,
                [["node", str(compiler), "--noEmit"], [str(binaries / "eslint"), "."]],
            )
        check = type(
            "Check",
            (),
            {"type": "python-pytest", "workdir": ".", "config": None, "params": {}},
        )()
        self.assertEqual(
            commands_for(check, ROOT, ROOT, ("base", "head")),
            [["python3", "-m", "pytest", "tests", "-q"]],
        )
        check = type(
            "Check",
            (),
            {"type": "web-test", "workdir": ".", "config": None, "params": {}},
        )()
        self.assertEqual(
            commands_for(check, ROOT, ROOT, ("base", "head")),
            [["node", "scripts/test.mjs"]],
        )


if __name__ == "__main__":
    unittest.main()
