# TurnTurnTurn

[![CI](https://github.com/dr-arioso/TurnTurnTurn/actions/workflows/ci.yml/badge.svg)](https://github.com/dr-arioso/TurnTurnTurn/actions) [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT) [![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-blue.svg)](https://www.python.org/downloads/)

Minimal scaffold for TurnTurnTurn.

Requirements:
- Python 3.12

Usage:

Create and activate virtualenv:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

Run the package:

```bash
python -m turnturnturn
```

**Developer tools**

- Run the test suite with coverage:

  ```bash
  pytest --cov=turnturnturn
  coverage html
  ```

- Run `ruff`, `black`, `isort`, `mypy` etc. via pre-commit:

  ```bash
  pre-commit install
  pre-commit run --all-files
  ```

- Audit dependencies:

  ```bash
  safety check
  pip-audit
  ```

- Lint markdown:

  ```bash
  markdownlint README.md
  ```
