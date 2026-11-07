import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from apprentice.cli import main, view
from apprentice.discovery import assess
from apprentice.packet import prepare, render_packet
from apprentice.store import Store
from .support import observation


class StorePacketTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "history.sqlite3"
        self.store = Store(self.path)
        self.addCleanup(self.store.close)
        self.observed = observation()
        self.issue_id = self.store.observe(self.observed)
        self.store.assess(self.issue_id, assess(self.observed))

    def test_observations_estimates_and_history_remain_distinct(self):
        self.store.assess(self.issue_id, {"score": 1}, "model-test")
        issue = self.store.issue(self.issue_id)
        self.assertNotIn("score", issue["observed"])
        self.assertEqual(issue["assessment_source"], "model-test")
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM assessments").fetchone()[0], 2)
        self.assertEqual(self.store.history()["events"][0]["kind"], "observed")

    def test_modes_require_explicit_completion_and_new_session_resets(self):
        self.store.select(self.issue_id)
        self.assertEqual(self.store.session()["level"], "librarian")
        with self.assertRaisesRegex(ValueError, "completed"):
            self.store.mode("reviewer")
        self.store.mode("mentor")
        self.store.mode("reviewer", completed=True)
        self.store.select(self.issue_id)
        self.assertEqual(self.store.session()["level"], "librarian")
        self.assertFalse(self.store.session()["implementation_complete"])

    def test_packet_is_pinned_reference_only_with_precise_locations(self):
        observed = self.observed
        class FakeGitHub:
            def document(self, repo, path, sha):
                return {**observed["documents"][0], "path": path, "content": "# Project\n## Installation\nSee contributing instructions.\n"}
        packet = prepare(FakeGitHub(), self.store.issue(self.issue_id))
        self.assertIn("a" * 40, render_packet(packet))
        self.assertTrue(packet["instruction_locations"])
        self.assertTrue(any(r["role"] == "existing tests" for r in packet["references"]))
        serialized = json.dumps(packet)
        self.assertNotIn(self.observed["issue"]["body"], serialized)
        self.assertNotIn("```", serialized)

    def test_presentation_never_dumps_issue_bodies_or_comments(self):
        result = view(self.store.issue(self.issue_id))
        self.assertNotIn("body", result["observed"])
        self.assertNotIn("comments", result["observed"])

    def test_offline_packet_preview_does_not_select_or_recommend(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["--db", str(self.path), "--offline", "packet", "--preview", str(self.issue_id), "--json"]), 0)
        packet = json.loads(output.getvalue())
        self.assertTrue(packet["preview_only"])
        self.assertTrue(packet["warnings"])
        self.assertTrue(packet["instruction_locations"])
        with self.assertRaises(ValueError):
            self.store.session()
        self.assertEqual(self.store.history()["events"][-1]["kind"], "packet-preview")

    def test_cli_offline_blocks_selection_and_models(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["--db", str(self.path), "--offline", "select", str(self.issue_id)]), 1)
            self.assertEqual(main(["--db", str(self.path), "--offline", "discover", "--model"]), 1)

    def test_review_cli_requires_finished_work_and_never_modifies_patch(self):
        self.store.select(self.issue_id)
        patch_path = Path(self.temp.name) / "change.patch"
        content = "--- /dev/null\n+++ b/example.py\n@@ -0,0 +1 @@\n+value = 1\n"
        patch_path.write_text(content)
        args = ["--db", str(self.path), "review", "--patch", str(patch_path)]
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(args), 1)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(args + ["--completed"]), 0)
        review = json.loads(output.getvalue())
        self.assertEqual(review["findings"], [])
        self.assertFalse(review["patch_stored"])
        self.assertEqual(patch_path.read_text(), content)
        self.assertEqual(len(self.store.history()["reviews"]), 1)

    def test_select_rechecks_availability_instead_of_trusting_saved_ranking(self):
        self.observed["issue"]["assignees"] = [{"login": "another-contributor"}]
        with patch("apprentice.cli.GitHub") as github, contextlib.redirect_stderr(io.StringIO()):
            github.return_value.observe.return_value = self.observed
            self.assertEqual(main(["--db", str(self.path), "select", str(self.issue_id)]), 1)
            github.return_value.observe.assert_called_once_with("example/project", 7, fresh=True)
        with self.assertRaises(ValueError):
            self.store.session()

    def test_cli_selection_packet_and_mode_workflow(self):
        with patch("apprentice.cli.GitHub") as github:
            github.return_value.observe.return_value = self.observed
            github.return_value.document.return_value = self.observed["documents"][0]
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--db", str(self.path), "select", str(self.issue_id)]), 0)
                self.assertEqual(main(["--db", str(self.path), "packet"]), 0)
                self.assertEqual(main(["--db", str(self.path), "mode", "mentor"]), 0)
                self.assertEqual(main(["--db", str(self.path), "record", "--kind", "status", "--status", "attempted"]), 0)
        self.assertEqual(len(self.store.history()["packets"]), 1)
        self.assertEqual(self.store.session()["level"], "mentor")

    def test_packet_prioritizes_testing_workflows_and_short_subsystem_names(self):
        data = self.observed
        data["issue"]["title"] = "FTS detection treats names as patterns"
        data["files"] += ["tests/test_fts.py", ".github/workflows/a-publish.yml"]
        self.store.observe(data)
        class FakeGitHub:
            def document(self, repo, path, sha):
                return data["documents"][0]
        packet = prepare(FakeGitHub(), self.store.issue(self.issue_id))
        tests = [r["path"] for r in packet["references"] if r["role"] == "existing tests"]
        self.assertEqual(tests[0], "tests/test_fts.py")
        workflows = [r["path"] for r in packet["references"] if r["role"] == "CI configuration"]
        self.assertEqual(workflows[0], ".github/workflows/test.yml")

    def test_status_remains_self_reported_not_verified(self):
        self.store.select(self.issue_id)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--db", str(self.path), "record", "--kind", "status", "--status", "merged",
                                   "--url", "https://github.com/example/project/pull/8"]), 0)
        event = self.store.history()["events"][-1]
        self.assertEqual(event["data"]["provenance"], "self-reported")
        self.assertFalse(event["data"]["externally_verified"])

    def test_output_will_not_overwrite_user_file(self):
        target = Path(self.temp.name) / "history.json"
        target.write_text("user content")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["--db", str(self.path), "history", "--output", str(target)]), 1)
        self.assertEqual(target.read_text(), "user content")
