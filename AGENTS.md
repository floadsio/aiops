# Project Overview

aiops is a multi-tenant Flask control plane that unifies Git workflows, external issue trackers,
AI-assisted tmux sessions, and Ansible automation. Platform engineers use it to synchronise issues,
triage incidents, and trigger automation tasks without leaving the dashboard. The codebase favours
thin blueprints, well-tested service helpers, and clear separation between configuration, database
models, and provider adapters. Secrets stay in `instance/` and `.env`, while infrastructure assets
live under `ansible/`.

## How Agents Should Work Here

- Always load `AGENTS.md` (generated from the UI) for the current issue context before
  changing files.
- Keep request/response handling inside `app/routes/` minimal; push integrations and orchestration
  into `app/services/` with dedicated tests.
- When touching issue provider logic, add provider stubs in `tests/services/issues/`; CI never hits
  real APIs.
- Use `make start-dev` during development so Flask auto-reloads changes. The legacy `make start`
  runs detached and will not reload code.
- Prefer built-in CLI commands (`flask version`, `flask sync-issues`, etc.) over ad-hoc scripts so
  teammates can reproduce results.
- Run `make check` (Ruff + MyPy + Pytest) before every commit; treat style/type errors as blockers.

# Repository Guidelines

## Project Structure & Module Organization
The aiops Flask app lives in `app/`, with blueprints in `app/routes/`, forms in `app/forms/`, and shared helpers in `app/services/`. Database models sit in `app/models.py`, configuration glue in `app/config.py` and `app/extensions.py`, and CLI entry points in `manage.py`. Store infrastructure assets under `ansible/playbooks/`, documentation in `docs/`, and keep tests parallel to runtime modules inside `tests/`.

## Build, Test, and Development Commands
Install [uv](https://github.com/astral-sh/uv) and run `make sync` to create the uv-managed `.venv/` (Python 3.12 by default) and install runtime dependencies; `make sync-dev` adds contributor tooling. Core automation: `make format` (Ruff auto-format), `make lint` (Ruff + MyPy), `make test` (Pytest), and `make check` (linting plus tests). Use `make seed AIOPS_ADMIN_EMAIL=<admin@domain>` to migrate and register default tenants/projects, and `make seed-identities AIOPS_ADMIN_EMAIL=<admin@domain> [SEED_SOURCE=/path]` to import syseng SSH material. Run the Flask server with `make start-dev` during development (auto reload) or `make start`/`make stop` for the background runner; logs land in `/tmp/aiops.log`. `make all` bootstraps dependencies and launches the server for local work. Run additional CLI tasks via `.venv/bin/flask ...` or after activating the env.

## Coding Style & Naming Conventions
Follow PEP 8 with 4-space indentation and 100-character lines. Apply `ruff format` before pushing and fix import order with `ruff check --select I --fix`. Treat MyPy warnings as errors and add type hints on new code paths. Modules and functions use snake_case, classes use PascalCase, and constants stay UPPER_SNAKE_CASE. Push complex orchestration into `app/services/` helpers to keep blueprints thin.

## Testing Guidelines
Write Pytest cases alongside the code they cover and collect shared fixtures in `tests/conftest.py`. Name files `test_<area>.py` and use parametrised tests for Git, AI, and Ansible workflows. Target `pytest --cov=app --cov-report=term-missing` coverage of at least 90% on core services, noting any justified gaps in the PR. Place multi-step or slow interactions under `tests/integration/`.

## Commit & Pull Request Guidelines
Use imperative commit subjects like `Add tenant creation form validation`, splitting refactors from features when practical. Before opening a PR, run `make check` and paste the output. Describe motivation, noteworthy implementation details, validation steps, and attach UI or automation evidence when relevant. Link issues and highlight breaking changes in both the PR body and commit message footer.

## Security & Configuration Tips
Keep secrets in `.env` (gitignored) and surface only safe defaults through `.env.example`. Record public SSH keys via the admin UI; when private keys must live with the app, import them with `.venv/bin/flask --app manage.py seed-identities --owner-email <admin@domain>` so they’re copied into `instance/keys/` with `chmod 600`. Review new dependencies for license compliance and known CVEs, recording findings in the PR. When exposing AI or Ansible commands, update the allowlists in `app/config.py` and document production overrides in `docs/`.

## Agent Session Context
- Refresh project guidance in `AGENTS.md` with `python3 scripts/agent_context.py write --issue <ID> --title "<short blurb>" <<'EOF'`.
- Append new notes for the same issue by rerunning the command with the `append` subcommand.
- Clear the file between issues with `python3 scripts/agent_context.py clear`.
- Use the "Populate AGENTS.md" button next to an issue in the project dashboard to refresh the repository context.
- When you start a Codex session, ask the agent to read `AGENTS.md` so it loads the latest instructions before doing work.

## Current Issue Context
<!-- issue-context:start -->

_No issue context populated yet. Use the Populate AGENTS.md button to generate it._

<!-- issue-context:end -->
