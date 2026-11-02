"""Multi-line Rust attributes and oversized files cannot hide a suppression."""
import tempfile
import unittest
from pathlib import Path

from scripts.forbidden_constructs import MAX_SCAN_BYTES, ScanOptions, check, scan_text


def rules(text, added):
    return [item.rule_id for item in scan_text(text, ".rs", added)]


class MultilineRustTests(unittest.TestCase):
    def test_allow_on_its_own_line_inside_an_attribute_is_caught(self):
        text = "#[\n    allow(dead_code)\n]\nfn f() {}\n"
        self.assertEqual(rules(text, {2}), ["no-lint-suppression"])

    def test_spaced_and_split_attribute_forms_are_caught(self):
        self.assertEqual(rules("#[ allow ( dead_code ) ]\nfn f() {}\n", {1}), ["no-lint-suppression"])
        self.assertEqual(rules("#[cfg_attr(\n    test,\n    allow(unused)\n)]\nfn f() {}\n", {3}), ["no-lint-suppression"])

    def test_a_reasoned_marker_on_the_attribute_still_allows_it(self):
        text = "// allow-no-lint-suppression: generated code\n#[\n    allow(dead_code)\n]\nfn f() {}\n"
        self.assertEqual(rules(text, {3}), [])

    def test_ordinary_attributes_and_unrelated_lines_are_not_flagged(self):
        self.assertEqual(rules("#[derive(\n    Debug,\n    Clone\n)]\nstruct A;\n", {2}), [])

    def test_an_oversized_source_file_is_reported_instead_of_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            big = Path(directory) / "big.rs"
            big.write_text("// x\n" * (MAX_SCAN_BYTES // 4))
            found = [item.rule_id for item in check(Path(directory), ScanOptions("all", "worktree", "", "", None))]
        self.assertEqual(found, ["file-too-large"])


if __name__ == "__main__":
    unittest.main()
