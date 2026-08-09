import importlib.util
import shutil
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
    "max_nesting_depth": 2,
    "max_parameters": 2,
    "max_comment_lines": 20,
    "max_doc_comment_lines": 20,
    "max_types_per_file": 20,
}


class CSharpExplicitInterfaceRegressionTests(unittest.TestCase):
    def functions(self, source):
        return linter_checker.brace_function_lengths(source, "csharp")

    def issues(self, source):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "Sample.cs"
            path.write_text(source, encoding="utf-8")
            return linter_checker.check_paths(root, [path], LIMITS)

    def test_void_explicit_implementation_is_detected(self):
        source = """class C {
    void IFoo.Run(int value) {
        Work(value);
    }
}
"""
        self.assertEqual(self.functions(source), [("Run", 2, 3, 1)])

    def test_value_returning_qualified_implementation_is_detected(self):
        source = """class C {
    int Namespace.IFoo.Compute(int value) {
        return value;
    }
}
"""
        self.assertEqual(self.functions(source), [("Compute", 2, 3, 1)])

    def test_generic_interface_and_generic_method_are_detected(self):
        source = """class C {
    Task<int> IFoo<T>.Compute<U>(T first, U second) {
        return 0;
    }
}
"""
        self.assertEqual(self.functions(source), [("Compute", 2, 3, 2)])

    def test_async_explicit_implementation_is_detected(self):
        source = """class C {
    async Task IFoo.Run(int first, int second) {
        await Task.Yield();
    }
}
"""
        self.assertEqual(self.functions(source), [("Run", 2, 3, 2)])

    def test_ref_return_explicit_implementation_is_detected(self):
        source = """class C {
    ref int IFoo.Get() {
        return ref value;
    }
}
"""
        self.assertEqual(self.functions(source), [("Get", 2, 3, 0)])

    def test_multiline_parameters_are_counted_from_declaration_line(self):
        source = """class C {
    void IFoo.Run(
        int first,
        string second,
        bool third
    )
    {
        Work();
    }
}
"""
        self.assertEqual(self.functions(source), [("Run", 2, 8, 3)])

    def test_body_brace_on_next_line_is_measured(self):
        source = """class C {
    void IFoo.Run(int value)
    {
        Work(value);
    }
}
"""
        self.assertEqual(self.functions(source), [("Run", 2, 4, 1)])

    def test_expression_bodied_explicit_implementation_is_one_line(self):
        source = """class C {
    int IFoo.Compute(int a, int b, int c) => a + b + c;
}
"""
        self.assertEqual(self.functions(source), [("Compute", 2, 1, 3)])

    def test_nested_classes_keep_explicit_implementations_distinct(self):
        source = """class Outer {
    class Inner {
        void IFoo.Run() {
            Work();
        }
    }
    void IFoo.Run() {
        Work();
    }
}
"""
        self.assertEqual(
            self.functions(source),
            [("Run", 3, 3, 0), ("Run", 7, 3, 0)],
        )

    def test_comments_and_strings_with_dotted_method_text_are_ignored(self):
        source = """class C {
    string text = "void IFoo.Fake(int a, int b) { }";
    // int Namespace.IFoo.Comment(int a, int b) { }
    void IFoo.Real(int value) {
        Work(value);
    }
}
"""
        self.assertEqual(self.functions(source), [("Real", 4, 3, 1)])

    def test_malformed_explicit_signature_does_not_create_phantom_function(self):
        source = """class C {
    void IFoo.Run(int value
}
"""
        self.assertEqual(self.functions(source), [])

    def test_qualified_call_like_block_is_not_an_explicit_method(self):
        source = """class C {
    this.IFoo.Run(first, second, third) {
        Fake();
        Fake();
        Fake();
    }
}
"""
        self.assertEqual(self.functions(source), [])
        self.assertEqual(self.issues(source), [])

    def test_constructors_destructors_and_ordinary_methods_are_preserved(self):
        source = """class C {
    C(int value) {
        Work(value);
    }
    void Run(int value) {
        Work(value);
    }
    ~C() {
        Work();
    }
}
"""
        self.assertEqual(
            [item[0] for item in self.functions(source)],
            ["C", "Run", "~C"],
        )

    def test_interface_declaration_is_not_misclassified_as_explicit_method(self):
        source = """interface IFoo {
    void Run(int first, int second, int third);
}
"""
        self.assertEqual(self.functions(source), [])
        self.assertEqual(self.issues(source), [])

    def test_line_accounting_ignores_fake_braces_in_literals(self):
        source = """class C {
    string text = "{ fake IFoo.Run(a, b) }";

    void IFoo.Run() {
        Work();
    }
}
"""
        self.assertEqual(self.functions(source), [("Run", 4, 3, 0)])

    def test_explicit_method_limits_report_length_and_parameters(self):
        source = """class C {
    void IFoo.Run(int a, int b, int c) {
        Work();
        Work();
        Work();
    }
}
"""
        self.assertEqual(
            [(issue.kind, issue.line) for issue in self.issues(source)],
            [("function_length", 2), ("max_parameters", 2)],
        )

    def test_explicit_method_body_still_enforces_nesting(self):
        source = """class C {
    void IFoo.Run() {
        if (first) {
            if (second) {
                if (third) {
                    Work();
                }
            }
        }
    }
}
"""
        self.assertTrue(any(issue.kind == "nesting_depth" for issue in self.issues(source)))

    def test_multiple_qualified_interface_segments_are_supported(self):
        source = """class C {
    string Company.Contracts.IFoo.Format(string value) {
        return value;
    }
}
"""
        self.assertEqual(self.functions(source), [("Format", 2, 3, 1)])

    def test_public_cli_reports_explicit_method_violations(self):
        source = """class C {
    void IFoo.Run(int a, int b, int c) {
        Work();
        Work();
        Work();
    }
}
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Sample.cs").write_text(source, encoding="utf-8")
            (root / ".code-linter.json").write_text(
                '{"max_file_lines": 100, "max_function_lines": 3, '
                '"max_parameters": 2, "max_nesting_depth": 2, '
                '"max_comment_lines": 20, "max_doc_comment_lines": 20, '
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
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("function_length", result.stdout)
        self.assertIn("max_parameters", result.stdout)

    def test_valid_fixture_compiles_with_available_csharp_compiler(self):
        compiler = shutil.which("csc")
        if compiler is None and shutil.which("dotnet") is None:
            self.skipTest("neither csc nor dotnet is installed")
        source = """using System.Threading.Tasks;
interface IFoo<T> { Task<int> Compute<U>(T first, U second); }
class C : IFoo<int> {
    async Task<int> IFoo<int>.Compute<U>(int first, U second) {
        await Task.Yield();
        return first;
    }
}
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_path = root / "Fixture.cs"
            source_path.write_text(source, encoding="utf-8")
            if compiler:
                command = [
                    compiler,
                    "/nologo",
                    "/target:library",
                    f"/out:{root / 'Fixture.dll'}",
                    str(source_path),
                ]
            else:
                project = root / "Fixture.csproj"
                project.write_text(
                    '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
                    "<TargetFramework>net8.0</TargetFramework><EnableDefaultCompileItems>false</EnableDefaultCompileItems>"
                    '</PropertyGroup><ItemGroup><Compile Include="Fixture.cs" /></ItemGroup></Project>',
                    encoding="utf-8",
                )
                command = [
                    shutil.which("dotnet"),
                    "build",
                    str(project),
                    "--nologo",
                    "--verbosity",
                    "quiet",
                ]
            result = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
