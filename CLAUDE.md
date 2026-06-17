# CLAUDE.md

# VibeBuild

Python CLI extending Fedora's Koji build system with automatic dependency resolution for RPM packages. Documentation is in Russian.

## Setup

```bash
pip install -e ".[dev,ml]"
```

## Test

```bash
pytest                          # all tests with coverage
pytest -m unit                  # unit only
pytest -m integration           # integration only (needs koji CLI)
pytest tests/test_analyzer.py   # single file
```

## Lint / Format

```bash
pre-commit run --all-files      # all hooks at once
black --check .                 # formatting (line-length=100)
isort --check .                 # import ordering
flake8                          # linting (max-line-length=100)
mypy vibebuild                  # type checking
```

## Commit Style

[Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/), сообщения **по-английски**, **только subject** (без body/описания), без `Co-Authored-By` и emoji. Допустимые `type`: `feat fix docs style refactor perf test build ci chore revert`. Subject ≤ 100 символов, без точки в конце.

## Architecture

Entry point: `vibebuild/cli.py:main` (console script `vibebuild`)

- `analyzer.py` — SRPM/spec parsing, extracts BuildRequires
- `name_resolver.py` — rule-based RPM name resolution (virtual provides, macros, SRPM mapping)
- `ml_resolver.py` — optional ML fallback (scikit-learn, gated behind `HAS_SKLEARN`)
- `resolver.py` — dependency graph + topological sort via `KojiClient`
- `builder.py` — orchestrates Koji builds with dependency ordering
- `fetcher.py` — downloads SRPMs from Fedora Koji
- `exceptions.py` — hierarchy rooted at `VibeBuildError`

## Key Patterns

- Tests use mocks for koji/subprocess/requests — no real Koji needed for unit tests
- Python 3.9+ compatibility required (use `dict[]` not `Dict[]`, no walrus in 3.9 code)
- Config loaded from `~/.koji/config` and `/etc/koji.conf`

## Directory Layout

```
vibebuild/         # main package
tests/             # pytest tests + fixtures/
docs/              # documentation (Russian)
scripts/           # ML training data scripts
ansible/           # deployment playbooks
dev/koji-server/   # local Docker-based Koji server for testing
```
