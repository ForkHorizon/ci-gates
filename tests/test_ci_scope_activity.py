import contextlib
import io
import os
import unittest
from unittest import mock

from scripts import ci_scope_run as run


class ActivityTests(unittest.TestCase):
    def say(self, env):
        err = io.StringIO()
        with mock.patch.dict(os.environ, env, clear=True), contextlib.redirect_stderr(err):
            run.announce("lint: python3 /x/code-linter.py")
        return err.getvalue()

    def test_silent_unless_the_agent_asks(self):
        self.assertEqual(self.say({}), "")

    def test_prints_one_marked_line_for_the_agent(self):
        self.assertEqual(self.say({"CI_SCOPE_ACTIVITY": "1"}), "@@activity lint: python3 /x/code-linter.py\n")


if __name__ == "__main__":
    unittest.main()
