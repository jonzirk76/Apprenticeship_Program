"""CLI boundary: local actions only, explicit assistance and transmission."""

import argparse
import json
import os
import sqlite3
import sys
from subprocess import SubprocessError
from pathlib import Path
from urllib.parse import urlsplit

from .discovery import CONCEPTS, OFFICIAL_DOCS, assess, discover
from .github import APIError, GitHub
from .model import Model, ModelError
from .packet import prepare, render_packet
from .review import git_diff, read_patch, review_patch
from .store import Store


DEFAULT_QUERY = 'language:Python label:bug -label:"breaking-change"'


def bounded_int(low, high):
    def parse(value):
        number = int(value)
        if not low <= number <= high:
            raise argparse.ArgumentTypeError(f"Expected {low} through {high}")
        return number
    return parse


def parser():
    root = argparse.ArgumentParser(description="Independent engineering apprenticeship. Public GitHub reads and local records only.")
    root.add_argument("--db", default=os.environ.get("APPRENTICE_DB", ".apprentice/history.sqlite3"))
    root.add_argument("--offline", action="store_true", help="Use cached GitHub responses only; disables model calls")
    commands = root.add_subparsers(dest="command", required=True)
    search = commands.add_parser("discover", help="Qualify a bounded sample and show up to five candidates")
    search.add_argument("--query", default=DEFAULT_QUERY)
    search.add_argument("--repo", action="append", default=[], help="Restrict to OWNER/NAME (repeatable)")
    search.add_argument("--limit", type=bounded_int(1, 30), default=15, help="Issues examined, not recommendations (max 30)")
    search.add_argument("--top", type=bounded_int(1, 5), default=5)
    search.add_argument("--profile", type=Path, help="JSON with concept_weights using documented concept names")
    search.add_argument("--model", action="store_true", help="Request separate, enum-only model estimates")
    search.add_argument("--json", action="store_true")
    candidates = commands.add_parser("candidates", help="List locally saved candidates; no freshness claim")
    candidates.add_argument("--all", action="store_true", help="Include excluded issues and reasons")
    candidates.add_argument("--json", action="store_true")
    select = commands.add_parser("select", help="Recheck an issue and select it locally; never claims it on GitHub")
    select.add_argument("id", type=int)
    packet = commands.add_parser("packet", help="Create reference-only preparation for the selected issue")
    packet.add_argument("--output", type=Path)
    packet.add_argument("--json", action="store_true")
    packet.add_argument("--model", action="store_true", help="Select from allowlisted public references only")
    packet.add_argument("--preview", type=int, metavar="ID", help="Preview references for any saved candidate without selecting or recommending it")
    mode = commands.add_parser("mode", help="Explicitly set assistance level")
    mode.add_argument("level", choices=["librarian", "mentor", "reviewer"])
    mode.add_argument("--completed", action="store_true", help="Declare your implementation complete")
    review = commands.add_parser("review", help="Review a finished patch without editing or running repository code")
    source = review.add_mutually_exclusive_group(required=True)
    source.add_argument("--patch", type=Path)
    source.add_argument("--repo", type=Path)
    review.add_argument("--staged", action="store_true", help="Read staged Git changes")
    review.add_argument("--base", help="Git revision to compare against, e.g. HEAD")
    review.add_argument("--completed", action="store_true", help="Declare completion and explicitly enter reviewer mode")
    review.add_argument("--model", action="store_true", help="Use the configured model for broader review")
    review.add_argument("--public-patch", action="store_true", help="Declare the entire patch public, nonproprietary, credential-free, and permitted to share")
    review.add_argument("--allow-remote", action="store_true", help="Authorize transmission of this public patch to a remote model")
    review.add_argument("--output", type=Path, help="Write structured JSON")
    record = commands.add_parser("record", help="Record self-reported learning and contribution evidence locally")
    record.add_argument("--kind", required=True, choices=["time", "skill", "documentation", "difficulty", "feedback", "status", "relevance", "reproduction"])
    record.add_argument("--note", default="")
    record.add_argument("--minutes", type=bounded_int(1, 1440))
    record.add_argument("--phase", choices=["investigation", "implementation", "testing", "review"])
    record.add_argument("--skill", action="append", default=[])
    record.add_argument("--proficiency", choices=["exposure", "practicing", "independent"], default="practicing")
    record.add_argument("--status", choices=["attempted", "completed", "pr-submitted", "merged", "rejected", "abandoned"])
    record.add_argument("--url", help="Public documentation, feedback, or contribution evidence link; not automatically verified")
    history = commands.add_parser("history", help="Show local learning events, packets, and reviews as JSON")
    history.add_argument("--output", type=Path)
    return root


