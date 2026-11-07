# Engineering Apprentice

A small local CLI for finding legitimate open-source work, preparing to investigate
it independently, and reviewing your completed patch. The target is independently
demonstrated engineering competence, not contribution volume.

The application may generate its own code. It never implements the issues it
discovers, edits your contribution, runs repository code, posts comments, claims
issues, forks repositories, or submits PRs.

## Setup

Requires Python 3.10+ with SQLite. Git is needed only for reading a local Git diff.
No runtime packages, account, or model are required for discovery and preparation.

Run directly from this repository:

```sh
python3 -m apprentice --help
python3 -m unittest discover -v
```

Optionally install the `apprentice` entry point in a virtual environment:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/apprentice --help
```

Installation needs setuptools (and may download build tooling). Direct module
execution and tests do not need pip or internet access.

By default records go into `.apprentice/history.sqlite3`, relative to your current
directory. Use `APPRENTICE_DB` or the global `--db /path/to/history.sqlite3` option
for a consistent location across directories. This directory and credential files
are gitignored. Back up the database yourself; local records are not encrypted.

GitHub authentication is optional. If needed, set `GITHUB_TOKEN` using your normal
secret manager or shell environment. Use read-only permissions for public
repositories; never put tokens in command arguments, configuration files, or Git.
The application does not read `gh` credentials or `.env` files.

## Find, choose, and prepare

```sh
python3 -m apprentice discover --repo simonw/sqlite-utils --query 'is:issue -linked:pr' --limit 12
python3 -m apprentice candidates --all
python3 -m apprentice select 1
python3 -m apprentice packet --output preparation.md
```

Replace `1` with a local candidate ID from your actual results. The application
rechecks issue details, comments, and timeline at selection time. Selection is
local; it neither claims an issue nor proves it is available. Read the issue,
maintainer guidance, and linked policies before deciding to attempt it. Public
observations are saved in `.apprentice/demo.sqlite3`; see `docs/DEMO.md`. No real
issue was selected because the live sample did not establish a suitable candidate.

Without `--repo`, discovery searches public Python bugs. Repeat `--repo` to search
several known projects. `--query` supports GitHub issue search syntax; if the value
starts with a minus sign, use `--query=-linked:pr`. Search always appends public,
open, unassigned issue qualifiers. The sample is bounded to 30 issues, with at
most five recommendations. No recommendations is a valid result (exit code 2).
Errors return 1; successful commands return 0.

Qualification uses actual issue content and repository evidence. It excludes
closed/locked/assigned issues, repositories without a push in 180 days, missing
contribution/test evidence, weak reproduction material, apparent ongoing work,
open linked PRs, incomplete inventories/activity, risky scope, and potential AI
policy conflicts. Some eligible issues may still be poor choices. Push recency
is not evidence of review responsiveness; framework and difficulty assessments
are explicitly estimates. A reproducible-looking report has **not** been
reproduced by the application. It never downloads dependencies or runs tests in
the target repository. Repositories that disable pull requests or restrict them
to collaborators are rejected before the remaining repository inspection.

Ranking combines reproduction/test/CI evidence with weighted learning targets
divided by the upper end of estimated hours. Scores are heuristics, not calibrated
probabilities. They do not use stars, PR counts, or promised salary gains. Optional
model ratings are recorded separately and do not override eligibility or ranking.

```sh
python3 -m apprentice discover --repo OWNER/NAME --profile profile.example.json --json
```

`profile.example.json` contains the default concept priorities (integers 0–5).
Adjust them after reflecting on your own experience. The MVP records skill growth
but does not automatically infer proficiency or escalate issue difficulty. Career
priorities and their employer sources are documented in `docs/CAREER_SIGNALS.md`.

A preparation packet contains commit-pinned contribution, build, CI, architecture,
test, and example references, line links into instruction documents, official
language/API documentation, and concept names. File-name relevance is heuristic.
It contains no generated implementation, algorithm, pseudocode, patch, or solution
steps. Repository sources retain retrieval timestamps. Official reference URLs
are clearly marked as references whose page contents were not fetched; match
their versions to repository requirements.

To inspect references before committing to a candidate, use `packet --preview ID`.
Previews work for excluded issues too, are clearly labeled, and do not select or
recommend the issue. They are saved as preview events in local history.

Cached GitHub responses last 15 minutes online. Inspect a saved packet without
network access with `--offline` before the subcommand:

```sh
python3 -m apprentice --offline packet
```

Offline mode forbids selection and model calls. It reports a missing cache entry
instead of quietly accessing the network. Saved candidates can be stale.

## Assistance boundaries

Every new selection starts at **librarian**: documentation, definitions, and
navigation. The CLI is not a general-purpose chat agent. It generates reference
packets and maintains the following explicit assistance state:

```sh
python3 -m apprentice mode mentor
python3 -m apprentice mode librarian
python3 -m apprentice mode reviewer --completed
```

**Mentor** permits conceptual questions and progressively informative hints, with
no issue-specific implementation guidance. **Reviewer** requires an explicit
declaration that your implementation is complete. Changes never occur because of
frustration, time spent, or test failures. The MVP does not implement unrestricted
solution overrides or delegate work to another agent. When using another chat
tool alongside the CLI, you must communicate these boundaries there as well;
this application cannot enforce another tool's behavior.

## Review your finished work

```sh
python3 -m apprentice review --patch /path/to/finished.patch --completed --output review.json
python3 -m apprentice review --repo /path/to/your/checkout --base HEAD --completed
python3 -m apprentice review --repo /path/to/your/checkout --staged --completed
```

Without `--base`, Git reads unstaged changes against the index. `--base HEAD`
includes tracked staged and unstaged changes. Untracked files are excluded;
provide an explicit textual unified patch when needed. External diff helpers,
text conversion, clean/process filters, submodule diffs, and fsmonitor are disabled.
Partial/promisor clones require an explicit patch to avoid automatic object
fetches. No builds, imports, hooks, or tests from the contribution repository are
run. Patches must be UTF-8,
at most 200 KB; binary and metadata-only changes are unsupported.

With no model, review is a **limited structural pass**, checking conflict markers
and statically parsing complete new Python files. It cannot establish behavioral
correctness, security, compatibility, performance, coverage, or repository
conventions. It does not invent findings when none are established.

Each finding has a classification, location, concern, conditions, evidence,
documentation/test references, and source. Classifications are **Confirmed
defect**, **Potential defect**, **Maintainability concern**, and **Style preference**.
Only independent local evidence (currently a new Python file's syntax failure)
can establish a confirmed defect; model opinions cannot. Python syntax evidence
is specific to the interpreter running the application. Review never supplies
replacement code. Patch contents are not saved in history; a SHA-256 digest and
structured findings are saved. Prose findings may describe sensitive behavior,
so keep the local database and exported reviews private when appropriate.

## Optional model interface

Configure a trusted endpoint accepting the chat-completions JSON protocol. No
provider SDK or provider account is bundled. The URL must be the **complete POST
endpoint**, not a base URL:

```sh
export APPRENTICE_MODEL_URL=http://127.0.0.1:8000/v1/chat/completions
export APPRENTICE_MODEL=your-served-model
python3 -m apprentice discover --repo OWNER/NAME --model
python3 -m apprentice packet --model
python3 -m apprentice review --patch finished.patch --completed --model
```

Set `APPRENTICE_MODEL_KEY` through your secret manager if needed. Requests contain
`model`, `temperature`, and `messages`; responses must contain
`choices[0].message.content` as a JSON string. Unsupported or malformed output
fails clearly. No requests are made unless `--model` is supplied. Discovery sends
only public issue text and estimates; packet generation sends public titles and
reference paths. It sends no local files for those operations. Model reference
selection cannot invent URLs or omit policy/build/CI references.

Review sends **only the explicitly supplied diff and public reference metadata**.
Loopback endpoints are allowed by default, including HTTP. You are responsible
for knowing whether your local server forwards requests elsewhere. Remote
endpoints require HTTPS and both per-command flags:

```sh
python3 -m apprentice review --patch public.patch --completed --model --public-patch --allow-remote
```

`--public-patch` declares the **entire diff, including removed/context lines and
file paths**, public, nonproprietary, credential-free, and allowed to share.
`--allow-remote` authorizes sending it to the configured remote endpoint. Do not
use these for private or proprietary code. Known secret patterns block model
transmission even for local models, but detection cannot establish that a patch
is safe. Redirects are refused, including for GitHub, to prevent forwarding
credentials or patch bodies to another endpoint.

Model outputs are untrusted. Analysis accepts only integer ratings. Preparation
accepts only existing reference IDs. Review validates classification, changed
locations, allowed references, prose lengths, and common code/correction patterns.
These checks and the no-solution prompt reduce risk; they cannot prove that prose
will never reveal a solution. Use the deterministic workflow when you need to
avoid generated review prose entirely. Live model behavior requires validation
with your chosen model; automated tests use controlled responses.

## Keep learning records

```sh
python3 -m apprentice record --kind status --status attempted
python3 -m apprentice record --kind time --minutes 45 --phase investigation
python3 -m apprentice record --kind skill --skill 'regression testing' --proficiency practicing
python3 -m apprentice record --kind documentation --url https://docs.python.org/3/library/sqlite3.html
python3 -m apprentice record --kind difficulty --note 'Needed help understanding the test fixtures'
python3 -m apprentice record --kind relevance --note 'Relevant: bounded debugging in familiar data domain'
python3 -m apprentice record --kind reproduction --note 'Reproduced locally in the documented environment'
python3 -m apprentice record --kind status --status completed
python3 -m apprentice record --kind status --status pr-submitted --url https://github.com/OWNER/REPO/pull/NUMBER
python3 -m apprentice record --kind feedback --note 'Maintainer requested compatibility evidence'
python3 -m apprentice history --output history.json
```

Statuses also include `merged`, `rejected`, and `abandoned`. All manually recorded
statuses, proficiency, and evidence links remain **self-reported and externally
unverified**. An unmerged PR is never called accepted work. The MVP does not verify
PR status, summarize proficiency automatically, or claim career readiness.
Append dated skill and difficulty observations to track change over time. History
also retains discovery/relevance, reproduction, investigation versus implementation
time, assistance level, reviews, and maintainer feedback so you can judge usefulness
without using contribution count as the success metric.

## Operational limits

GitHub public access has a shared IP quota of 60 requests/hour without a token;
authenticated access generally has a higher quota. Search has its own rate limit.
Network and server failures retry at most three times; permission/rate-limit
responses stop promptly and report reset/retry metadata. Partial discovery keeps
qualified results and reports warnings; it may produce fewer than five. One issue
can require several requests for comments, timeline, and repository evidence.

The CLI performs no remote mutations and creates no external accounts. It cannot
guarantee maintainer engagement, contribution acceptance, suitability, or salary
outcomes. Automated-contribution prevalence and policies outside recognized
repository documents require manual inspection. See `docs/PLAN.md` for the
architecture/data model and `docs/DEMO.md` for real-issue validation.
