import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from apprentice.model import Model, ModelError, contains_secret
from apprentice.review import git_diff, parse_patch, review_patch, validate_model_review


PATCH = "--- a/example.py\n+++ b/example.py\n@@ -1,2 +1,2 @@\n value = 1\n-old = 2\n+new = 3\n"
REFS = [{"url": "https://docs.python.org/3/"}]


class PatchReviewTests(unittest.TestCase):
    def test_changed_line_locations_and_context(self):
        locations, additions, new_files = parse_patch(PATCH)
        self.assertEqual(locations, {"example.py": [2]})
        self.assertEqual(additions["example.py"], {2: "new = 3"})
        self.assertEqual(new_files, set())

    def test_multiple_hunks_and_files(self):
        content = PATCH + "@@ -10 +10 @@\n-previous = 2\n+current = 4\n" + "--- /dev/null\n+++ b/another.py\n@@ -0,0 +1 @@\n+ok = True\n"
        locations, _, new = parse_patch(content)
        self.assertEqual(locations["example.py"], [2, 10])
        self.assertEqual(locations["another.py"], [1])
        self.assertIn("another.py", new)

    def test_deleted_lines_have_precise_old_side_locations(self):
        content = "--- a/obsolete.py\n+++ /dev/null\n@@ -5,2 +0,0 @@\n-first = 1\n-second = 2\n"
        new, _, _, old = parse_patch(content, include_old=True)
        self.assertEqual(new, {})
        self.assertEqual(old, {"obsolete.py": [5, 6]})
        finding = {"classification": "Potential defect", "path": "obsolete.py", "line": 6, "side": "old",
                   "concern": "A public behavior may disappear.", "conditions": "Matters if callers still depend on the removed behavior.",
                   "evidence": "The supplied diff removes this behavior; callers are not shown.", "reference_ids": [0]}
        result = validate_model_review({"summary": "One compatibility concern.", "findings": [finding]}, new, REFS, old)
        self.assertEqual(result[1][0]["side"], "old")
        with self.assertRaises(ModelError):
            validate_model_review({"summary": "One concern.", "findings": [{**finding, "side": "new"}]}, new, REFS, old)

    def test_empty_binary_malformed_and_unsafe_patches_are_rejected(self):
        cases = ["", "Binary files a/a.png and b/a.png differ", "--- a/file\n+++ b/file\n", PATCH[:-9],
                 PATCH.replace("b/example.py", "b/../secret"), PATCH.replace("@@ -1,2 +1,2 @@", "@@ invalid @@")]
        for content in cases:
            with self.subTest(content=content[:40]), self.assertRaises(ValueError):
                parse_patch(content)

    def test_only_complete_new_python_files_get_confirmed_syntax_findings(self):
        new = "--- /dev/null\n+++ b/new.py\n@@ -0,0 +1,2 @@\n+def broken(:\n+    pass\n"
        result = review_patch(new, REFS)
        self.assertEqual(result["findings"][0]["classification"], "Confirmed defect")
        partial = new.replace("--- /dev/null", "--- a/new.py").replace("-0,0", "-1,0")
        self.assertEqual(review_patch(partial, REFS)["findings"], [])
        self.assertFalse(result["patch_stored"])
        self.assertNotIn("def broken", json.dumps(result))

    def test_merge_markers_remain_potential_when_intent_unknown(self):
        content = "--- /dev/null\n+++ b/fixture.txt\n@@ -0,0 +1 @@\n+<<<<<<< branch\n"
        result = review_patch(content, REFS)
        self.assertEqual(result["findings"][0]["classification"], "Potential defect")

    def test_sound_patch_has_no_invented_findings_and_honest_limitations(self):
        result = review_patch(PATCH, REFS)
        self.assertEqual(result["findings"], [])
        self.assertTrue(any("not a full" in x for x in result["limitations"]))

    def test_git_does_not_execute_external_diff_or_modify_files(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            subprocess.run(["git", "init", "-q", directory], check=True)
            source = repo / "sample.txt"
            source.write_text("before\n")
            subprocess.run(["git", "-C", directory, "add", "sample.txt"], check=True)
            source.write_text("after\n")
            marker = repo / "executed"
            script = repo / "external-diff.sh"
            script.write_text("#!/bin/sh\ntouch " + str(marker) + "\n")
            script.chmod(0o700)
            with patch.dict(os.environ, {"GIT_EXTERNAL_DIFF": str(script)}):
                result = git_diff(repo)
            self.assertIn("+after", result)
            self.assertFalse(marker.exists())
            self.assertEqual(source.read_text(), "after\n")
            with self.assertRaises(ValueError):
                git_diff(repo, base="--output=bad")

    def test_git_does_not_execute_clean_or_process_filters(self):
        for setting in ("clean", "process"):
            with self.subTest(setting=setting), tempfile.TemporaryDirectory() as directory:
                repo = Path(directory)
                subprocess.run(["git", "init", "-q", directory], check=True)
                source = repo / "sample.txt"
                source.write_text("before\n")
                subprocess.run(["git", "-C", directory, "add", "sample.txt"], check=True)
                source.write_text("after\n")
                (repo / ".gitattributes").write_text("*.txt filter=untrusted\n")
                marker = repo / "executed"
                script = repo / "filter.sh"
                script.write_text("#!/bin/sh\ntouch '" + str(marker) + "'\ncat\n")
                script.chmod(0o700)
                subprocess.run(["git", "-C", directory, "config", f"filter.untrusted.{setting}", str(script)], check=True)
                subprocess.run(["git", "-C", directory, "config", "filter.untrusted.required", "true"], check=True)
                self.assertIn("+after", git_diff(repo))
                self.assertFalse(marker.exists())

    def test_git_refuses_automatic_lazy_fetch_in_partial_clones(self):
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run(["git", "init", "-q", directory], check=True)
            subprocess.run(["git", "-C", directory, "config", "remote.origin.promisor", "true"], check=True)
            with self.assertRaisesRegex(ValueError, "explicit patch"):
                git_diff(Path(directory))


class ModelBoundaryTests(unittest.TestCase):
    def model(self, response, endpoint="http://127.0.0.1:8000/v1/chat/completions", calls=None):
        def transport(req, timeout=20):
            if calls is not None:
                calls.append(req)
            return {"choices": [{"message": {"content": json.dumps(response)}}]}
        return Model(endpoint, "test-model", transport)

    def test_endpoint_rules(self):
        for endpoint in ("http://example.com/", "https://user:pass@example.com/", "https://example.com/?key=private", "file:///tmp/model"):
            with self.subTest(endpoint=endpoint), self.assertRaises(ModelError):
                Model(endpoint, "test")
        self.assertTrue(Model("http://[::1]:8000/v1/chat/completions", "test").local)

    def test_remote_patch_requires_both_explicit_flags(self):
        calls = []
        model = self.model({"summary": "No findings.", "findings": []}, "https://model.example/v1/chat/completions", calls)
        for public, allowed in ((False, False), (True, False), (False, True)):
            with self.subTest(public=public, allowed=allowed), self.assertRaises(ModelError):
                model.review(PATCH, {"example.py": [2]}, REFS, public, allowed)
        self.assertEqual(calls, [])
        model.review(PATCH, {"example.py": [2]}, REFS, True, True)
        self.assertEqual(len(calls), 1)

    def test_possible_secrets_block_even_loopback(self):
        calls = []
        model = self.model({}, calls=calls)
        secret = "password = 'very-secret-value'"
        self.assertTrue(contains_secret(secret))
        with self.assertRaises(ModelError):
            model.review(secret, {}, REFS)
        with self.assertRaises(ModelError):
            model.ask("test", {"nested": [{"content": secret}]})
        self.assertEqual(calls, [])

    def test_issue_analysis_accepts_only_bounded_integer_ratings(self):
        from .support import observation
        response = {"scope_confidence": 3, "educational_value": 4, "career_relevance": 4}
        self.assertEqual(self.model(response).analyze(observation(), {}), response)
        for bad in ({**response, "solution": "do this"}, {**response, "scope_confidence": True}, {**response, "scope_confidence": 9}):
            with self.subTest(bad=bad), self.assertRaises(ModelError):
                self.model(bad).analyze(observation(), {})

    def test_reference_allowlist_preserves_policies_and_build_instructions(self):
        references = [{"path": "CONTRIBUTING.md", "role": "contribution policy"},
                      {"path": "pyproject.toml", "role": "build and test instructions"},
                      {"path": "tests/test_example.py", "role": "existing tests"}]
        self.assertEqual(self.model({"ids": [2]}).references("issue", references), [0, 1, 2])
        with self.assertRaises(ModelError):
            self.model({"ids": [99]}).references("issue", references)

    def test_review_validation_disallows_fabricated_locations_and_confirmation(self):
        finding = {"classification": "Potential defect", "path": "example.py", "line": 2, "side": "new",
                   "concern": "Failure handling may be incomplete.", "conditions": "Matters if the operation fails.",
                   "evidence": "Failure behavior is not shown in this diff.", "reference_ids": [0]}
        raw = {"summary": "One unverified concern.", "findings": [finding]}
        self.assertEqual(len(validate_model_review(raw, {"example.py": [2]}, REFS)[1]), 1)
        for change in ({"line": 99}, {"path": "unrelated.py"}, {"classification": []}, {"classification": "Confirmed defect"},
                       {"reference_ids": [99]}, {"concern": "```python\nreplace()\n```"}, {"concern": "Replace the validation routine."}):
            with self.subTest(change=change), self.assertRaises(ModelError):
                validate_model_review({"summary": raw["summary"], "findings": [{**finding, **change}]}, {"example.py": [2]}, REFS)

    def test_model_review_can_accept_sound_patch_without_findings(self):
        model = self.model({"summary": "No defects identified within the supplied context.", "findings": []})
        result = review_patch(PATCH, REFS, model=model)
        self.assertEqual(result["findings"], [])
        self.assertEqual(result["engine"], "local+model")

    def test_malformed_model_response_is_rejected(self):
        model = Model("http://localhost:8000/v1/chat/completions", "test", lambda *a, **kw: {})
        with self.assertRaisesRegex(ModelError, "malformed"):
            model.ask("test", {})
