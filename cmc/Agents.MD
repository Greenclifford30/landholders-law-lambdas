# Agents.MD

Guidance for AI coding agents working in this repository.

## Project

This repository contains Python AWS Lambda handlers for the Chicago Movie Club backend. Each Lambda lives in its own directory with an `app.py` entrypoint and, where needed, a local `requirements.txt`. Shared backend helpers live in `shared/cmc_shared.py`.

## Layout

- `*-lambda/app.py` - Individual Lambda handler implementations.
- `*-lambda/requirements.txt` - Per-Lambda Python dependencies.
- `shared/cmc_shared.py` - Shared backend utilities.
- `tests/` - Cross-Lambda tests.
- `docs/` - Product and handoff notes.
- `scripts/` - Operational helper scripts.

## Commands

- Run focused tests with `python -m pytest <path>`.
- Run all available tests with `python -m pytest`.
- Install dependencies only for the Lambda or test scope being worked on.

## Working Guidelines

- Prefer existing handler structure and shared helper patterns.
- Keep dependency changes local to the Lambda that needs them unless shared behavior requires otherwise.
- Use structured JSON event fixtures already present in Lambda directories when testing handler behavior.
- Keep edits scoped to the requested Lambda or shared helper behavior.
- Use `rg` for searching.
- Do not commit secrets, AWS credentials, deployment artifacts, or local environment files.
