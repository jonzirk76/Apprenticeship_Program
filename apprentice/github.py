"""Read-only, public-only GitHub REST access with bounded network work."""

import base64
import json
import os
import re
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .store import now


class APIError(RuntimeError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward credentials or local patch bodies to a redirect target.
        return None


def read_json(request, timeout=20):
    with build_opener(NoRedirect).open(request, timeout=timeout) as response:
        raw = response.read(8_000_001)
        if len(raw) > 8_000_000:
            raise APIError("Response exceeds the 8 MB safety limit")
        try:
            return json.loads(raw)
        except (ValueError, UnicodeDecodeError) as exc:
            raise APIError("Service returned invalid JSON") from exc


class GitHub:
    base = "https://api.github.com"

    def __init__(self, store, offline=False, transport=read_json, sleeper=time.sleep):
        self.store, self.offline = store, offline
        self.transport, self.sleeper = transport, sleeper
        self.sources = {}
        self.contexts = {}

    def get(self, path, params=None, fresh=False):
        if not path.startswith("/") or path.startswith("//") or ".." in path:
            raise ValueError("Expected a GitHub API path")
        url = self.base + path + ("?" + urlencode(params) if params else "")
        cached = self.store.cache_get(url)
        if cached and not fresh:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(cached[1])).total_seconds()
            if self.offline or age < 900:
                self.sources[url] = cached[1]
                return cached[0]
        if self.offline:
            raise APIError("Offline mode has no cached response for " + url)
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "engineering-apprentice/0.1"}
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = "Bearer " + token
        for attempt in range(3):
            try:
                data = self.transport(Request(url, headers=headers, method="GET"))
                self.store.cache_put(url, data)
                self.sources[url] = self.store.cache_get(url)[1]
                return data
            except HTTPError as exc:
                if exc.code in (403, 429):
                    reset = exc.headers.get("X-RateLimit-Reset", "unknown")
                    delay = exc.headers.get("Retry-After", "unknown")
                    raise APIError(f"GitHub denied access or rate limited this request ({exc.code}); "
                                   f"reset epoch={reset}, retry-after={delay}. Retry later or configure GITHUB_TOKEN.") from None
                if exc.code >= 500 and attempt < 2:
                    self.sleeper(2 ** attempt)
                    continue
                raise APIError(f"GitHub HTTP {exc.code}: {url}") from None
            except (URLError, TimeoutError, OSError):
                if attempt < 2:
                    self.sleeper(2 ** attempt)
                    continue
                raise APIError("GitHub network failure after 3 attempts. No remote changes were made.") from None
        raise APIError("GitHub request failed")

    def search(self, query, limit):
        # Force baseline qualifiers even when the user supplies a broader search.
        data = self.get("/search/issues", {"q": query + " is:issue is:open no:assignee is:public",
                        "sort": "updated", "order": "desc", "per_page": limit})
        if data.get("incomplete_results"):
            raise APIError("GitHub returned incomplete search results; narrow the query")
        return data.get("items", [])

    def context(self, repo):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
            raise ValueError("Repository must be OWNER/NAME")
        if repo in self.contexts:
            return self.contexts[repo]
        metadata = self.get(f"/repos/{repo}")
        if metadata.get("private") is not False or metadata.get("visibility", "public") != "public":
            raise APIError("Only verified public repositories are supported")
        if metadata.get("has_pull_requests") is False or metadata.get("pull_request_creation_policy", "all") != "all":
            raise APIError("Repository restricts external pull requests; unsuitable for an independent public contribution")
        branch = metadata["default_branch"]
        commit = self.get(f"/repos/{repo}/commits/{quote(branch, safe='')}")
        sha = commit["sha"]
        tree = self.get(f"/repos/{repo}/git/trees/{sha}", {"recursive": "1"})
        files = [item["path"] for item in tree.get("tree", []) if item.get("type") == "blob"]
        contribution_paths = [p for p in files if p.rsplit("/", 1)[-1].lower() in
                              {"contributing.md", "contributing.rst", "contributing", "contributing.txt"}]
        contribution_paths.sort(key=lambda p: (p.count("/"), len(p)))
        policy_paths = [p for p in files if p.lower() in {"agents.md", ".github/agents.md", "ai_policy.md", ".github/ai_policy.md"}]
        documents = []
        for path in (contribution_paths[:2] + policy_paths[:2]):
            documents.append(self.document(repo, path, sha))
        result = {"repository": metadata, "commit": sha, "files": files,
                  "tree_truncated": tree.get("truncated", False), "documents": documents,
                  "contribution_paths": contribution_paths, "retrieved_at": now()}
        self.contexts[repo] = result
        return result

    def document(self, repo, path, sha):
        data = self.get(f"/repos/{repo}/contents/{quote(path, safe='/')}", {"ref": sha})
        if data.get("encoding") != "base64" or data.get("size", 0) > 200_000:
            raise APIError("Repository document exceeds supported size or encoding")
        try:
            content = base64.b64decode(data["content"], validate=False).decode("utf-8")
        except (ValueError, UnicodeError):
            raise APIError("Repository document is not UTF-8 text") from None
        return {"path": path, "content": content,
                "url": f"https://github.com/{repo}/blob/{sha}/{quote(path, safe='/')}",
                "retrieved_at": self.sources[self.base + f"/repos/{repo}/contents/{quote(path, safe='/')}?" + urlencode({"ref": sha})]}

    def observe(self, repo, number, fresh=False):
        context = self.context(repo)
        issue = self.get(f"/repos/{repo}/issues/{number}", fresh=fresh)
        if "pull_request" in issue:
            raise APIError("Pull requests are not candidate issues")
        comments = self.get(f"/repos/{repo}/issues/{number}/comments", {"per_page": 100}, fresh=fresh) if issue.get("comments") else []
        timeline = self.get(f"/repos/{repo}/issues/{number}/timeline", {"per_page": 100}, fresh=fresh)
        return {**context, "issue": issue, "comments": comments, "timeline": timeline,
                "activity_complete": len(comments) < 100 and len(timeline) < 100,
                "retrieved_at": self.sources[self.base + f"/repos/{repo}/issues/{number}"],
                "assembled_at": now(),
                "sources": [{"url": url, "retrieved_at": ts} for url, ts in self.sources.items()
                            if f"/repos/{repo}/" in url or url == self.base + f"/repos/{repo}"]}
