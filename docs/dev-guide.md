# Developer Guide

## Setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
pre-commit install
```

## Running tests

```bash
pytest --cov=turnturnturn
coverage html          # opens htmlcov/index.html
```

## Linting and formatting

All checks run via pre-commit on every commit. To run manually:

```bash
pre-commit run --all-files
```

This covers ruff, black, isort, mypy (strict), and docstring coverage via
interrogate.

## Docstring coverage

TTT uses `interrogate` to enforce docstring coverage on all public API surfaces.
The threshold is set to **80%** in `pyproject.toml` — new public classes and
methods must be documented before they can be committed.

Check coverage manually:

```bash
interrogate src/turnturnturn
```

Generate a coverage badge (written to `docs/assets/`):

```bash
interrogate src/turnturnturn --generate-badge docs/assets/
```

Badge generation is intentionally a manual docs step, not part of the
pre-commit hook path.

## Docs

The documentation site is built from two sources:

1. **Narrative docs** — Markdown files in `docs/` (architecture, lifecycle, guides, this page).
2. **API reference** — Extracted live from docstrings at build time via `mkdocstrings`.

For architecture work, prefer one authoritative home per concern:

- `docs/architecture/bootstrap_lifecycle.md` — mesh/session lifecycle invariants
- `docs/architecture/core_architecture.md` — broader substrate architecture
- docstrings — code-local contract and API behavior

Keep `README.md` brief and link-oriented. Do not duplicate lifecycle narrative there.

Serve locally:

```bash
mkdocs serve
# → http://127.0.0.1:8000
```

Build static site:

```bash
mkdocs build   # output → site/
```

Deploy to GitHub Pages:

```bash
mkdocs gh-deploy
```

Or let CI handle it — see `.github/workflows/docs.yml`.

## Dependency auditing

```bash
safety check
pip-audit
```

## Markdown linting

```bash
markdownlint docs/
```
