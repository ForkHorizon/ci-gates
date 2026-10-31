import unittest
from pathlib import Path

from scripts.forbidden_constructs import scan_text

FIXTURES = Path(__file__).parent / "fixtures"


class ForbiddenConstructTests(unittest.TestCase):
    def test_added_unsafe_lines_are_reported_and_existing_lines_are_ignored(self):
        text = (FIXTURES / "forbidden_probe.ts").read_text()
        violations = scan_text(text, ".ts", {1}, mode="new")
        self.assertEqual([item.rule_id for item in violations], ["no-any"])

    def test_suppression_requires_a_reason_on_same_or_previous_line(self):
        accepted = "// allow-no-any: boundary adapter\nconst item: any = value;\n"
        bare = "// allow-no-any:\nconst item: any = value;\n"
        self.assertEqual(scan_text(accepted, ".ts", {2}), [])
        self.assertEqual(
            [v.rule_id for v in scan_text(bare, ".ts", {2})],
            ["invalid-suppression", "no-any"],
        )

    def test_python_bare_catch_and_unexplained_noqa_are_flagged(self):
        text = "except:\n    pass  # noqa\n"
        self.assertEqual(
            {v.rule_id for v in scan_text(text, ".py", {1, 2})},
            {"bare-except", "no-noqa"},
        )

    def test_typescript_suppression_and_empty_catch_are_flagged(self):
        text = "// @ts-ignore\ntry { work(); } catch (error) { }\n// eslint-disable-next-line rule\n"
        rules = {v.rule_id for v in scan_text(text, ".ts", {1, 2, 3})}
        self.assertEqual(rules, {"no-ts-ignore", "no-empty-catch", "no-eslint-disable"})

    def test_swift_and_go_unsafe_constructs_are_flagged(self):
        swift = "let item = try! load()\nlet value = item as! String\n// swiftlint:disable force_cast\ncatch {\n}\n"
        go = "_ = os.Remove(path)\n//nolint:errcheck\n"
        self.assertEqual(
            {v.rule_id for v in scan_text(swift, ".swift", {1, 2, 3, 4})},
            {"no-try-bang", "no-force-cast", "no-swiftlint-disable", "no-empty-catch"},
        )
        self.assertEqual(
            {v.rule_id for v in scan_text(go, ".go", {1, 2})},
            {"no-ignored-error", "no-nolint"},
        )

    def test_go_custom_error_calls_are_project_overrides(self):
        rules = {
            ".go": [
                (
                    "no-ignored-error",
                    r"_\s*=\s*client\.Close\s*\(",
                    "do not drop Close error",
                )
            ]
        }
        self.assertEqual(
            [v.rule_id for v in scan_text("_ = client.Close()\n", ".go", {1}, rules=rules)],
            ["no-ignored-error"],
        )

    def test_python_ignore_and_multiline_empty_exception_are_flagged(self):
        text = "value = call()  # type: ignore\nexcept Exception:\n    pass\n"
        self.assertEqual(
            {v.rule_id for v in scan_text(text, ".py", {1, 2, 3})},
            {"no-type-ignore", "no-broad-except-pass"},
        )

    def test_new_only_mode_flags_added_python_body_after_existing_except(self):
        text = "except Exception:\n    pass\n"
        self.assertEqual(
            [v.rule_id for v in scan_text(text, ".py", {2}, mode="new")],
            ["no-broad-except-pass"],
        )

    def test_new_only_mode_flags_added_closing_brace_after_existing_empty_catch(self):
        text = "try {\n    work()\n} catch {\n}\n"
        self.assertEqual(
            [v.rule_id for v in scan_text(text, ".ts", {4}, mode="new")],
            ["no-empty-catch"],
        )

    def test_new_only_mode_ignores_comments_between_empty_block_lines(self):
        python = "except Exception:\n    # explanation\n    pass\n"
        typescript = "try {\n    work()\n} catch {\n    // explanation\n}\n"
        self.assertEqual(
            [v.rule_id for v in scan_text(python, ".py", {3}, mode="new")],
            ["no-broad-except-pass"],
        )
        self.assertEqual(
            [v.rule_id for v in scan_text(typescript, ".ts", {5}, mode="new")],
            ["no-empty-catch"],
        )

    def test_new_only_mode_skips_block_comments_between_empty_catch_lines(self):
        text = "try { work(); } catch { /* explanation */\n}\n"
        self.assertEqual(
            [v.rule_id for v in scan_text(text, ".ts", {2}, mode="new")],
            ["no-empty-catch"],
        )

    def test_new_only_mode_flags_pass_added_to_existing_bare_except(self):
        self.assertEqual(
            [v.rule_id for v in scan_text("except:\n    pass\n", ".py", {2})],
            ["no-broad-except-pass"],
        )

    def test_suppression_text_inside_strings_is_not_a_marker(self):
        text = 'const hint = "// allow-no-any: sample";\nconst item: any = value;\n'
        self.assertEqual(
            [v.rule_id for v in scan_text(text, ".ts", {2})],
            ["no-any"],
        )
        self.assertEqual(
            [v.rule_id for v in scan_text('const hint = "// allow-no-any:";\n', ".ts", {1})],
            [],
        )

    def test_escaped_quotes_do_not_expose_suppression_text_as_comment(self):
        text = 'const hint = "\\" // allow-no-any: sample";\nconst item: any = value;\n'
        self.assertEqual(
            [v.rule_id for v in scan_text(text, ".ts", {2})],
            ["no-any"],
        )

    def test_swift_raw_string_does_not_expose_suppression_text_as_comment(self):
        text = 'let marker = #"text " // allow-no-force-cast: example"#\nlet value = source as! String\n'
        self.assertEqual(
            [v.rule_id for v in scan_text(text, ".swift", {2})],
            ["no-force-cast"],
        )

    def test_swift_raw_string_escape_does_not_end_string_early(self):
        text = 'let marker = #"escaped \\"# // allow-no-force-cast: example"#\nlet value = source as! String\n'
        self.assertEqual(
            [v.rule_id for v in scan_text(text, ".swift", {2})],
            ["no-force-cast"],
        )

    def test_swift_nested_block_comments_are_skipped(self):
        text = "do { try work() } catch { /* outer /* nested */ */\n}\n"
        self.assertEqual(
            [v.rule_id for v in scan_text(text, ".swift", {2})],
            ["no-empty-catch"],
        )


if __name__ == "__main__":
    unittest.main()
