"""The Swift gates drop the Command Line Tools SDK variables the git shim exports into hooks."""

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import swift_compile_project
import swift_quality_support

CLT_ENV = {
    "SDKROOT": "/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk",
    "CPATH": "/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/include",
    "LIBRARY_PATH": "/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/lib",
    "DEVELOPER_DIR": "/Applications/Xcode.app/Contents/Developer",
}


class SwiftSdkEnvTests(unittest.TestCase):
    def test_the_command_line_tools_sdk_exported_by_the_git_shim_is_dropped(self):
        for module in (swift_quality_support, swift_compile_project):
            with mock.patch.dict(os.environ, CLT_ENV, clear=True):
                module.ensure_developer_dir()
                self.assertEqual(os.environ, {"DEVELOPER_DIR": CLT_ENV["DEVELOPER_DIR"]})

    def test_another_sdk_root_is_left_alone(self):
        with mock.patch.dict(os.environ, {"SDKROOT": "/opt/custom/sdk", "DEVELOPER_DIR": "/x"}, clear=True):
            swift_quality_support.ensure_developer_dir()
            self.assertEqual(os.environ["SDKROOT"], "/opt/custom/sdk")


if __name__ == "__main__":
    unittest.main()
