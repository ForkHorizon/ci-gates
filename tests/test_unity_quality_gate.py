import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "unity-quality-gate.py"
SPEC = importlib.util.spec_from_file_location("unity_quality_gate", SCRIPT)
unity_quality_gate = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(unity_quality_gate)


class UnityQualityGateTests(unittest.TestCase):
    def test_is_unity_package_detection(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.assertFalse(unity_quality_gate.is_unity_package(root))

            (root / "package.json").write_text('{"name": "com.test.pkg"}', encoding="utf-8")
            self.assertTrue(unity_quality_gate.is_unity_package(root))

            (root / "ProjectSettings").mkdir()
            (root / "ProjectSettings" / "ProjectVersion.txt").write_text(
                "m_EditorVersion: 6000.0.0f1", encoding="utf-8"
            )
            self.assertFalse(unity_quality_gate.is_unity_package(root))

    def test_load_config_for_project_and_package(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg_project = unity_quality_gate.load_config(root / ".unity-quality-gate.json", is_pkg=False)
            self.assertEqual(cfg_project["project"], "Assembly-CSharp.csproj")
            self.assertEqual(cfg_project["include_paths"], ["Assets/"])

            cfg_pkg = unity_quality_gate.load_config(root / ".unity-quality-gate.json", is_pkg=True)
            self.assertEqual(cfg_pkg["project"], "")
            self.assertEqual(cfg_pkg["include_paths"], ["Runtime/", "Editor/"])

            # Test migration of default Assets/ template in package repos
            (root / ".unity-quality-gate.json").write_text(json.dumps({"include_paths": ["Assets/"]}), encoding="utf-8")
            cfg_migrated = unity_quality_gate.load_config(root / ".unity-quality-gate.json", is_pkg=True)
            self.assertEqual(cfg_migrated["include_paths"], ["Runtime/", "Editor/"])

    def test_is_first_party_filtering(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            pkg_config = {
                "include_paths": ["Runtime/", "Editor/"],
                "exclude_paths": ["Tests~/", "tools~/", "Plugins/"],
            }
            self.assertTrue(unity_quality_gate.is_first_party(root, str(root / "Runtime/Core.cs"), pkg_config))
            self.assertTrue(unity_quality_gate.is_first_party(root, str(root / "Editor/Inspector.cs"), pkg_config))
            self.assertFalse(unity_quality_gate.is_first_party(root, str(root / "Tests~/SmokeTests.cs"), pkg_config))
            self.assertFalse(unity_quality_gate.is_first_party(root, str(root / "tools~/Generator.cs"), pkg_config))
            self.assertFalse(unity_quality_gate.is_first_party(root, str(root / "External/Lib.cs"), pkg_config))


if __name__ == "__main__":
    unittest.main()
