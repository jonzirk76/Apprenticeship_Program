# Live public-data validation

Performed November 7, 2026. The CLI made only unauthenticated GET requests to
GitHub's official REST API. No accounts were created and no remote state changed.
No contribution implementation or repository test execution took place.

## What was actually demonstrated

1. Public issue discovery and repository inspection ran against
   `simonw/sqlite-utils`, recording **22 distinct issue observations** across
   bounded searches. Raw API evidence, source URLs, retrieval timestamps, and
   append-only assessments are stored locally in `.apprentice/demo.sqlite3`
   (gitignored; available in this workspace).
2. Qualification rejected occupied issues and unsuitable reports. A real usage
   question with a traceback exposed a heuristic false positive. A regression
   test and explicit support-question exclusion corrected that behavior.
3. A search in `pallets/click` exposed a further repository-level restriction:
   `pull_request_creation_policy` is `collaborators_only`. The application now
   rejects that policy before fetching repository trees and issue activity.
4. The anonymous GitHub quota was exhausted. The API returned HTTP 403 and reset
   epoch `1794056804` (November 7, 2026, **8:06:44 a.m. America/New_York**). The CLI
   reported the limit and retained prior observations instead of retrying forever.
5. Cached public observations were reassessed with the final heuristic. The
   result is **zero recommendations**, exported to
   [demo-discovery.json](demo-discovery.json). The export contains issue URLs,
   titles, observation timestamps, and exclusion reasons; no fabricated rankings.
6. A reference-only preparation **preview** was generated for the real issue
   [sqlite-utils #930](https://github.com/simonw/sqlite-utils/issues/930):
   [demo-preparation.md](demo-preparation.md). This issue references an open PR,
   so it was **not selected or recommended**. The preview demonstrates pinned
   documentation, test/CI navigation, official references, and no solution text.
   README text was not cached; that retrieval limitation is reported explicitly.

Examples of why candidates were excluded:

| Public issue | Observed reason or estimated suitability concern |
| --- | --- |
| [#930](https://github.com/simonw/sqlite-utils/issues/930) | Open PR referenced in the timeline |
| [#928](https://github.com/simonw/sqlite-utils/issues/928) | Weak reproduction evidence and open PR reference |
| [#815](https://github.com/simonw/sqlite-utils/issues/815) | Short report lacks concrete reproduction material |
| [#796](https://github.com/simonw/sqlite-utils/issues/796) | Bundled-binary request exceeds the intended initial scope |
| [#651](https://github.com/simonw/sqlite-utils/issues/651) | Usage question, despite including a traceback |

These are time-bounded observations and heuristic estimates. Open PR references
may be indirect; the exclusion is intentionally conservative. No issue was
reproduced, and repository receptiveness or automated-contribution prevalence was
not established. The API quota prevented a fresh suitable selection in another
repository during this validation run.

## Reproduce from the saved cache

From this workspace:

```sh
python3 -m apprentice --db .apprentice/demo.sqlite3 --offline candidates --all --json
python3 -m apprentice --db .apprentice/demo.sqlite3 --offline packet --preview 1
```

The checked-in Markdown and JSON exports remain available when the local database
is absent. They are documentation artifacts, not imported API fixtures.

## Continue toward the first contribution

After the quota resets, or with an existing read-only `GITHUB_TOKEN` configured
securely, search a small relevant repository sample:

```sh
python3 -m apprentice discover --repo pypa/packaging --query 'is:issue -linked:pr' --limit 6
python3 -m apprentice candidates --all
```

This is a next search to evaluate, not a recommendation of an issue or assurance
of that repository's policy compatibility. Read the returned evidence. If an
eligible issue appears, select its actual local ID and generate its packet:

```sh
python3 -m apprentice select ID
python3 -m apprentice packet --output my-preparation.md
```

You then investigate and reproduce it independently. The MVP's **learning success
criterion has not yet been met**: no suitable real issue was selected or attempted.
The application and its offline workflow are implemented; live validation has
demonstrated safe rejection and preparation preview, not a completed first
contribution workflow. A live model review was not attempted because no model
endpoint was configured. Model protocol, consent, and response checks are tested
with controlled responses. The test suite also exercises successful selection,
packet generation, explicit assistance changes, and completed-patch review using
synthetic fixtures. It verifies that Git external diff, clean/process filters,
and automatic lazy fetching cannot run through the Git inspection path.
