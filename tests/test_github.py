import os
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from apprentice.github import APIError, GitHub, NoRedirect
from apprentice.store import Store


class GitHubTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / "db")
        self.addCleanup(self.store.close)

    def test_cache_and_offline_prevent_network(self):
        calls = []
        def transport(req):
            calls.append(req)
            return {"ok": True}
        client = GitHub(self.store, transport=transport)
        self.assertEqual(client.get("/test"), {"ok": True})
        self.assertEqual(client.get("/test"), {"ok": True})
        self.assertEqual(len(calls), 1)
        offline = GitHub(self.store, offline=True, transport=lambda _: self.fail("Network accessed"))
        self.assertEqual(offline.get("/test"), {"ok": True})
        with self.assertRaises(APIError):
            offline.get("/uncached")
        with self.assertRaises(APIError):
            offline.get("/test", fresh=True)

    def test_network_failure_retries_are_bounded(self):
        calls, sleeps = [], []
        def transport(req):
            calls.append(req)
            raise URLError("offline")
        client = GitHub(self.store, transport=transport, sleeper=sleeps.append)
        with self.assertRaisesRegex(APIError, "3 attempts"):
            client.get("/test")
        self.assertEqual(len(calls), 3)
        self.assertEqual(sleeps, [1, 2])

    def test_server_failure_retries(self):
        calls = []
        def transport(req):
            calls.append(req)
            if len(calls) < 3:
                raise HTTPError(req.full_url, 503, "unavailable", Message(), None)
            return {"ok": True}
        client = GitHub(self.store, transport=transport, sleeper=lambda _: None)
        self.assertEqual(client.get("/test"), {"ok": True})
        self.assertEqual(len(calls), 3)

    def test_rate_limit_does_not_busy_wait(self):
        headers = Message()
        headers["X-RateLimit-Reset"] = "123"
        def transport(req):
            raise HTTPError(req.full_url, 429, "limited", headers, None)
        with self.assertRaisesRegex(APIError, "reset epoch=123"):
            GitHub(self.store, transport=transport, sleeper=lambda _: self.fail("sleep")).get("/test")

    def test_token_only_in_header_and_requests_get_only(self):
        def transport(req):
            self.assertEqual(req.get_method(), "GET")
            self.assertEqual(req.get_header("Authorization"), "Bearer test-token")
            self.assertNotIn("test-token", req.full_url)
            return {}
        with patch.dict(os.environ, {"GITHUB_TOKEN": "test-token"}):
            client = GitHub(self.store, transport=transport)
            client.get("/test")
            self.assertNotIn("test-token", str(self.store.cache_get(client.base + "/test")))

    def test_arbitrary_urls_and_paths_rejected(self):
        client = GitHub(self.store)
        for path in ("https://other.test/", "//other.test/", "/../secrets"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                client.get(path)
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://other.test"))

    def test_private_repository_blocked_before_tree_access(self):
        calls = []
        def transport(req):
            calls.append(req.full_url)
            return {"private": True}
        with self.assertRaisesRegex(APIError, "public"):
            GitHub(self.store, transport=transport).context("example/private")
        self.assertEqual(len(calls), 1)

    def test_collaborator_only_pull_requests_blocked_before_tree_access(self):
        calls = []
        def transport(req):
            calls.append(req.full_url)
            return {"private": False, "pull_request_creation_policy": "collaborators_only"}
        with self.assertRaisesRegex(APIError, "restricts"):
            GitHub(self.store, transport=transport).context("example/closed-contributions")
        self.assertEqual(len(calls), 1)

    def test_incomplete_search_is_not_a_recommendation(self):
        client = GitHub(self.store, transport=lambda _: {"incomplete_results": True, "items": []})
        with self.assertRaisesRegex(APIError, "incomplete"):
            client.search("test", 5)
