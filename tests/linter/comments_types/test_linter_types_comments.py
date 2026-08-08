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

    def test_doc_comments_are_exempt(self):
        source = "import Foundation\n" + "".join(f"/// line {i}\n" for i in range(10))
        source += "func run() {}\n"
        self.assertEqual(self.blocks(source, "swift"), [])

    def test_javadoc_block_is_exempt(self):
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

    def test_license_file_header_is_exempt(self):
        source = "// Copyright 2026\n" + "".join(f"// license line {i}\n" for i in range(10))
        self.assertEqual(self.blocks(source, "swift"), [])

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


if __name__ == "__main__":
    unittest.main()
