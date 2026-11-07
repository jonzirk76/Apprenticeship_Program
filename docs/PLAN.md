# MVP design and implementation plan

Use a single Python process, argparse, SQLite, urllib, and the Git CLI. There are
no runtime packages, background agents, remote mutations, or repository execution.
The optional model adapter speaks a configurable chat-completions JSON protocol;
no model account is needed for discovery or preparation.

1. Implement bounded public GitHub GET requests, caching, retry/rate-limit errors,
   repository evidence collection, transparent qualification, and ranking.
2. Persist raw observations separately from heuristic/model assessments. Add
   selection and a small session state machine (librarian, mentor, reviewer).
3. Generate reference-only preparation packets from public repository trees,
   contribution/build instructions, and official documentation.
4. Accept explicit patches or read-only Git diffs. Support conservative local
   checks, optional model review, strict output validation, and local history.
5. Exercise the core behavior with offline unittest fixtures, then demonstrate
   discovery and preparation against real public issues. Document limitations.

## Data model

- `issues`: repository, number, URL, title, latest observed public API evidence,
  retrieval timestamp, and discovery history in `events`.
- `assessments`: append-only heuristic/model estimates, score, eligibility,
  reasons, uncertainty, and timestamp; never written into observed metadata.
- `sessions`: selected issue, assistance level, workflow status, and completion
  declaration. Selection is local and does not reserve a GitHub issue.
- `packets`, `reviews`: append-only generated artifacts with source timestamps,
  scope/limitations, patch hash (not patch content), and structured findings.
- `events`: local status reports, time, skills, feedback, documentation consulted,
  difficulties, assistance changes, and public evidence links. Self-report is
  distinguished from externally verified evidence; MVP does not verify PR status.
- `http_cache`: bounded-age API responses. Selection always rechecks availability.

## CLI

`discover`, `candidates`, `select`, `packet`, `mode`, `review`, `record`, `history`.
`packet --preview ID` permits inspecting references before selection and records
the artifact as an explicitly labeled preview event, never a recommendation.
Global options: `--db`, `--offline`. Detailed usage lives in README.md.

## External APIs and dependencies

- GitHub REST: issue search, repository metadata, issue details/comments/timeline,
  default-branch commit, recursive trees, repository contents. Public reads only.
- Optional model endpoint: user-configured URL/model/key environment variables.
  Public issue metadata only for analysis and reference selection. Local patch
  review uses loopback by default; remote transmission requires explicit consent
  and an assertion that the entire diff is public and shareable.
- Python 3.10+, SQLite bundled with Python, Git for `review --repo` only.
- Tests use the standard library. No scraping, embeddings, or frontend.

## Risks and practical limits

- Search is a bounded sample, not a proof of the five best issues on GitHub.
- Issue scope, framework needs, engagement, and hours are estimates. Recent pushes
  do not establish maintainer receptiveness. Reproduction is always unverified.
- Unassigned does not mean available: inspect bounded comments and linked PRs,
  exclude uncertain/truncated activity, and recheck on selection.
- Contribution policies may live outside recognized paths; users must read them.
  Maintainer response history and prevalence of automated contributions are not
  exhaustively assessed. No claims of guaranteed acceptance or career outcomes.
- Model instructions are not a security boundary. Structured fields, enum-only
  analysis, reference allowlists, no tools, and output checks reduce solution
  leakage, but prose review still requires user judgment.
- Secret detection is conservative and incomplete. No private repository is
  eligible; no patch is sent remotely without explicit per-command action.
- Git diff review lacks the full codebase and execution evidence. Automated
  opinions cannot be promoted to confirmed defects without independent evidence.
- API quotas and failures may yield fewer than five or zero eligible candidates.
