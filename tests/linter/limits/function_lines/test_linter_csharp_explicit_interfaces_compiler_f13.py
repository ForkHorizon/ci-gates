import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


class CSharpExplicitInterfaceCompilerTests(unittest.TestCase):
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
