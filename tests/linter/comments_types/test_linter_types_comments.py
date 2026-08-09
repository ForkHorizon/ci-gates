"""Regressions for the false positives and parse bugs found in the 2026-08-07 audit.

Each test names the behaviour that was wrong before, so a future rewrite that
reintroduces it fails here instead of in someone's pull request.
"""

import importlib.util
import sys
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

spec = importlib.util.spec_from_file_location("linter_fixes", SCRIPTS_DIR / "code-linter.py")
linter = importlib.util.module_from_spec(spec)
sys.modules["linter_fixes"] = linter
spec.loader.exec_module(linter)


class TypesPerFileTests(unittest.TestCase):
    def types(self, source, language):
        return [name for name, _ in linter.brace_type_declarations(source, language)]

    def test_nested_swift_types_are_not_counted(self):
        source = "struct Feed {\n    struct Run {}\n    enum Job {}\n}\n"
        self.assertEqual(self.types(source, "swift"), ["Feed"])

    def test_csharp_namespace_does_not_hide_its_types(self):
        source = "namespace App\n{\n    class A\n    {\n    }\n    class B\n    {\n    }\n}\n"
        self.assertEqual(self.types(source, "csharp"), ["A", "B"])

    def test_swift_extension_does_not_hide_its_types(self):
        source = "extension Feed {\n    struct Row {}\n}\nstruct Other {}\n"
        self.assertEqual(self.types(source, "swift"), ["Row", "Other"])

    def test_allman_type_declaration_still_nests(self):
        source = "class Outer\n{\n    class Inner\n    {\n    }\n}\n"
        self.assertEqual(self.types(source, "csharp"), ["Outer"])

    def test_go_alias_does_not_swallow_the_next_declaration(self):
        source = "type UserID = string\n\nfunc Handle() {\n}\n\ntype Store struct {\n}\n"
        self.assertEqual(self.types(source, "go"), ["UserID", "Store"])


