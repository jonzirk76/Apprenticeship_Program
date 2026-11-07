"""Read-only patch review. Findings never contain replacement code."""

import ast
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path, PurePosixPath

from .model import ModelError, prose
from .store import now


CLASSIFICATIONS = {"Confirmed defect", "Potential defect", "Maintainability concern", "Style preference"}
MAX_PATCH_BYTES = 200_000


def read_patch(path):
    with Path(path).open("rb") as stream:
        data = stream.read(MAX_PATCH_BYTES + 1)
    if len(data) > MAX_PATCH_BYTES:
        raise ValueError("Patch exceeds 200 KB; provide a smaller, focused patch")
    return data.decode("utf-8")


def git_diff(repo, staged=False, base=None):
    if base and (base.startswith("-") or not re.fullmatch(r"[A-Za-z0-9_./~^{}@+-]+", base)):
        raise ValueError("Invalid Git base revision")
    env = os.environ.copy()
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES"):
        env.pop(key, None)
    env["GIT_OPTIONAL_LOCKS"] = "0"
    command = ["git", "-c", "core.fsmonitor=false", "-c", "core.pager=cat", "-C", str(Path(repo).resolve())]
    config = subprocess.run(command + ["config", "--null", "--name-only", "--get-regexp",
                             r"^(filter\..*\.(clean|smudge|process|required)|extensions\.partialclone|remote\..*\.promisor)$"],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10, env=env, check=False)
    if config.returncode not in (0, 1):
        raise ValueError("Cannot safely inspect Git configuration; supply an explicit patch")
    for key in config.stdout.decode("utf-8").strip("\0").split("\0"):
        if not key:
            continue
        if key.lower() == "extensions.partialclone" or (key.lower().startswith("remote.") and key.lower().endswith(".promisor")):
            raise ValueError("Partial/promisor clones can fetch objects automatically; supply an explicit patch")
        driver = key.rsplit(".", 1)[0]
        for setting in ("clean=", "smudge=", "process=", "required=false"):
            command += ["-c", driver + "." + setting]
    command += ["diff", "--no-ext-diff", "--no-textconv", "--ignore-submodules=all", "--no-color"]
    if staged:
        command.append("--cached")
    if base:
        command.append(base)
    command.append("--")
    # File-backed output avoids holding arbitrarily large Git output in memory.
    import tempfile
    with tempfile.TemporaryFile() as output:
        result = subprocess.run(command, stdout=output, stderr=subprocess.PIPE, timeout=30, env=env, check=False)
        if result.returncode:
            raise ValueError("Git diff failed. Check repository and base revision.")
        output.seek(0)
        data = output.read(MAX_PATCH_BYTES + 1)
    if len(data) > MAX_PATCH_BYTES:
        raise ValueError("Git diff exceeds 200 KB; provide a focused patch")
    return data.decode("utf-8")


def patch_path(raw, prefix):
    raw = raw.split("\t")[0]
    if raw == "/dev/null":
        return None
    if raw.startswith('"'):
        try:
            raw = json.loads(raw)
        except ValueError:
            raise ValueError("Unsupported quoted patch path") from None
    raw = raw.removeprefix(prefix)
    parts = PurePosixPath(raw)
    if parts.is_absolute() or ".." in parts.parts or not raw or re.search(r"[\x00-\x1f\x7f]", raw):
        raise ValueError("Patch contains an unsafe path")
    return raw


def parse_patch(patch, include_old=False):
    if not patch.strip():
        raise ValueError("Patch is empty. Git diff excludes untracked files; supply a patch explicitly if needed.")
    locations, old_locations, additions, new_files = {}, {}, {}, set()
    path, old_path, remaining_old, remaining_new, new_line, old_line = None, None, 0, 0, 0, 0
    hunk, hunk_count = False, 0
    for line in patch.split("\n"):
        if line.startswith("diff --git "):
            if remaining_old or remaining_new:
                raise ValueError("Truncated patch hunk")
            path, old_path, hunk = None, None, False
        elif not hunk and line.startswith("--- "):
            old_path = patch_path(line[4:], "a/")
        elif not hunk and line.startswith("+++ "):
            path = patch_path(line[4:], "b/")
            if path is None:
                continue
            locations.setdefault(path, [])
            additions.setdefault(path, {})
            if old_path is None:
                new_files.add(path)
        elif line.startswith("@@ "):
            if remaining_old or remaining_new:
                raise ValueError("Truncated patch hunk")
            match = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
            if not match:
                raise ValueError("Malformed unified patch hunk")
            old_start, old_count, new_start, new_count = match.groups()
            remaining_old = int(old_count) if old_count is not None else 1
            remaining_new = int(new_count) if new_count is not None else 1
            new_line, hunk = int(new_start), True
            old_line = int(old_start)
            hunk_count += 1
        elif hunk:
            if line.startswith("\\ No newline"):
                continue
            if not (remaining_old or remaining_new):
                hunk = False
                continue
            if line.startswith("+"):
                if path:
                    locations[path].append(new_line)
                    additions[path][new_line] = line[1:]
                new_line += 1
                remaining_new -= 1
            elif line.startswith("-"):
                if old_path:
                    old_locations.setdefault(old_path, []).append(old_line)
                old_line += 1
                remaining_old -= 1
            elif line.startswith(" "):
                new_line += 1
                old_line += 1
                remaining_old -= 1
                remaining_new -= 1
            else:
                raise ValueError("Malformed unified patch content")
            if remaining_new < 0 or remaining_old < 0:
                raise ValueError("Patch hunk line counts do not match")
            if remaining_new == remaining_old == 0:
                hunk = False
    if remaining_new or remaining_old:
        raise ValueError("Truncated patch hunk")
    if not hunk_count or not (any(locations.values()) or old_locations):
        raise ValueError("Expected a textual unified diff; binary/metadata-only diffs are unsupported")
    if include_old:
        return locations, additions, new_files, old_locations
    return locations, additions, new_files


