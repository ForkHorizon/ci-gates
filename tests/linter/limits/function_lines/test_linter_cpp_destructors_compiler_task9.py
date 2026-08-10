import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


class CppDestructorCompilerTests(unittest.TestCase):
    def compile_source(self, source):
        compiler = shutil.which("g++") or shutil.which("clang++")
        if compiler is None:
            self.skipTest("neither g++ nor clang++ is installed")
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / "destructors.cpp"
            source_path.write_text(source, encoding="utf-8")
            return subprocess.run(
                [compiler, "-std=c++20", "-fsyntax-only", str(source_path)],
                capture_output=True,
                text=True,
                check=False,
            )

    def test_member_nested_and_qualified_destructors_compile(self):
        source = """namespace Namespace {
struct Base {
    virtual ~Base() noexcept = default;
};
struct Widget : Base {
    struct Inner {
        ~Inner();
    };
    ~Widget() noexcept override;
};
}

Namespace::Widget::~Widget() noexcept
{
}

Namespace::Widget::Inner::~Inner()
{
}
"""
        result = self.compile_source(source)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_out_of_line_destructor_with_valid_qualifiers_compiles(self):
        source = """struct Base {
    virtual ~Base() noexcept = default;
};
struct Widget : Base {
    ~Widget() noexcept override;
};

Widget::~Widget() noexcept
{
}
"""
        result = self.compile_source(source)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
