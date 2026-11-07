from datetime import datetime, timezone


def observation():
    return {
        "repository": {"full_name": "example/project", "private": False, "visibility": "public",
                       "archived": False, "disabled": False, "language": "Python",
                       "pushed_at": datetime.now(timezone.utc).isoformat()},
        "issue": {"number": 7, "title": "CSV conversion raises unexpected error",
                  "html_url": "https://github.com/example/project/issues/7", "state": "open",
                  "locked": False, "assignees": [], "labels": [{"name": "bug"}], "comments": 0,
                  "body": "Steps to reproduce: a CSV import with a blank field raises an exception. "
                          "Expected: the documented validation behavior. Actual: traceback during conversion. "
                          "A small input is included in the reproduction."},
        "files": ["CONTRIBUTING.md", "README.md", "pyproject.toml", "tests/test_csv.py",
                  "tests/conftest.py", "examples/import_csv.py", "docs/architecture.md", ".github/workflows/test.yml"],
        "commit": "a" * 40, "tree_truncated": False, "contribution_paths": ["CONTRIBUTING.md"],
        "documents": [{"path": "CONTRIBUTING.md", "content": "# Contributing\n## Tests\nUse the documented environment.\n",
                       "url": "https://github.com/example/project/blob/" + "a" * 40 + "/CONTRIBUTING.md",
                       "retrieved_at": "2026-11-07T12:00:00+00:00"}],
        "comments": [], "timeline": [], "activity_complete": True,
        "retrieved_at": "2026-11-07T12:00:00+00:00",
        "sources": [{"url": "https://api.github.com/repos/example/project/issues/7", "retrieved_at": "2026-11-07T12:00:00+00:00"}],
    }