class CommentBlockTests(unittest.TestCase):
    def blocks(self, source, language, limit=5):
        return linter.check_comment_blocks("fixture", source, language, limit)

    def test_doc_comments_use_the_separate_limit(self):
        source = "import Foundation\n" + "".join(f"/// line {i}\n" for i in range(10))
        source += "func run() {}\n"
        self.assertEqual(self.blocks(source, "swift"), [])

    def test_javadoc_block_uses_the_separate_limit(self):
        source = "import java.util.List;\n/**\n" + "".join(f" * line {i}\n" for i in range(10))
        source += " */\nvoid run() {}\n"
        self.assertEqual(self.blocks(source, "java"), [])

    def test_plain_block_comment_is_still_flagged(self):
        source = "int seed = 0;\n/*\n" + "".join(f" * line {i}\n" for i in range(10))
        source += " */\nvoid run() {}\n"
        self.assertEqual(len(self.blocks(source, "csharp")), 1)

    def test_commented_out_code_is_still_flagged(self):
        source = "let seed = 0\n" + "".join(f"// old line {i}\n" for i in range(10))
        source += "func run() {}\n"
        self.assertEqual(len(self.blocks(source, "swift")), 1)

    def test_generic_file_header_is_not_exempt(self):
        source = "".join(f"//  line {i}\n" for i in range(10)) + "\nfunc run() {}\n"
        self.assertEqual(len(self.blocks(source, "swift")), 1)

    def test_license_file_header_uses_the_bounded_allowance(self):
        source = "// SPDX-License-Identifier: MIT\n" + "".join(f"// license line {i}\n" for i in range(10))
        self.assertEqual(self.blocks(source, "swift"), [])

    def test_copyright_without_license_text_is_not_exempt(self):
        source = "// Copyright is unrelated prose\n" + "".join(f"// line {i}\n" for i in range(10))
        self.assertEqual(len(self.blocks(source, "swift")), 1)

    def test_license_header_has_a_bounded_allowance(self):
        source = "// SPDX-License-Identifier: MIT\n" + "".join(f"// line {i}\n" for i in range(29))
        self.assertEqual(self.blocks(source, "swift"), [])
        source += "// line 29\n"
        self.assertEqual(len(self.blocks(source, "swift")), 1)

    def test_commented_out_code_cannot_use_a_license_word_as_a_bypass(self):
        source = "// copyright = false\n" + "".join(f"// disabled code {i}\n" for i in range(10))
        self.assertEqual(len(self.blocks(source, "swift")), 1)

    def test_spdx_marker_without_identifier_is_not_exempt(self):
        source = "// SPDX-License-Identifier\n" + "".join(f"// line {i}\n" for i in range(10))
        self.assertEqual(len(self.blocks(source, "swift")), 1)

    def test_spdx_marker_after_the_header_scan_window_is_not_exempt(self):
        source = "".join(f"// preamble {i}\n" for i in range(5))
        source += "// SPDX-License-Identifier: MIT\n"
        source += "".join(f"// line {i}\n" for i in range(5))
        self.assertEqual(len(self.blocks(source, "swift")), 1)

    def test_copyright_and_license_phrase_form_a_bounded_header(self):
        source = "// Copyright 2026 Example\n// Project terms\n// Licensed under the MIT License.\n"
        source += "".join(f"// line {i}\n" for i in range(27))
        self.assertEqual(self.blocks(source, "swift"), [])

    def test_blank_lines_and_mixed_doc_styles_share_one_limit(self):
        source = "/// API paragraph one\n\n// prose paragraph one\n\n"
        source += "/// API paragraph two\n\n// prose paragraph two\n"
        source += "// prose paragraph three\n// prose paragraph four\n"
        self.assertEqual([issue.kind for issue in self.blocks(source, "swift")], ["comment_block"])

    def test_python_triple_quoted_comment_text_is_ignored_before_real_block(self):
        source = 'fixture = """\n' + "".join(f"# string data {i}\n" for i in range(20))
        source += '"""\n' + "".join(f"# real comment {i}\n" for i in range(6))
        issues = self.blocks(source, "python")
        self.assertEqual([(issue.kind, issue.line) for issue in issues], [("comment_block", 23)])

    def test_python_doc_and_prose_comments_cannot_reset_each_other(self):
        source = "#: documentation one\n\n# prose one\n\n#: documentation two\n"
        source += "\n".join(f"# prose {i}" for i in range(4))
        issues = self.blocks(source, "python")
        self.assertEqual([issue.kind for issue in issues], ["comment_block"])

    def test_python_doc_comments_over_the_generous_limit_are_reported_as_doc(self):
        source = "\n".join(f"#: API detail {i}" for i in range(51))
        issues = self.blocks(source, "python")
        self.assertEqual([(issue.kind, issue.line) for issue in issues], [("doc_comment_block", 1)])

    def test_javadoc_over_the_generous_limit_is_still_bounded(self):
        source = "/**\n" + "".join(f" * API detail {i}\n" for i in range(50)) + " */\nvoid run() {}\n"
        issues = self.blocks(source, "java")
        self.assertEqual([issue.kind for issue in issues], ["doc_comment_block"])

    def test_shebang_only_exempt_on_the_first_line(self):
        source = "#!/usr/bin/env python3\n" + "".join(f"# line {i}\n" for i in range(3))
        self.assertEqual(self.blocks(source, "python", 3), [])

    def test_hash_lines_inside_a_python_string_are_not_comments(self):
        source = 'x = 1\nFIXTURE = """\n' + "".join(f"# line {i}\n" for i in range(10))
        source += '"""\n'
        self.assertEqual(self.blocks(source, "python"), [])

    def test_python_trailing_comments_do_not_form_a_block(self):
        source = "".join(f"x{i} = {i}  # note {i}\n" for i in range(10))
        self.assertEqual(self.blocks(source, "python"), [])

    def test_python_real_comment_block_still_flagged(self):
        source = "x = 1\n" + "".join(f"# line {i}\n" for i in range(10)) + "y = 2\n"
        self.assertEqual(len(self.blocks(source, "python")), 1)

    def test_unparseable_python_falls_back_to_prefix_scan(self):
        source = "x = (\n" + "".join(f"# line {i}\n" for i in range(10))
        self.assertEqual(len(self.blocks(source, "python")), 1)

    def test_python_doc_comments_are_bounded_and_not_prose_flags(self):
        source = "\n".join(f"#: line {i}" for i in range(51))
        self.assertEqual(len(self.blocks(source, "python")), 1)
        self.assertTrue(all(flag is False for flag in linter.comment_line_flags(source, "python")))


if __name__ == "__main__":
    unittest.main()
