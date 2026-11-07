# Preparation: FTS detection treats table names as LIKE patterns

Issue: https://github.com/simonw/sqlite-utils/issues/930
Observed: 2026-11-07T12:14:17+00:00; pinned commit: `9c66bafa52ae23d40499c74b0db3b635bcddb876`

**Preview only. This issue was not selected or recommended. Inspect qualification and current availability.**

## Repository references

- [docs/contributing.rst](https://github.com/simonw/sqlite-utils/blob/9c66bafa52ae23d40499c74b0db3b635bcddb876/docs/contributing.rst) — contribution policy. Read contribution and AI-assistance policies before work.
- [README.md](https://github.com/simonw/sqlite-utils/blob/9c66bafa52ae23d40499c74b0db3b635bcddb876/README.md) — build and test instructions. Use the supported versions and commands documented here; no commands have been executed.
- [pyproject.toml](https://github.com/simonw/sqlite-utils/blob/9c66bafa52ae23d40499c74b0db3b635bcddb876/pyproject.toml) — build and test instructions. Use the supported versions and commands documented here; no commands have been executed.
- [.github/workflows/test-coverage.yml](https://github.com/simonw/sqlite-utils/blob/9c66bafa52ae23d40499c74b0db3b635bcddb876/.github/workflows/test-coverage.yml) — CI configuration. Authoritative CI environment, dependency, and test commands.
- [.github/workflows/test-sqlite-support.yml](https://github.com/simonw/sqlite-utils/blob/9c66bafa52ae23d40499c74b0db3b635bcddb876/.github/workflows/test-sqlite-support.yml) — CI configuration. Authoritative CI environment, dependency, and test commands.
- [.github/workflows/test.yml](https://github.com/simonw/sqlite-utils/blob/9c66bafa52ae23d40499c74b0db3b635bcddb876/.github/workflows/test.yml) — CI configuration. Authoritative CI environment, dependency, and test commands.
- [tests/test_fts.py](https://github.com/simonw/sqlite-utils/blob/9c66bafa52ae23d40499c74b0db3b635bcddb876/tests/test_fts.py) — existing tests. Navigation reference selected by path/title overlap; subsystem relevance requires your inspection.
- [tests/test_analyze_tables.py](https://github.com/simonw/sqlite-utils/blob/9c66bafa52ae23d40499c74b0db3b635bcddb876/tests/test_analyze_tables.py) — existing tests. Navigation reference selected by path/title overlap; subsystem relevance requires your inspection.
- [tests/test_create_table_parser.py](https://github.com/simonw/sqlite-utils/blob/9c66bafa52ae23d40499c74b0db3b635bcddb876/tests/test_create_table_parser.py) — existing tests. Navigation reference selected by path/title overlap; subsystem relevance requires your inspection.

## Instruction locations

- [docs/contributing.rst, line 4](https://github.com/simonw/sqlite-utils/blob/9c66bafa52ae23d40499c74b0db3b635bcddb876/docs/contributing.rst#L4)
- [docs/contributing.rst, line 7](https://github.com/simonw/sqlite-utils/blob/9c66bafa52ae23d40499c74b0db3b635bcddb876/docs/contributing.rst#L7)
- [docs/contributing.rst, line 9](https://github.com/simonw/sqlite-utils/blob/9c66bafa52ae23d40499c74b0db3b635bcddb876/docs/contributing.rst#L9)
- [docs/contributing.rst, line 21](https://github.com/simonw/sqlite-utils/blob/9c66bafa52ae23d40499c74b0db3b635bcddb876/docs/contributing.rst#L21)
- [docs/contributing.rst, line 27](https://github.com/simonw/sqlite-utils/blob/9c66bafa52ae23d40499c74b0db3b635bcddb876/docs/contributing.rst#L27)
- [docs/contributing.rst, line 30](https://github.com/simonw/sqlite-utils/blob/9c66bafa52ae23d40499c74b0db3b635bcddb876/docs/contributing.rst#L30)
- [docs/contributing.rst, line 36](https://github.com/simonw/sqlite-utils/blob/9c66bafa52ae23d40499c74b0db3b635bcddb876/docs/contributing.rst#L36)
- [docs/contributing.rst, line 39](https://github.com/simonw/sqlite-utils/blob/9c66bafa52ae23d40499c74b0db3b635bcddb876/docs/contributing.rst#L39)

## Official documentation and API references

- [Python documentation](https://docs.python.org/3/)
- [Python exceptions](https://docs.python.org/3/tutorial/errors.html)
- [SQLite language reference](https://www.sqlite.org/lang.html)
- [SQLite transactions](https://www.sqlite.org/lang_transaction.html)
- [Python sqlite3 API](https://docs.python.org/3/library/sqlite3.html)
- [SQLite FTS5 reference](https://www.sqlite.org/fts5.html)
- [pytest documentation](https://docs.pytest.org/en/stable/)

## Background concepts

automated testing, SQL and data modeling, APIs and integration, compatibility

## Boundaries and uncertainty

- PREVIEW ONLY: this issue has not been selected or recommended. Check current qualification and availability.
- References and navigation only; no proposed solution or implementation steps.
- Read contribution and AI policies. Policy discovery is not exhaustive.
- Match documentation versions to the repository build configuration.
- Repository code, install scripts, builds, and tests have not been executed.
- Path similarity does not establish that an example or test covers this issue.

## Retrieval limitations

- README text unavailable; tree-verified link retained: Offline mode has no cached response for https://api.github.com/repos/simonw/sqlite-utils/contents/README.md?ref=9c66bafa52ae23d40499c74b0db3b635bcddb876
