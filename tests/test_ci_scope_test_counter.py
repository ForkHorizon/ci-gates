"""Tests for the generic test-runner counter in ci_scope_activity."""

import unittest

from scripts.ci_scope_activity import TestCounter


def feed_all(lines):
    counter = TestCounter()
    return [counter.feed(line) for line in lines]


class TestCounterTests(unittest.TestCase):
    def test_cargo_counts_against_the_announced_total(self):
        got = feed_all(["running 3 tests", "test a ... ok", "test b ... FAILED"])
        self.assertEqual(
            got[1:],
            [
                {"step": "cargo test", "current": 1, "total": 3},
                {"step": "cargo test", "current": 2, "total": 3},
            ],
        )

    def test_runners_without_a_total_show_only_the_count(self):
        lines = {
            "go test": "--- PASS: TestX (0.00s)",
            "unittest": "test_x (m.C) ... ok",
            "xcodebuild": "Test Case '-[A b]' passed (0.1 seconds).",
            "node test": "ok 1 - foo",
            "swift test": "✔ Test bar() passed after 0.1 seconds.",
        }
        for runner, line in lines.items():
            with self.subTest(runner):
                self.assertEqual(feed_all([line])[0], {"step": runner, "current": 1})

    def test_other_output_is_ignored(self):
        self.assertEqual(feed_all(["....  [ 10%]", "Compiling foo", ""]), [None, None, None])
