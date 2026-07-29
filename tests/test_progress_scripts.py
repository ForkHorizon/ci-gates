import contextlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / name)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class ProgressScriptTests(unittest.TestCase):
    def test_progress_cli_emits_contract_payload(self):
        progress = load_script("_progress.py")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(
                progress.main(["--step", "lint", "--current", "3", "--total", "10", "--detail", "Sources/Foo.swift"]),
                0,
            )

        prefix, payload = output.getvalue().strip().split(" ", maxsplit=1)
        self.assertEqual(prefix, "::ci-scope-progress::")
        self.assertEqual(json.loads(payload), {"step": "lint", "current": 3, "total": 10, "detail": "Sources/Foo.swift"})

    def test_readability_reports_each_of_ten_files(self):
        readability = load_script("linter-checker-300-lines.py")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index in range(10):
                (root / f"File{index}.swift").write_text("func f() {}\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "add", "."], cwd=root, check=True)

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(readability.main(["--root", str(root), "--mode", "all"]), 0)

        markers = [
            json.loads(line.split(" ", maxsplit=1)[1])
            for line in output.getvalue().splitlines()
            if line.startswith("::ci-scope-progress:: ")
        ]
        self.assertEqual([(marker["current"], marker["total"]) for marker in markers], [(index, 10) for index in range(1, 11)])
        self.assertEqual(markers[0]["detail"], "File0.swift")
        self.assertEqual(markers[-1]["detail"], "File9.swift")


if __name__ == "__main__":
    unittest.main()
