"""Tests for the pytest progress plugin when tests run through xdist workers."""

import contextlib
import io
import os
import unittest
from types import SimpleNamespace as Obj
from unittest import mock

from scripts import ci_scope_activity as activity
from scripts import ci_scope_pytest_progress as plugin


class XdistTotalTests(unittest.TestCase):
    def test_the_total_comes_from_the_workers_collection(self):
        out = io.StringIO()
        with mock.patch.dict(os.environ, {plugin.ENV: "1"}), contextlib.redirect_stdout(out):
            plugin.pytest_configure(Obj())
            plugin.pytest_collection_finish(Obj(items=[]))  # the controller itself collected nothing
            plugin.pytest_xdist_node_collection_finished(["a", "b", "c"])
            plugin.pytest_runtest_logreport(Obj(when="call", outcome="passed", nodeid="a"))
        marks = [m for m in map(activity.parse_marker, out.getvalue().splitlines()) if m]
        self.assertEqual([(m["current"], m["total"]) for m in marks], [(0, 3), (1, 3)])

    def test_a_test_reported_twice_counts_once(self):
        out = io.StringIO()
        with mock.patch.dict(os.environ, {plugin.ENV: "1"}), contextlib.redirect_stdout(out):
            plugin.pytest_configure(Obj())
            plugin.pytest_collection_finish(Obj(items=[1, 2]))
            for _ in range(3):  # a test with subtests reports once per subtest, then once itself
                plugin.pytest_runtest_logreport(Obj(when="call", outcome="passed", nodeid="a"))
        marks = [m for m in map(activity.parse_marker, out.getvalue().splitlines()) if m]
        self.assertEqual([m["current"] for m in marks], [0, 1])


if __name__ == "__main__":
    unittest.main()