def view(issue):
    observed = issue["observed"]
    repo, raw = observed["repository"], observed["issue"]
    return {"id": issue["id"], "repo": issue["repo"], "number": issue["number"],
            "title": issue["title"], "url": issue["url"],
            "observed": {"retrieved_at": issue["retrieved_at"], "state": raw.get("state"),
                         "assignees": [a.get("login") for a in raw.get("assignees", [])],
                         "labels": [x["name"] for x in raw.get("labels", [])],
                         "repository_language": repo.get("language"), "repository_pushed_at": repo.get("pushed_at"),
                         "commit": observed["commit"], "sources": observed["sources"]},
            "estimates": issue["assessment"], "assessment_source": issue["assessment_source"]}


def show_candidates(result, as_json=False):
    public = {**result, "candidates": [view(r) for r in result["candidates"]]}
    if as_json:
        print(json.dumps(public, indent=2))
        return
    print(f"{len(result['candidates'])} recommended from {result['examined']} examined; {result['eligible']} eligible.")
    if not result["candidates"]:
        print("No suitable candidates established. Inspect exclusions or try a narrower, relevant repository.")
    for issue in result["candidates"]:
        a, raw = issue["assessment"], issue["observed"]["issue"]
        print(f"\n[{issue['id']}] {issue['repo']}#{issue['number']}: {issue['title']}\n  {issue['url']}")
        print(f"  Observed {issue['retrieved_at']}: {raw['state']}, {len(raw.get('assignees', []))} assignees; repo language {issue['observed']['repository'].get('language')}.")
        print(f"  Estimates: score {a['score']}/100; {a['difficulty_estimate']}; {a['hours_estimate'][0]}–{a['hours_estimate'][1]} hours.")
        print("  " + "; ".join(a["why"]) + ".")
        print("  Maintainer engagement: " + a["maintainer_engagement_estimate"] + ".")
        print("  Reproduction unverified; framework, scope, documentation quality, and time require your inspection.")
    for warning in result.get("warnings", []):
        print("Warning: " + warning, file=sys.stderr)
    for excluded in result.get("excluded", []):
        print(f"Excluded [{excluded['id']}] {excluded.get('url', '')}: " + "; ".join(excluded["reasons"]))


def write_output(path, content):
    # Avoid accidentally overwriting existing user work or following a symlink.
    if path:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(content)
    else:
        print(content, end="" if content.endswith("\n") else "\n")


