"""The pytest progress plugin loads in a project that has no pytest-xdist installed."""

import unittest

from scripts import ci_scope_pytest_progress as plugin


class PytestProgressWithoutXdistTests(unittest.TestCase):
    def test_the_xdist_hook_is_optional_so_pytest_without_xdist_accepts_the_plugin(self):
        # A plain xdist hook makes pytest without xdist stop with "unknown hook" before collecting a test.
        self.assertTrue(plugin.pytest_xdist_node_collection_finished.pytest_impl["optionalhook"])


if __name__ == "__main__":
    unittest.main()
