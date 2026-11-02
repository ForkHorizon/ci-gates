import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import ci_scope_cli as cli
from scripts import install_hooks


class HookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.env = {
            **os.environ,
            "HOME": str(base),
            "GIT_CONFIG_GLOBAL": str(base / "gitconfig"),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.com",
        }
        patcher = mock.patch.dict(os.environ, self.env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.hooks = base / "hooks"
        self.repo = base / "repo"
        self.repo.mkdir()
        self.git("init", "-q", cwd=self.repo)
        (self.repo / "a.txt").write_text("a\n", encoding="utf-8")
        self.git("add", ".", cwd=self.repo)

    def git(self, *args, cwd=None, check=True, extra_env=None):
        env = {**self.env, **(extra_env or {})}
        return subprocess.run(
            ["git", *args], cwd=cwd or self.repo, env=env, capture_output=True, text=True, check=check
        )

    def stub(self, code, name="stub"):
        path = Path(self.tmp.name) / name
        path.write_text(f"#!/bin/sh\necho \"$@\" >> '{path}.calls'\nexit {code}\n", encoding="utf-8")
        path.chmod(0o755)
        return path

    def test_install_writes_hooks_and_sets_the_global_path_once(self):
        written = install_hooks.install(self.hooks)
        self.assertEqual({p.name for p in written}, {"pre-commit", "pre-push", "ci-scope-check"})
        self.assertTrue(all(os.access(p, os.X_OK) for p in written))
        self.assertEqual(self.git("config", "--global", "core.hooksPath").stdout.strip(), str(self.hooks))
        install_hooks.install(self.hooks)  # same path again is fine
        self.git("config", "--global", "core.hooksPath", "/somewhere/else")
        with self.assertRaises(install_hooks.InstallError):
            install_hooks.install(self.hooks)

    def test_failing_check_blocks_a_commit_and_a_passing_one_allows_it(self):
        install_hooks.install(self.hooks)
        blocked = self.git("commit", "-qm", "x", check=False, extra_env={"CI_SCOPE_CLI": str(self.stub(1))})
        self.assertNotEqual(blocked.returncode, 0)
        self.assertEqual(self.git("log", "--oneline", check=False).returncode, 128, "no commit was created")
        allowed = self.git("commit", "-qm", "x", extra_env={"CI_SCOPE_CLI": str(self.stub(0, "ok"))})
        self.assertEqual(allowed.returncode, 0)
        self.assertIn("--hook --tier commit", (Path(self.tmp.name) / "ok.calls").read_text(encoding="utf-8"))

    def test_the_projects_own_hook_still_runs_after_the_check(self):
        install_hooks.install(self.hooks)
        marker = Path(self.tmp.name) / "project-hook-ran"
        own = self.repo / ".git/hooks/pre-commit"
        own.write_text(f"#!/bin/sh\ntouch '{marker}'\nexit 0\n", encoding="utf-8")
        own.chmod(0o755)
        self.git("commit", "-qm", "x", extra_env={"CI_SCOPE_CLI": str(self.stub(0))})
        self.assertTrue(marker.exists())
        marker.unlink()
        own.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        refused = self.git("commit", "-qm", "y", check=False, extra_env={"CI_SCOPE_CLI": str(self.stub(0, "ok2"))})
        self.assertNotEqual(refused.returncode, 0)

    def test_pre_push_uses_the_push_tier_and_can_block(self):
        install_hooks.install(self.hooks)
        self.git("commit", "-qm", "x", extra_env={"CI_SCOPE_CLI": str(self.stub(0))})
        remote = Path(self.tmp.name) / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", str(remote)], env=self.env, check=True)
        self.git("remote", "add", "origin", str(remote))
        branch = self.git("branch", "--show-current").stdout.strip()
        refused = self.git(
            "push", "-q", "origin", branch, check=False, extra_env={"CI_SCOPE_CLI": str(self.stub(1, "no"))}
        )
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("--hook --tier push", (Path(self.tmp.name) / "no.calls").read_text(encoding="utf-8"))
        accepted = self.git("push", "-q", "origin", branch, extra_env={"CI_SCOPE_CLI": str(self.stub(0, "yes"))})
        self.assertEqual(accepted.returncode, 0)

    def test_hook_mode_never_blocks_for_unregistered_repos_or_a_down_server(self):
        def not_registered(url, token):
            raise cli.NotRegisteredError("no")

        def down(url, token):
            raise cli.ServerUnavailableError("down")

        env = {"CI_SCOPE_URL": "https://ci.example", "CI_SCOPE_CONFIG_TOKEN": "t"}
        with mock.patch.dict(os.environ, env):
            self.assertEqual(cli.main(["--hook", "--root", str(self.repo)], fetch=not_registered), 0)
            self.assertEqual(cli.main(["--hook", "--root", str(self.repo)], fetch=down), 0)
            self.assertEqual(cli.main(["--root", str(self.repo)], fetch=down), 2)
            self.assertEqual(cli.main(["--root", str(self.repo)], fetch=not_registered), 2)


if __name__ == "__main__":
    unittest.main()
