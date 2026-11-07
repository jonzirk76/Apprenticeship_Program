"""Transparent estimates based on observed evidence, not label promises."""

import re
from datetime import datetime, timezone

from .github import APIError
from .model import ModelError


CONCEPTS = {
    "automated testing": r"\b(test|pytest|regression|reproduc|assert)\w*\b",
    "error handling": r"\b(error|exception|traceback|crash|invalid|overflow)\w*\b",
    "SQL and data modeling": r"\b(sql|sqlite|database|schema|column|transaction|insert|upsert|query|delete where)\w*\b",
    "APIs and integration": r"\b(api|http|request|response|endpoint|client|server)\w*\b",
    "serialization and validation": r"\b(json|csv|serializ|validat|convert|parsing|encoding)\w*\b",
    "compatibility": r"\b(compatib|version|windows|linux|python 3)\w*\b",
    "async and concurrency": r"\b(async|concurren|thread|race|deadlock)\w*\b",
    "CI and packaging": r"\b(packag|install|workflow|ci|pip|build)\w*\b",
}

DEFAULT_WEIGHTS = {
    "automated testing": 5, "error handling": 4, "SQL and data modeling": 4,
    "APIs and integration": 5, "serialization and validation": 4, "compatibility": 3,
    "async and concurrency": 2, "CI and packaging": 4,
}

OFFICIAL_DOCS = {
    "Python": [("Python documentation", "https://docs.python.org/3/"),
               ("Python exceptions", "https://docs.python.org/3/tutorial/errors.html")],
    "C#": [("C# reference", "https://learn.microsoft.com/en-us/dotnet/csharp/language-reference/")],
    "TypeScript": [("TypeScript handbook", "https://www.typescriptlang.org/docs/handbook/intro.html")],
    "JavaScript": [("JavaScript reference", "https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference")],
    "Go": [("Go documentation", "https://go.dev/doc/")],
    "Rust": [("Rust documentation", "https://doc.rust-lang.org/")],
}


def age_days(value, current):
    if not value:
        return 10000
    try:
        return (current - datetime.fromisoformat(value.replace("Z", "+00:00"))).total_seconds() / 86400
    except (ValueError, TypeError):
        return 10000


