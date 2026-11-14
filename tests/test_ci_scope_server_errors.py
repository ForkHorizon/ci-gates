import io
import unittest
import urllib.error
from unittest import mock

from scripts import ci_scope_server as srv


def refusal(code: int, body: bytes) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://ci.test/x", code, "refused", {}, io.BytesIO(body))


class NotFoundMessageTests(unittest.TestCase):
    def fetch_with(self, error):
        with mock.patch("urllib.request.urlopen", side_effect=error):
            return srv.http_fetch("https://ci.test/x", "token")

    def test_missing_config_says_not_registered(self):
        with self.assertRaises(srv.NotRegisteredError) as caught:
            self.fetch_with(refusal(404, b'{"error":"project_config_not_found"}'))
        self.assertIn("not registered", str(caught.exception))

    def test_missing_baseline_does_not_call_a_registered_project_unregistered(self):
        with self.assertRaises(srv.NotRegisteredError) as caught:
            self.fetch_with(refusal(404, b'{"error":"baseline_not_found"}'))
        self.assertIn("registered with CI Scope but has no protected-files baseline", str(caught.exception))
        self.assertNotIn("is not registered", str(caught.exception))

    def test_an_unreadable_404_body_still_means_not_registered(self):
        with self.assertRaises(srv.NotRegisteredError) as caught:
            self.fetch_with(refusal(404, b"<html>"))
        self.assertIn("not registered", str(caught.exception))

    def test_other_statuses_are_still_a_server_problem(self):
        with self.assertRaises(srv.ServerUnavailableError):
            self.fetch_with(refusal(500, b"{}"))
