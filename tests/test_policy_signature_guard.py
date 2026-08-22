import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.policy_signature_guard import (
    DEFAULT_PROTECTED_PATTERNS,
    audit_policy_signatures,
    find_changed_protected_files,
    is_protected_file,
    verify_commit_signature,
)


class TestPolicySignatureGuard(unittest.TestCase):
    def test_is_protected_file(self):
        # Protected files
        self.assertTrue(is_protected_file(".code-linter.json"))
        self.assertTrue(is_protected_file("subfolder/.code-linter.json"))
        self.assertTrue(is_protected_file(".ruff.toml"))
        self.assertTrue(is_protected_file("ruff.toml"))
        self.assertTrue(is_protected_file(".unity-quality-gate.json"))
        self.assertTrue(is_protected_file(".github/workflows/code-linter.yml"))
        self.assertTrue(is_protected_file(".github/workflows/validate.yml"))
        self.assertTrue(is_protected_file(".github/CODEOWNERS"))
        self.assertTrue(is_protected_file("configs/allowed_signers"))

        # Non-protected normal source files
        self.assertFalse(is_protected_file("Editor/nexus_bridge/routing.py"))
        self.assertFalse(is_protected_file("Runtime/MyScript.cs"))
        self.assertFalse(is_protected_file("README.md"))
        self.assertFalse(is_protected_file("package.json"))
        self.assertFalse(is_protected_file("Sources/App/main.swift"))

    @patch("scripts.policy_signature_guard.git_cmd")
    def test_no_protected_files_changed(self, mock_git_cmd):
        # When only regular source files are modified
        mock_git_cmd.return_value = (
            0,
            "Editor/MyScript.cs\nRuntime/Helper.cs\nEditor/nexus_bridge/routing.py",
            "",
        )

        errors = audit_policy_signatures(
            root=ROOT,
            base="origin/main",
            head="HEAD",
            allowed_signers=ROOT / "configs/allowed_signers",
        )
        self.assertEqual(errors, [])

    @patch("scripts.policy_signature_guard.git_cmd")
    def test_unsigned_protected_file_change_fails(self, mock_git_cmd):
        def side_effect(root, args):
            cmd_str = " ".join(args)
            if "diff" in cmd_str:
                return 0, ".code-linter.json\nEditor/MyScript.cs", ""
            if "log" in cmd_str and "%H" in cmd_str:
                return 0, "abcd1234ef567890abcd1234ef567890abcd1234", ""
            if "log" in cmd_str and "%G?" in cmd_str:
                # N = No signature (unsigned agent commit)
                return 0, "N|||", ""
            return 0, "", ""

        mock_git_cmd.side_effect = side_effect

        errors = audit_policy_signatures(
            root=ROOT,
            base="origin/main",
            head="HEAD",
            allowed_signers=ROOT / "configs/allowed_signers",
        )
        self.assertEqual(len(errors), 1)
        self.assertIn("without a valid signature", errors[0])
        self.assertIn("Commit is unsigned", errors[0])

    @patch("scripts.policy_signature_guard.git_cmd")
    def test_verified_signed_protected_file_change_passes(self, mock_git_cmd):
        def side_effect(root, args):
            cmd_str = " ".join(args)
            if "diff" in cmd_str:
                return 0, ".code-linter.json\nEditor/MyScript.cs", ""
            if "log" in cmd_str and "%H" in cmd_str:
                return 0, "abcd1234ef567890abcd1234ef567890abcd1234", ""
            if "log" in cmd_str and "%G?" in cmd_str:
                # G = Good (valid) signature from trusted owner
                return 0, "G|daliys133@gmail.com|SHA256:daliysKeyFingerprint|", ""
            return 0, "", ""

        mock_git_cmd.side_effect = side_effect

        errors = audit_policy_signatures(
            root=ROOT,
            base="origin/main",
            head="HEAD",
            allowed_signers=ROOT / "configs/allowed_signers",
        )
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