def run(args, store):
    if args.offline and getattr(args, "model", False):
        raise ValueError("--offline disables all model calls")
    github = GitHub(store, offline=args.offline)
    model = Model() if getattr(args, "model", False) else None
    if args.command == "discover":
        query = args.query
        for repo in args.repo:
            # Validate before incorporating a repository qualifier into search.
            import re
            if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
                raise ValueError("--repo must be OWNER/NAME")
        if args.repo:
            query += " " + " ".join("repo:" + repo for repo in args.repo)
        weights = None
        if args.profile:
            profile = json.loads(args.profile.read_text(encoding="utf-8"))
            if not isinstance(profile, dict):
                raise ValueError("Profile must be a JSON object containing concept_weights")
            weights = profile.get("concept_weights", {})
            if not isinstance(weights, dict) or any(k not in CONCEPTS or type(v) is not int or not 0 <= v <= 5 for k, v in weights.items()):
                raise ValueError("Profile concept_weights must use documented names and integer values 0–5")
        result = discover(github, store, query, args.limit, args.top, model, weights)
        show_candidates(result, args.json)
        return 0 if result["candidates"] else 2
    if args.command == "candidates":
        issues = store.candidates()
        eligible = [r for r in issues if r["assessment"] and r["assessment"]["eligible"]]
        eligible.sort(key=lambda r: -r["assessment"]["score"])
        excluded = [{"id": r["id"], "url": r["url"], "title": r["title"], "observed_at": r["retrieved_at"],
                     "reasons": r["assessment"]["exclusions"]} for r in issues
                    if args.all and r["assessment"] and not r["assessment"]["eligible"]]
        show_candidates({"candidates": eligible[:5], "examined": len(issues), "eligible": len(eligible),
                         "excluded": excluded, "warnings": ["Saved observations may be stale; select rechecks availability."]}, args.json)
    elif args.command == "select":
        if args.offline:
            raise ValueError("Selection requires an online availability check; cached candidates may be stale")
        issue = store.issue(args.id)
        observed = github.observe(issue["repo"], issue["number"], fresh=True)
        store.observe(observed)
        assessment = assess(observed)
        store.assess(args.id, assessment)
        if not assessment["eligible"]:
            raise ValueError("Issue is no longer qualified: " + "; ".join(assessment["exclusions"]))
        session = store.select(args.id)
        print(f"Selected local issue {args.id}, session {session['id']}. Assistance: librarian. No GitHub reservation was made.")
    elif args.command == "packet":
        issue = store.issue(args.preview) if args.preview is not None else store.issue(store.session()["issue_id"])
        packet = prepare(github, issue, model)
        if args.preview is not None:
            packet["preview_only"] = True
            packet["boundaries"].insert(0, "PREVIEW ONLY: this issue has not been selected or recommended. Check current qualification and availability.")
        content = json.dumps(packet, indent=2) + "\n" if args.json else render_packet(packet)
        write_output(args.output, content)
        if args.preview is not None:
            store.event(issue["id"], "packet-preview", packet)
        else:
            store.artifact("packets", packet)
    elif args.command == "mode":
        session = store.mode(args.level, args.completed)
        print("Assistance: " + session["level"])
        print({"librarian": "Documentation, definitions, and repository navigation only.",
               "mentor": "Conceptual hints and diagnostic questions are permitted. No implementation code or solution steps.",
               "reviewer": "Completed-work review is available. Corrections remain yours to design and implement."}[args.level])
    elif args.command == "review":
        if args.patch and (args.staged or args.base):
            raise ValueError("--staged and --base apply only to --repo")
        session = store.session()
        if args.completed:
            session = store.mode("reviewer", completed=True)
        if session["level"] != "reviewer" or not session["implementation_complete"]:
            raise ValueError("Review requires completed work and explicit reviewer mode: review --completed or mode reviewer --completed")
        patch = read_patch(args.patch) if args.patch else git_diff(args.repo, args.staged, args.base)
        previous = store.db.execute("SELECT data FROM packets WHERE session_id=? ORDER BY id DESC LIMIT 1", (session["id"],)).fetchone()
        references = json.loads(previous["data"])["references"] if previous else []
        issue = store.issue(session["issue_id"])
        references.append({"url": issue["url"], "role": "issue requirements"})
        language = issue["observed"]["repository"].get("language")
        references.extend({"url": url, "role": "language reference"} for _, url in OFFICIAL_DOCS.get(language, []))
        result = review_patch(patch, references, model, args.public_patch, args.allow_remote)
        result["issue_id"] = session["issue_id"]
        write_output(args.output, json.dumps(result, indent=2) + "\n")
        store.artifact("reviews", result)
    elif args.command == "record":
        session = store.session()
        if args.kind == "time" and (args.minutes is None or args.phase is None):
            raise ValueError("Time records require --minutes and --phase")
        if args.kind == "status" and args.status is None:
            raise ValueError("Status records require --status")
        if args.kind == "skill" and not args.skill:
            raise ValueError("Skill records require at least one --skill")
        if args.url:
            parsed = urlsplit(args.url)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("Evidence links must be public HTTPS URLs without embedded credentials")
        data = {"note": args.note, "minutes": args.minutes, "phase": args.phase,
                "skills": args.skill, "proficiency": args.proficiency, "status": args.status,
                "url": args.url, "provenance": "self-reported", "externally_verified": False}
        if args.kind == "status":
            with store.db:
                store.db.execute("UPDATE sessions SET status=?,implementation_complete=? WHERE id=?",
                                 (args.status, int(args.status in {"completed", "pr-submitted", "merged", "rejected"}), session["id"]))
        store.event(session["issue_id"], args.kind, data)
        print("Saved locally as self-reported; linked contribution status is not independently verified.")
    elif args.command == "history":
        write_output(args.output, json.dumps(store.history(), indent=2) + "\n")
    return 0


def main(argv=None):
    args = parser().parse_args(argv)
    store = None
    try:
        store = Store(args.db)
        return run(args, store)
    except (APIError, ModelError, ValueError, OSError, UnicodeError, sqlite3.Error, SubprocessError) as exc:
        print("Error: " + str(exc), file=sys.stderr)
        return 1
    finally:
        if store:
            store.close()
