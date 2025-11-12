# Project Overview _(version 0.1.2)_

aiops is a multi-tenant Flask control plane that unifies Git workflows, external issue trackers,
AI-assisted tmux sessions, and Ansible automation. Platform engineers use it to synchronise issues,
triage incidents, and trigger automation tasks without leaving the dashboard. The codebase favours
thin blueprints, well-tested service helpers, and clear separation between configuration, database
models, and provider adapters. Secrets stay in `instance/` and `.env`, while infrastructure assets
live under `ansible/`.

## How Agents Should Work Here

- **CRITICAL: Working Directory Context** — aiops uses **per-user workspaces** for all development work.
  When running in a tmux session, you'll be in your personal workspace at `/home/{username}/workspace/{project}/`
  (e.g., `/home/ivo/workspace/aiops/`). This is where you edit code, commit, and push changes.
  **NEVER modify files in `/home/syseng/aiops` directly**, as that is the running aiops Flask instance.
  Each user has their own isolated workspace with their own git configuration and shell environment.
  Check your current directory with `pwd` if uncertain.
- Always load `AGENTS.override.md` (generated from the UI) for the current issue context before
  changing files.
- Keep request/response handling inside `app/routes/` minimal; push integrations and orchestration
  into `app/services/` with dedicated tests.
- When touching issue provider logic, add provider stubs in `tests/services/issues/`; CI never hits
  real APIs.
- Apply pending migrations before running the server: `.venv/bin/flask --app manage.py db upgrade`
  (missing fields such as `tenants.color` will crash `/admin` otherwise).
- Local maintenance helpers live in `_local.sh` (gitignored). Use `./_local.sh sync-db` (alias
  `pull-db`) to rsync `instance/app.db` from `syseng@dev.floads:/home/syseng/aiops/` or
  `./_local.sh sync-instance` to clone the full `instance/` tree; override host/paths via env vars
  when needed.
- Use the Admin → Settings “tmux Sessions” card to resync tmux windows with DB projects after DB
  restores; it recreates missing windows and prunes orphaned `-p<ID>` sessions.
- Dashboard project cards include branch-aware git controls plus inline forms to checkout/create or
  merge branches; prefer these tools when testing feature branches.
- Admin → Settings now has Codex, Gemini, and Claude CLI cards; use them to install/upgrade
  `codex`, `gemini-cli`, or `claude` instead of running npm manually. Select a user before
  pasting Codex `auth.json` or Gemini `google_accounts.json` / `oauth_creds.json`; aiops stores
  each user's files under `instance/<tool>/user-<id>/` and mirrors them into the corresponding
  CLI directories (`CODEX_CONFIG_DIR/auth.json` for Codex, `GEMINI_CONFIG_DIR/user-<id>/...` for
  Gemini, `CLAUDE_CONFIG_DIR/api_key` for Claude) whenever they save or launch a session so
  credentials stay isolated without manual copies.
- Use the Claude credentials card to save each user's Anthropic API key (stored at
  `instance/claude/user-<id>/api_key`), then aiops copies it into `CLAUDE_CONFIG_DIR/api_key` and
  exports `CLAUDE_CODE_OAUTH_TOKEN` when launching Claude tmux sessions so `claude` can authenticate.
- **Per-User Linux Shell Sessions** — aiops can launch tmux sessions as individual Linux users (e.g., `ivo`, `michael`)
  instead of running all sessions as the Flask app user. This allows each user to have their own home directory,
  shell configurations (.bashrc, .profile), and separate git configs. To enable this:
  1. Set `LINUX_USER_STRATEGY` in `.env` to `"mapping"` or `"direct"` (default: `"mapping"`)
  2. For mapping strategy, define `LINUX_USER_MAPPING` as a JSON dict or Python dict in `config.py`:
     ```python
     LINUX_USER_MAPPING = {
         'ivo@floads.io': 'ivo',
         'michael@floads.io': 'michael',
     }
     ```
  3. For direct strategy, the system tries to use the aiops user's `username` field as the Linux username
  4. Ensure the target Linux users exist on the system: `id ivo` / `id michael`
  5. Set `USE_LOGIN_SHELL=true` (default) to load user configs when spawning shells
  The child process will call `os.setuid()` and `os.setgid()` to switch to the target Linux user before
  executing tmux. Each shell gets its own `HOME`, `USER`, and `LOGNAME` environment variables.
- **Per-User Workspaces** — Each user has their own workspace directory at `/home/{username}/workspace/{project}/`
  where they clone and work on projects. Workspaces must be initialized before use:
  ```bash
  # Initialize workspace for a user and project
  .venv/bin/flask init-workspace --user-email ivo@floads.io --project-id 1
  ```
  Once initialized, tmux sessions automatically start in the user's workspace, and all git operations
  (pull, push, branch management) operate on the user's workspace. The dashboard shows status from
  the logged-in user's workspace. This architecture eliminates permission conflicts and provides
  clean isolation between users.
- Use `make start-dev` during development so Flask auto-reloads changes. The legacy `make start`
  runs detached and will not reload code.
- Prefer built-in CLI commands (`flask version`, `flask sync-issues`, etc.) over ad-hoc scripts so
  teammates can reproduce results.
- During implementation, focus on code changes and skip tests (`make lint` only). Run `make check` before commits; treat style/type errors as blockers. Use `make test-file FILE=tests/test_<area>.py` to test specific modules during development.

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
- Refresh project guidance in `AGENTS.override.md` with `python3 scripts/agent_context.py write --issue <ID> --title "<short blurb>" <<'EOF'`.
- Append new notes for the same issue by rerunning the command with the `append` subcommand.
- Clear the override file between issues with `python3 scripts/agent_context.py clear`.
- Use the "Populate AGENTS.override.md" button next to an issue in the project dashboard to refresh the repository context.
- When you start a Codex session, ask the agent to read `AGENTS.override.md` so it loads the latest instructions before doing work.

## Current Issue Context
<!-- issue-context:start -->

_No issue context populated yet. Use the Populate AGENTS.override.md button to generate it._

<!-- issue-context:end -->
