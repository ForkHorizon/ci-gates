import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import install_hooks


class InstallerSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        env = {
            **os.environ,
            "HOME": str(base),
            "GIT_CONFIG_GLOBAL": str(base / "gitconfig"),
            "GIT_CONFIG_NOSYSTEM": "1",
        }
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.hooks = base / "hooks"
        self.base = base

    def test_a_foreign_hook_is_never_overwritten(self):
        self.hooks.mkdir()
        mine = self.hooks / "pre-commit"
        mine.write_text("#!/bin/sh\necho my own hook\n", encoding="utf-8")
        with self.assertRaises(install_hooks.InstallError) as caught:
            install_hooks.install(self.hooks)
        self.assertIn("not overwriting", str(caught.exception))
        self.assertEqual(mine.read_text(encoding="utf-8"), "#!/bin/sh\necho my own hook\n")
        self.assertEqual(
            subprocess.run(
                ["git", "config", "--global", "--get", "core.hooksPath"], capture_output=True, text=True, check=False
            ).stdout.strip(),
            "",
        )

    def test_reinstalling_over_our_own_hooks_is_fine(self):
        install_hooks.install(self.hooks)
        install_hooks.install(self.hooks)
        self.assertTrue((self.hooks / "pre-push").exists())

    def test_a_gates_path_with_shell_syntax_cannot_run_code(self):
        evil = self.base / "g$(touch pwned)`touch pwned2`"
        (evil / "scripts/hooks").mkdir(parents=True)
        source = Path(install_hooks.GATES) / "scripts/hooks/ci-scope-hook"
        (evil / "scripts/hooks/ci-scope-hook").write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        install_hooks.install(self.hooks, evil)
        wrapper = (self.hooks / "ci-scope-check").read_text(encoding="utf-8")
        result = subprocess.run(
            ["sh", "-c", f"cd {self.base} && sh {self.hooks / 'ci-scope-check'} --help"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertFalse((self.base / "pwned").exists(), result.stderr)
        self.assertFalse((self.base / "pwned2").exists(), result.stderr)
        self.assertIn("'", wrapper)


if __name__ == "__main__":
    unittest.main()
