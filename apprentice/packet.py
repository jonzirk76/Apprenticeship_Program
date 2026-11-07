"""Reference-only preparation: no generated implementation advice."""

import re
from urllib.parse import quote

from .discovery import OFFICIAL_DOCS
from .github import APIError
from .store import now


def prepare(github, issue, model=None):
    observed = issue["observed"]
    repo, sha = issue["repo"], observed["commit"]
    files = observed["files"]
    references = []

    def add(path, role, detail):
        url = f"https://github.com/{repo}/blob/{sha}/{quote(path, safe='/')}"
        if not any(r["url"] == url for r in references):
            references.append({"path": path, "role": role, "url": url, "detail": detail,
                               "provenance": "observed repository tree", "commit": sha})

    for doc in observed["documents"]:
        add(doc["path"], "contribution policy", "Read contribution and AI-assistance policies before work.")
    ci_paths = sorted((p for p in files if p.startswith(".github/workflows/")),
                      key=lambda p: (not bool(re.search(r"(test|(^|/)ci[.\-_]|lint)", p, re.I)), p))[:3]
    for path in files:
        low = path.lower()
        if low in {"readme.md", "readme.rst", "readme", "pyproject.toml", "setup.cfg", "tox.ini", "makefile", "package.json", "global.json"}:
            add(path, "build and test instructions", "Use the supported versions and commands documented here; no commands have been executed.")
    for path in ci_paths:
        add(path, "CI configuration", "Authoritative CI environment, dependency, and test commands.")
    # Retrieve a bounded number of instruction documents to provide precise line references.
    docs = list(observed["documents"])
    warnings = []
    for path in files:
        if path.lower() in {"readme.md", "readme.rst"}:
            try:
                docs.append(github.document(repo, path, sha))
            except APIError as exc:
                warnings.append(f"README text unavailable; tree-verified link retained: {exc}")
            break
    sections = []
    for doc in docs:
        for index, line in enumerate(doc["content"].splitlines(), 1):
            if re.search(r"\b(contribut|install|develop|test|build|architecture|ai|llm)\w*\b", line, re.I):
                sections.append({"path": doc["path"], "line": index,
                                 "url": doc["url"] + f"#L{index}", "retrieved_at": doc["retrieved_at"]})
                if len([s for s in sections if s["path"] == doc["path"]]) >= 8:
                    break
    def words(value):
        return {word[:-1] if len(word) > 4 and word.endswith("s") else word
                for word in re.findall(r"[a-z]{3,}", value.lower())}
    terms = words(issue["title"]) - {"the", "with", "when", "from", "does", "should", "instead", "error"}
    def match(path):
        language_suffix = {"Python": ".py", "C#": ".cs", "Go": ".go", "Rust": ".rs"}.get(observed["repository"].get("language"))
        return (-len(terms & words(path)), bool(language_suffix and not path.endswith(language_suffix)), len(path), path)
    tests = [p for p in files if re.search(r"(^|/)(tests?|specs?)(/|_)|(_test|\.test|\.spec)\.", p, re.I)]
    examples = [p for p in files if re.search(r"(^|/)(examples?|samples?)/", p, re.I)]
    architecture = [p for p in files if re.search(r"(architecture|design|internals|contribut|testing|development)", p, re.I)
                    and p.endswith((".md", ".rst"))]
    for paths, role in [(tests, "existing tests"), (examples, "existing examples"), (architecture, "architecture and development")]:
        for path in sorted(paths, key=match)[:3]:
            add(path, role, "Navigation reference selected by path/title overlap; subsystem relevance requires your inspection.")
    language = observed["repository"].get("language")
    official = [{"title": title, "url": url, "provenance": "official reference; page not fetched"}
                for title, url in OFFICIAL_DOCS.get(language, [])]
    concepts = issue["assessment"]["concepts"]
    extra = []
    if "SQL and data modeling" in concepts:
        extra += [("SQLite language reference", "https://www.sqlite.org/lang.html"),
                  ("SQLite transactions", "https://www.sqlite.org/lang_transaction.html")]
        if language == "Python":
            extra.append(("Python sqlite3 API", "https://docs.python.org/3/library/sqlite3.html"))
        if re.search(r"\bfts\w*\b", issue["title"], re.I):
            extra.append(("SQLite FTS5 reference", "https://www.sqlite.org/fts5.html"))
    if "serialization and validation" in concepts and language == "Python":
        extra += [("Python json API", "https://docs.python.org/3/library/json.html"),
                  ("Python csv API", "https://docs.python.org/3/library/csv.html")]
    if "pytest" in issue["assessment"]["framework_estimates"]:
        extra.append(("pytest documentation", "https://docs.pytest.org/en/stable/"))
    for title, url in extra:
        official.append({"title": title, "url": url, "provenance": "official reference; page not fetched"})
    if model:
        chosen = model.references(issue["title"], references)
        references = [references[i] for i in chosen]
    return {"issue_id": issue["id"], "issue_url": issue["url"], "title": issue["title"],
            "created_at": now(), "observed_at": observed["retrieved_at"], "commit": sha,
            "assistance_level": "librarian", "references": references, "instruction_locations": sections,
            "warnings": warnings,
            "official_documentation": official, "background_concepts": concepts,
            "boundaries": ["References and navigation only; no proposed solution or implementation steps.",
                           "Read contribution and AI policies. Policy discovery is not exhaustive.",
                           "Match documentation versions to the repository build configuration.",
                           "Repository code, install scripts, builds, and tests have not been executed.",
                           "Path similarity does not establish that an example or test covers this issue."],
            "sources": observed["sources"] + [{"url": d["url"], "retrieved_at": d["retrieved_at"]} for d in docs]}


def render_packet(packet):
    lines = [f"# Preparation: {packet['title']}", "", f"Issue: {packet['issue_url']}",
             f"Observed: {packet['observed_at']}; pinned commit: `{packet['commit']}`", "",
             "## Repository references", ""]
    if packet.get("preview_only"):
        lines[5:5] = ["**Preview only. This issue was not selected or recommended. Inspect qualification and current availability.**", ""]
    for ref in packet["references"]:
        lines.append(f"- [{ref['path']}]({ref['url']}) — {ref['role']}. {ref['detail']}")
    lines += ["", "## Instruction locations", ""]
    for section in packet["instruction_locations"]:
        lines.append(f"- [{section['path']}, line {section['line']}]({section['url']})")
    lines += ["", "## Official documentation and API references", ""]
    for ref in packet["official_documentation"]:
        lines.append(f"- [{ref['title']}]({ref['url']})")
    lines += ["", "## Background concepts", "", ", ".join(packet["background_concepts"]), "",
              "## Boundaries and uncertainty", ""]
    lines.extend("- " + x for x in packet["boundaries"])
    if packet["warnings"]:
        lines += ["", "## Retrieval limitations", ""]
        lines.extend("- " + x for x in packet["warnings"])
    return "\n".join(lines) + "\n"
