import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[4] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

spec = importlib.util.spec_from_file_location("linter_checker", SCRIPTS_DIR / "code-linter.py")
linter_checker = importlib.util.module_from_spec(spec)
sys.modules["linter_checker"] = linter_checker
spec.loader.exec_module(linter_checker)


LIMITS = {
    "max_file_lines": 100,
    "max_function_lines": 3,
    "max_nesting_depth": 10,
    "max_parameters": 2,
    "max_comment_lines": 20,
    "max_doc_comment_lines": 20,
    "max_types_per_file": 20,
}


class DeclarationHeuristicF07Tests(unittest.TestCase):
    def issues(self, filename, source):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / filename
            path.write_text(source, encoding="utf-8")
            return linter_checker.check_paths(root, [path], LIMITS)

    def assert_no_function(self, language, source):
        self.assertEqual(linter_checker.brace_function_lengths(source, language), [])
        extension = {"csharp": "cs", "javascript": "js", "typescript": "ts"}.get(language) or language
        self.assertEqual(self.issues("sample." + extension, source), [])

    def test_c_family_call_like_blocks_are_not_declarations(self):
        source = """DoSomething(a, b, c) {
    x();
    y();
    z();
}
"""
        for language in (
            "c",
            "cpp",
            "csharp",
            "java",
            "dart",
            "groovy",
            "objective_c",
            "scala",
        ):
            with self.subTest(language=language):
                self.assert_no_function(language, source)

    def test_generic_call_like_headers_with_whitespace_are_not_declarations(self):
        source = """DoSomething < Result > (a, b, c) {
    x();
    y();
    z();
}
"""
        for language in ("c", "cpp", "csharp", "java", "objective_c"):
            with self.subTest(language=language):
                self.assert_no_function(language, source)

    def test_qualified_call_like_headers_are_not_declarations(self):
        cases = {
            "java": "service.DoSomething<String>(a, b, c) {\n    x();\n    y();\n    z();\n}\n",
            "csharp": "this.DoSomething<int>(a, b, c) {\n    x();\n    y();\n    z();\n}\n",
            "cpp": "object.DoSomething<int>(a, b, c) {\n    x();\n    y();\n    z();\n}\n",
        }
        for language, source in cases.items():
            with self.subTest(language=language):
                self.assert_no_function(language, source)

    def test_nested_call_like_blocks_do_not_create_inner_or_outer_functions(self):
        source = """Outer(a) {
    Inner(b, c, d) {
        x();
        y();
        z();
    }
}
"""
        for language in ("javascript", "typescript", "java", "csharp"):
            with self.subTest(language=language):
                self.assert_no_function(language, source)

    def test_javascript_and_typescript_call_like_blocks_are_not_methods(self):
        source = """DoSomething(a, b, c) {
    x();
    y();
    z();
}
"""
        for language in ("javascript", "typescript"):
            with self.subTest(language=language):
                self.assert_no_function(language, source)

    def test_comments_and_strings_with_call_shaped_text_leave_real_function_only(self):
        source = """// Fake(a, b, c) {
//     x(); y(); z();
// }
const text = "Fake(a, b, c) { x(); y(); z(); }";
function real(a, b) {
    return a + b;
}
"""
        self.assertEqual(
            linter_checker.brace_function_lengths(source, "javascript"),
            [("real", 5, 3, 2)],
        )
        self.assertEqual(self.issues("comments.js", source), [])

    def test_real_free_functions_and_methods_keep_parameter_and_length_checks(self):
        cases = {
            "c": "int add(int a, int b, int c) {\n    x();\n    y();\n    z();\n}\n",
            "cpp": "int add(int a, int b, int c) {\n    x();\n    y();\n    z();\n}\n",
            "java": "class Box {\n    public int add(int a, int b, int c) {\n        x();\n        y();\n        z();\n    }\n}\n",
            "csharp": "class Box {\n    public int Add(int a, int b, int c) {\n        x();\n        y();\n        z();\n    }\n}\n",
        }
        for language, source in cases.items():
            with self.subTest(language=language):
                lengths = linter_checker.brace_function_lengths(source, language)
                self.assertEqual(len(lengths), 1)
                self.assertEqual(lengths[0][3], 3)
                extension = "cs" if language == "csharp" else language
                self.assertEqual(
                    self.issues("sample." + extension, source)[0].kind,
                    "function_length",
                )

    def test_class_constructors_are_preserved_when_the_name_matches_enclosing_type(
        self,
    ):
        cases = {
            "java": """class Widget {
    Widget(int a, int b, int c) {
        x();
        y();
        z();
    }
}
""",
            "csharp": """class Widget {
    Widget(int a, int b, int c) {
        x();
        y();
        z();
    }
}
""",
            "cpp": """class Widget {
public:
    Widget(int a, int b, int c) {
        x();
        y();
        z();
    }
};
""",
        }
        for language, source in cases.items():
            with self.subTest(language=language):
                names = [item[0] for item in linter_checker.brace_function_lengths(source, language)]
                self.assertEqual(names, ["Widget"])
                extension = "cs" if language == "csharp" else language
                self.assertEqual(
                    self.issues("Widget." + extension, source)[0].kind,
                    "function_length",
                )

    def test_csharp_destructors_remain_declarations(self):
        source = """class Widget {
    ~Widget() {
        x();
        y();
        z();
    }
}
"""
        self.assertEqual(
            linter_checker.brace_function_lengths(source, "csharp"),
            [("~Widget", 2, 5, 0)],
        )
        self.assertEqual(self.issues("Widget.cs", source)[0].kind, "function_length")

    def test_javascript_class_object_methods_and_generators_remain_declarations(self):
        source = """class Box {
    *items(a, b, c) {
        x();
        y();
        z();
    }
}
const object = {
    method(a, b, c) {
        x();
        y();
        z();
    }
};
"""
        names = [item[0] for item in linter_checker.brace_function_lengths(source, "javascript")]
        self.assertEqual(names, ["items", "method"])
        issue_kinds = [issue.kind for issue in self.issues("methods.js", source)]
        self.assertEqual(
            issue_kinds,
            ["function_length", "max_parameters", "function_length", "max_parameters"],
        )

    def test_generators_and_function_expressions_remain_checked(self):
        source = """function* stream(a, b, c) {
    yield a;
    yield b;
    yield c;
}
const callback = function (a, b, c) {
    return a + b + c;
};
"""
        lengths = linter_checker.brace_function_lengths(source, "javascript")
        self.assertEqual(
            lengths,
            [("stream", 1, 5, 3), ("<anonymous>", 6, 3, 3)],
        )
        self.assertEqual(
            [(issue.kind, issue.line) for issue in self.issues("generators.js", source)],
            [("function_length", 1), ("max_parameters", 1), ("max_parameters", 6)],
        )

    def test_csharp_lambdas_and_java_anonymous_functions_remain_checked(self):
        csharp = """Func<int, int, int, int> f = (a, b, c) => {
    x();
    y();
    z();
};
"""
        self.assertEqual(
            linter_checker.brace_function_lengths(csharp, "csharp"),
            [("<anonymous>", 1, 5, 3)],
        )
        java = """Runnable task = new Runnable() {
    public void run() {
        x();
        y();
        z();
    }
};
"""
        self.assertEqual(
            linter_checker.brace_function_lengths(java, "java"),
            [("run", 2, 5, 0)],
        )

    def test_public_code_linter_has_no_issues_for_call_like_blocks(self):
        sources = {
            "sample.js": "DoSomething(a, b, c) {\n    x();\n    y();\n    z();\n}\n",
            "Sample.java": "DoSomething(a, b, c) {\n    x();\n    y();\n    z();\n}\n",
            "Sample.cs": "DoSomething(a, b, c) {\n    x();\n    y();\n    z();\n}\n",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for filename, source in sources.items():
                (root / filename).write_text(source, encoding="utf-8")
            (root / ".code-linter.json").write_text(
                '{"max_file_lines": 100, "max_function_lines": 3, "max_parameters": 2, '
                '"max_nesting_depth": 10, "max_comment_lines": 20, "max_doc_comment_lines": 20, '
                '"max_types_per_file": 20}\n',
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "code-linter.py"),
                    "--root",
                    str(root),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Code Linter passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