def validate_model_review(raw, locations, references, old_locations=None):
    if not isinstance(raw, dict) or set(raw) != {"summary", "findings"}:
        raise ModelError("Review response violated schema")
    summary = prose(raw["summary"])
    findings = raw["findings"]
    if not isinstance(findings, list) or len(findings) > 30:
        raise ModelError("Invalid findings list")
    clean = []
    fields = {"classification", "path", "line", "side", "concern", "conditions", "evidence", "reference_ids"}
    for finding in findings:
        if not isinstance(finding, dict) or set(finding) != fields:
            raise ModelError("Review finding violated schema")
        if not isinstance(finding["classification"], str) or finding["classification"] not in CLASSIFICATIONS - {"Confirmed defect"}:
            raise ModelError("Model cannot independently confirm a defect")
        path, line = finding["path"], finding["line"]
        side = finding["side"]
        if side not in ("old", "new"):
            raise ModelError("Finding must identify the old or new side of the diff")
        allowed = (old_locations or {}) if side == "old" else locations
        if not isinstance(path, str) or type(line) is not int or line not in allowed.get(path, []):
            raise ModelError("Finding cites a location outside the supplied changed lines")
        ids = finding["reference_ids"]
        if not isinstance(ids, list) or not ids or any(type(i) is not int or not 0 <= i < len(references) for i in ids):
            raise ModelError("Finding must cite an allowed documentation/test reference")
        clean.append({"classification": finding["classification"], "path": path, "line": line, "side": side,
                      **{key: prose(finding[key]) for key in ("concern", "conditions", "evidence")},
                      "references": [references[i]["url"] for i in ids], "source": "model opinion"})
    return summary, clean


def review_patch(patch, references, model=None, public_patch=False, allow_remote=False):
    if len(patch.encode()) > MAX_PATCH_BYTES:
        raise ValueError("Patch exceeds 200 KB")
    locations, additions, new_files, old_locations = parse_patch(patch, include_old=True)
    findings = []
    for path, lines in additions.items():
        for number, text in lines.items():
            if re.match(r"^(<<<<<<< |=======\s*$|>>>>>>> )", text):
                findings.append({"classification": "Potential defect", "path": path, "line": number, "side": "new",
                                 "concern": "Added text resembles an unresolved merge-conflict marker.",
                                 "conditions": "Matters when this is executable source rather than an intentional fixture or documentation example.",
                                 "evidence": "A conflict-marker pattern appears on an added line; intent is unverified.",
                                 "references": ["https://git-scm.com/docs/git-merge#_how_conflicts_are_presented"],
                                 "source": "local structural check"})
        if path in new_files and path.endswith(".py") and sorted(lines) == list(range(1, len(lines) + 1)):
            try:
                ast.parse("\n".join(lines[i] for i in sorted(lines)) + "\n", filename=path)
            except SyntaxError as exc:
                if exc.lineno in lines:
                    findings.append({"classification": "Confirmed defect", "path": path, "line": exc.lineno, "side": "new",
                                     "concern": "The complete new Python file fails static syntax parsing.",
                                     "conditions": "This file cannot be imported or executed by this Python interpreter; verify the project's target Python version.",
                                     "evidence": f"Python ast.parse raised SyntaxError: {exc.msg}. No code was executed.",
                                     "references": ["https://docs.python.org/3/library/ast.html#ast.parse"],
                                     "source": "local Python parser"})
    summary = "Local structural review completed. No high-confidence defects established." if not findings else "Local structural review found concerns requiring your investigation."
    limitations = ["Review context contains only the supplied diff; no surrounding source files were loaded for review.",
                   "Repository code and tests were not executed; behavior, compatibility, performance, and coverage remain unverified.",
                   "Python syntax checks apply only to complete new Python files and the running interpreter version."]
    if model:
        raw = model.review(patch, locations, references, public_patch, allow_remote, old_locations=old_locations)
        summary, model_findings = validate_model_review(raw, locations, references, old_locations)
        findings.extend(model_findings)
        limitations.append("Model findings are opinions validated for structure and location, not independently confirmed behavior.")
    else:
        limitations.append("No model configured: this is a limited structural pass, not a full correctness or security review. Configure a model for broader adversarial review.")
    return {"created_at": now(), "patch_sha256": hashlib.sha256(patch.encode()).hexdigest(),
            "engine": "local+model" if model else "local-structural", "summary": summary,
            "findings": findings, "limitations": limitations, "locations": locations, "old_locations": old_locations,
            "patch_stored": False, "transmitted_to_model": bool(model)}
