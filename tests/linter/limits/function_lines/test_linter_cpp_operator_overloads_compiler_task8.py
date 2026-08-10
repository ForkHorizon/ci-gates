import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


class CppOperatorOverloadCompilerTests(unittest.TestCase):
    def test_valid_operator_overload_fixture_compiles(self):
        compiler = shutil.which("g++") or shutil.which("clang++")
        if compiler is None:
            self.skipTest("neither g++ nor clang++ is installed")
        source = """#include <cstddef>
#include <ostream>
#include <string>

namespace math {
struct Number {
    int value{};
    Number operator+(const Number& other) const noexcept { return {value + other.value}; }
    Number operator-(const Number& other) const & noexcept;
    int& operator[](std::size_t index) noexcept { return values[index]; }
    int operator()(int first, int second) const { return first + second; }
    explicit operator bool() const noexcept { return value != 0; }
    int values[2]{};
};

Number Number::operator-(const Number& other) const & noexcept {
    return {value - other.value};
}

bool operator==(const Number& left, const Number& right) {
    return left.value == right.value;
}

std::ostream& operator<<(std::ostream& out, const Number& number) {
    return out << number.value;
}

Number operator>>(const Number& number, int shift) {
    return {number.value >> shift};
}
}
"""
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / "operators.cpp"
            source_path.write_text(source, encoding="utf-8")
            result = subprocess.run(
                [compiler, "-std=c++20", "-fsyntax-only", str(source_path)],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_qualified_and_conversion_operator_fixture_compiles(self):
        compiler = shutil.which("g++") or shutil.which("clang++")
        if compiler is None:
            self.skipTest("neither g++ nor clang++ is installed")
        source = """#include <string>

namespace api {
struct Token {
    operator std::string() const;
    Token operator->() const;
};

Token::operator std::string() const {
    return "token";
}

Token Token::operator->() const {
    return {};
}
}
"""
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / "qualified.cpp"
            source_path.write_text(source, encoding="utf-8")
            result = subprocess.run(
                [compiler, "-std=c++20", "-fsyntax-only", str(source_path)],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
