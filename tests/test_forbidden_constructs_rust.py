import unittest

from scripts.forbidden_constructs import scan_text


class RustForbiddenConstructTests(unittest.TestCase):
    def test_lint_suppressions_and_rustfmt_skip_are_flagged(self):
        text = (
            "#![allow(clippy::collapsible_if)]\n"
            "#[allow(dead_code)]\n"
            "#[cfg_attr(test, allow(unused_variables))]\n"
            "#[expect(unused)]\n"
            "#[rustfmt::skip]\n"
            "fn ok() {}\n"
        )
        found = [(v.line, v.rule_id) for v in scan_text(text, ".rs", {1, 2, 3, 4, 5, 6})]
        self.assertEqual(
            found,
            [
                (1, "no-lint-suppression"),
                (2, "no-lint-suppression"),
                (3, "no-lint-suppression"),
                (4, "no-lint-suppression"),
                (5, "no-rustfmt-skip"),
            ],
        )

    def test_suppression_with_reason_and_ordinary_attributes_pass(self):
        accepted = "// allow-no-lint-suppression: generated binding\n#[allow(non_snake_case)]\n"
        ordinary = "#[derive(Debug)]\n#[cfg(test)]\nlet allowed = true;\n"
        self.assertEqual(scan_text(accepted, ".rs", {2}), [])
        self.assertEqual(scan_text(ordinary, ".rs", {1, 2, 3}), [])


if __name__ == "__main__":
    unittest.main()
