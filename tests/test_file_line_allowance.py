import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from code_linter.config import load_config
from code_linter.runner import check_path


class FileLineAllowanceTests(unittest.TestCase):
    def test_exact_path_allowance_changes_only_that_files_line_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "large.py"
            source.write_text("value = 1\n" * 301)
            other = root / "other.py"
            other.write_text("value = 1\n" * 301)
            config_path = root / ".code-linter.json"
            config_path.write_text(
                json.dumps(
                    {
                        "file_line_exceptions": [
                            {
                                "path": "large.py",
                                "max_lines": 310,
                                "reason": "Existing generated API; tracked for split.",
                            }
                        ]
                    }
                )
            )
            config = load_config(config_path)
            self.assertEqual(check_path(root, source, config), [])
            self.assertEqual(
                [issue.kind for issue in check_path(root, other, config)],
                ["file_length"],
            )

    def test_allowance_requires_an_exact_existing_path_and_reason(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "source.py").write_text("value = 1\n")
            config_path = root / ".code-linter.json"
            for allowance in (
                {"path": "*.py", "max_lines": 400, "reason": "broad"},
                {"path": "source.py", "max_lines": 400},
                {"path": "source.py", "max_lines": 5001, "reason": "too high"},
            ):
                config_path.write_text(json.dumps({"file_line_exceptions": [allowance]}))
                with self.assertRaises(SystemExit):
                    load_config(config_path)


if __name__ == "__main__":
    unittest.main()
