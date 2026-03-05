# TurnTurnTurn

[![CI](https://github.com/dr-arioso/TurnTurnTurn/actions/workflows/ci.yml/badge.svg)](https://github.com/dr-arioso/TurnTurnTurn/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-blue.svg)](https://www.python.org/downloads/)

**TurnTurnTurn (TTT)** is a lightweight hub runtime for routing, enriching, and preserving provenance over sequential work items.

TTT is built around a single canonical object:

* **CTO** — Canonical Turn Object

TTT does **not** define domain semantics. It provides:

* authoritative CTO creation
* hub-mediated Delta merge
* typed HubEvents
* Purpose registration and dispatch
* replayable provenance through the event stream

The canonical example profile is **`conversation`**, but TTT is **profile-based**, not hard-coded to speaker/text semantics.

## Core concepts

* **TTT** — the public hub runtime
* **TurnSnargle** — pre-CTO ingress object submitted to TTT
* **CTO** — canonical work item created by TTT
* **Purpose** — registered agenda-bearing actor in the TTT mesh
* **Delta** — purpose-proposed change, merged authoritatively by TTT
* **HubEvent** — authoritative event emitted by TTT

## Status

This project is in active architectural development.
Names, APIs, and module layout are still being refined.

Current design direction:

* TTT is the hub runtime
* `conversation` is the canonical example content profile
* TTT creates CTOs from submitted TurnSnargles
* `cto_created` is the canonical creation event
* Purposes are actors, not per-turn payload wrappers

## Requirements

* Python 3.12+

## Installation

Create and activate a virtual environment:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

## Usage

Run the package:

```bash
python -m turnturnturn
```

## Developer workflow

Run the test suite with coverage:

```bash
pytest --cov=turnturnturn
coverage html
```

Run linting / formatting / type checks via pre-commit:

```bash
pre-commit install
pre-commit run --all-files
```

Audit dependencies:

```bash
safety check
pip-audit
```

Lint markdown:

```bash
markdownlint README.md
```

## Architecture

See:

* `docs/ttt_architecture_v0_15.md`

Primary source modules:

* `src/turnturnturn/hub.py`
* `src/turnturnturn/protocols.py`
* `src/turnturnturn/snargle.py`
* `src/turnturnturn/cto.py`
* `src/turnturnturn/events.py`
* `src/turnturnturn/delta.py`

## License

MIT
