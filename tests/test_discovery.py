import copy
import tempfile
import unittest
from pathlib import Path

from apprentice.discovery import assess, discover
from apprentice.store import Store
from .support import observation


class AssessmentTests(unittest.TestCase):
    def setUp(self):
        self.observed = observation()

    def test_concrete_bug_is_eligible_but_reproduction_not_verified(self):
        a = assess(self.observed)
        self.assertTrue(a["eligible"])
        self.assertFalse(a["reproduction_verified"])
        self.assertIn("automated testing", a["concepts"])
        self.assertIn("pytest", a["framework_estimates"])

    def test_good_first_label_is_not_sufficient(self):
        self.observed["issue"]["labels"] = [{"name": "good first issue"}]
        self.observed["issue"]["body"] = "Please make it better"
        self.assertFalse(assess(self.observed)["eligible"])

    def test_usage_question_with_traceback_is_not_a_contribution(self):
        self.observed["issue"]["title"] = "How to insert the vector embeddings values into a table?"
        self.assertFalse(assess(self.observed)["eligible"])

    def test_plain_ai_ban_is_respected(self):
        self.observed["documents"][0]["content"] = "Do not use AI for contributions."
        self.assertFalse(assess(self.observed)["eligible"])

    def test_exclusions(self):
        cases = [
            (lambda o: o["issue"].update(assignees=[{"login": "someone"}]), "assigned"),
            (lambda o: o["issue"].update(state="closed"), "closed"),
            (lambda o: o["repository"].update(archived=True), "archived"),
            (lambda o: o["repository"].update(private=True), "public"),
            (lambda o: o["repository"].update(pushed_at="2020-01-01T00:00:00Z"), "push"),
            (lambda o: o.update(tree_truncated=True), "truncated"),
            (lambda o: o.update(activity_complete=False), "activity"),
            (lambda o: o.update(contribution_paths=[]), "contribution"),
            (lambda o: o.update(files=["README.md"]), "tests"),
            (lambda o: o["issue"].update(labels=[{"name": "in-progress"}]), "Labels"),
            (lambda o: o["comments"].append({"body": "I'm working on this"}), "Comments"),
            (lambda o: o["timeline"].append({"source": {"issue": {"pull_request": {"url": "x"}, "state": "open"}}}), "pull request"),
            (lambda o: o["documents"][0].update(content="We do not accept AI-generated contributions."), "policy"),
        ]
        for change, reason in cases:
            with self.subTest(reason=reason):
                data = copy.deepcopy(self.observed)
                change(data)
                a = assess(data)
                self.assertFalse(a["eligible"])
                self.assertTrue(any(reason in r for r in a["exclusions"]), a)

    def test_closed_linked_pr_does_not_claim_issue(self):
        self.observed["timeline"] = [{"source": {"issue": {"pull_request": {"url": "x"}, "state": "closed"}}}]
        self.assertTrue(assess(self.observed)["eligible"])

    def test_quoted_claim_is_not_a_new_claim(self):
        self.observed["comments"] = [{"body": "> I'm working on this\nIs this still happening?"}]
        self.assertTrue(assess(self.observed)["eligible"])

    def test_configured_concept_weights_affect_ranking(self):
        basic = assess(self.observed, weights={c: 0 for c in assess(self.observed)["concepts"]})
        prioritized = assess(self.observed)
        self.assertGreater(prioritized["score"], basic["score"])

    def test_discovery_returns_up_to_five_and_can_return_none(self):
        data = observation()
        class FakeGitHub:
            def search(self, query, limit):
                return [{"repository_url": "https://api.github.com/repos/example/project", "number": i} for i in range(1, 8)]
            def observe(self, repo, number):
                result = copy.deepcopy(data)
                result["issue"]["number"] = number
                return result
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "db")
            self.addCleanup(store.close)
            result = discover(FakeGitHub(), store, "test")
            self.assertEqual(len(result["candidates"]), 5)
            self.assertEqual(result["examined"], 7)
            data["issue"]["assignees"] = [{"login": "other"}]
            self.assertEqual(discover(FakeGitHub(), store, "test")["candidates"], [])