def assess(observed, current=None, weights=None):
    current = current or datetime.now(timezone.utc)
    issue, repo = observed["issue"], observed["repository"]
    body = issue.get("body") or ""
    text = (issue["title"] + "\n" + body).lower().replace("_", " ")
    labels = [x["name"].lower() for x in issue.get("labels", [])]
    files = observed["files"]
    concepts = [name for name, pattern in CONCEPTS.items() if re.search(pattern, text)]
    repro = bool(re.search(r"```|steps to reproduce|reproducible|traceback|expected.{0,30}actual|reproduction", body, re.I | re.S))
    test_paths = [p for p in files if re.search(r"(^|/)(tests?|specs?)(/|_)|(_test|\.test|\.spec)\.", p, re.I)]
    ci_paths = [p for p in files if p.startswith(".github/workflows/")]
    exclusions = []
    if (re.search(r"^(how\b|can (?:i|we)\b|question\b|help\b|is it possible\b)", issue["title"], re.I)
            or any(re.search(r"^(question|support|enhancement|feature request)$", label) for label in labels)):
        exclusions.append("Appears to be a usage question or feature request rather than a bounded bug")
    bug_signal = (any("bug" in label for label in labels) or
                  re.search(r"\b(bug|incorrect|fails?|failure|crash|error|corrupt|unexpected|overflow|regression|cannot|silent|inconsistent|doesn't|does not)\w*\b", text))
    if not bug_signal:
        exclusions.append("No clear defect report identified; defer feature/support requests")
    if issue.get("state") != "open" or issue.get("locked"):
        exclusions.append("Issue is closed or locked")
    if issue.get("assignees"):
        exclusions.append("Issue is already assigned")
    if repo.get("archived") or repo.get("disabled") or repo.get("private") is not False:
        exclusions.append("Repository is archived, disabled, or not verified public")
    if repo.get("has_pull_requests") is False or repo.get("pull_request_creation_policy", "all") != "all":
        exclusions.append("Repository restricts external pull requests")
    if age_days(repo.get("pushed_at"), current) > 180:
        exclusions.append("No observed repository push within 180 days")
    if observed.get("tree_truncated"):
        exclusions.append("Repository inventory is truncated; evidence is incomplete")
    if not observed.get("activity_complete"):
        exclusions.append("Issue activity is truncated; availability cannot be assessed")
    if not observed.get("contribution_paths"):
        exclusions.append("No contribution guide found in repository inventory")
    if not test_paths:
        exclusions.append("No established tests found in repository inventory")
    if not repro or len(body.strip()) < 100:
        exclusions.append("Insufficient concrete reproduction evidence for this first attempt")
    if any(re.search(r"in.progress|wip|claimed|blocked|needs.discussion|breaking.change|major", label) for label in labels):
        exclusions.append("Labels suggest active work, blocked discussion, or a compatibility-breaking change")
    if not concepts:
        exclusions.append("No clear target engineering concept identified")
    if re.search(r"\b(typo|spelling)\b", issue["title"], re.I):
        exclusions.append("Likely low educational value relative to existing experience")
    if "async and concurrency" in concepts or re.search(r"\b(rewrite|redesign|new backend|distributed|support autoincrement|bundled binary)\b", text):
        exclusions.append("Scope may exceed several focused sessions; defer for manual qualification")
    for comment in observed.get("comments", []):
        # Old claims are still uncertainty; do not silently assume they expired.
        unquoted = "\n".join(x for x in (comment.get("body") or "").splitlines() if not x.lstrip().startswith(">"))
        if re.search(r"\b(i(?:'m| am|’m) working on|i(?:'ll| will|’ll) (?:take|work on)|working on (?:this|a fix)|can i (?:take|work on)|i have (?:a fix|opened a pr))\b", unquoted, re.I):
            exclusions.append("Comments indicate a claim or ongoing work; manual availability check required")
            break
    for event in observed.get("timeline", []):
        linked = event.get("source", {}).get("issue", {})
        if linked.get("pull_request") and linked.get("state") == "open":
            exclusions.append("An open pull request is linked from the issue timeline")
            break
    policy = re.sub(r"\s+", " ", "\n".join(d["content"] for d in observed.get("documents", [])))
    if re.search(r"(?:do not|don't|no|not accept|prohibit|not allowed|must not).{0,100}(?:\bai\b|ai.generated|ai.assist|llm|artificial intelligence)|(?:\bai\b|ai.generated|ai.assist|llm).{0,100}(?:not accepted|prohibited|not allowed|forbidden)", policy, re.I):
        exclusions.append("Contribution policy may restrict AI assistance; resolve policy compatibility first")
    framework_markers = {
        "pytest": any("pytest" in p or p.endswith("conftest.py") for p in files),
        ".NET": any(p.endswith((".csproj", ".sln")) for p in files),
        "Node.js": any(p.endswith("package.json") for p in files),
    }
    frameworks = [k for k, v in framework_markers.items() if v]
    # Estimates deliberately have no precision beyond a broad range.
    hours = [4, 10] if len(concepts) <= 3 else [6, 16]
    difficulty = "moderate" if len(concepts) <= 3 else "moderate to high"
    weights = {**DEFAULT_WEIGHTS, **(weights or {})}
    relevance = sum(weights[c] for c in concepts)
    value_per_hour = relevance / hours[1]
    score = min(100, round(20 + min(40, value_per_hour * 20) + 12 * repro + 8 * bool(test_paths) + 5 * bool(ci_paths)))
    engagement = [c for c in observed.get("comments", []) if c.get("author_association") in {"OWNER", "MEMBER", "COLLABORATOR"}]
    return {"eligible": not exclusions, "score": score if not exclusions else 0,
            "exclusions": list(dict.fromkeys(exclusions)), "concepts": concepts,
            "language_estimate": repo.get("language") or "unknown",
            "framework_estimates": frameworks, "difficulty_estimate": difficulty,
            "hours_estimate": hours, "reproduction_verified": False,
            "documentation_quality_estimate": "contribution guide found; completeness not established",
            "testing_estimate": "Regression testing expected; inspect the linked tests and CI. Commands not executed.",
            "maintainer_engagement_estimate": "uncertain; maintainer-associated comments observed" if engagement else "unknown; repository activity alone does not establish receptiveness",
            "educational_value_estimate": "Practice unfamiliar-codebase investigation and regression testing using existing language/data experience",
            "career_relevance_estimate": "Backend, integration, and automation fundamentals: " + ", ".join(concepts),
            "why": ["Concrete reproduction material is present" if repro else "Reproduction is unclear",
                    f"{len(test_paths)} test paths and {len(ci_paths)} CI workflows observed",
                    "Potential learning targets: " + ", ".join(concepts)],
            "uncertainties": ["Scope and time are estimates; issue has not been reproduced",
                              "Inventory signals do not establish documentation quality or test coverage",
                              "Automated-contribution prevalence and maintainer responsiveness require manual review",
                              "Check linked policies, comments, and availability before starting"],
            "estimated_value_per_hour": round(value_per_hour, 2), "concept_weights": weights}


def discover(github, store, query, limit=20, top=5, model=None, weights=None):
    results, warnings, seen = [], [], set()
    for item in github.search(query, limit):
        repo = item.get("repository_url", "").removeprefix("https://api.github.com/repos/")
        key = (repo, item["number"])
        if key in seen:
            continue
        seen.add(key)
        try:
            observed = github.observe(repo, item["number"])
            issue_id = store.observe(observed)
            assessment = assess(observed, weights=weights)
            store.assess(issue_id, assessment)
            if model and assessment["eligible"]:
                try:
                    ratings = model.analyze(observed, assessment)
                    assessment = {**assessment, "model_estimates": ratings}
                    store.assess(issue_id, assessment, source="heuristic-v1+model:" + model.model)
                except ModelError as exc:
                    warnings.append(f"{repo}#{item['number']}: optional model analysis unavailable: {exc}")
            results.append(store.issue(issue_id))
        except (APIError, ValueError) as exc:
            warnings.append(f"{repo}#{item['number']}: {exc}")
            if "rate limit" in str(exc).lower():
                break
    eligible = [r for r in results if r["assessment"]["eligible"]]
    eligible.sort(key=lambda r: (-r["assessment"]["score"],
                                 -r["assessment"]["estimated_value_per_hour"], r["id"]))
    selected = eligible[:top]
    store.event(None, "discovery", {"query": query, "examined": len(results),
                "recommended_ids": [r["id"] for r in selected], "warnings": warnings})
    return {"candidates": selected, "examined": len(results), "eligible": len(eligible),
            "warnings": warnings, "excluded": [{"id": r["id"], "url": r["url"],
              "title": r["title"], "observed_at": r["retrieved_at"],
              "reasons": r["assessment"]["exclusions"]} for r in results if not r["assessment"]["eligible"]]}
