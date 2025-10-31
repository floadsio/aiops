# aiops Control Panel

This project provides a Flask-based web UI that orchestrates multi-tenant source control workspaces, AI-assisted code editing, and infrastructure automation.

## Features
- Manage tenants and associated projects stored in a relational database (SQLite by default).
- Register SSH keys per user to authenticate against remote Git repositories.
- Clone, update, and push Git repositories through the web UI.
- Trigger AI assistants (Codex or Aider) against checked-out code via task runners.
- Run Ansible jobs via Semaphore to provision remote environments after code updates.
- Launch browser terminals that default to the Codex CLI and reuse tmux sessions per tenant for continuity.

## Getting Started
1. Install [uv](https://github.com/astral-sh/uv) (macOS/Linux/OpenBSD/FreeBSD binaries available). Example: `curl -Ls https://astral.sh/uv/install.sh | sh`.
2. Sync dependencies (creates `.venv/` with Python 3.12 by default): `make sync` or `make sync-dev` for contributor tooling. Override the interpreter with `make PYTHON_SPEC=3.13 sync`.
3. (Recommended) Activate the environment for interactive work: `source .venv/bin/activate` (macOS/Linux) or `.venv\Scripts\activate` (Windows). If you skip activation, prefix commands with `.venv/bin/`.
4. Copy `.env.example` to `.env` and adjust values (Git storage path, AI command, etc.).
5. Initialize the database: `.venv/bin/flask --app manage.py db_init`.
6. Create an admin user: `.venv/bin/flask --app manage.py create-admin`.
7. (Optional) Seed demo data: `.venv/bin/flask --app manage.py seed-data --owner-email <admin email>`.
8. Start the development server: `make start` (listens on http://127.0.0.1:8060 by default).

### Keeping Local Runtime Data Private
- Runtime state (SQLite DB, SSH keys, tmux configs) lives under `instance/` and is ignored by git.
- Environment overrides should go in `.env` which is also ignored; copy from `.env.example`.
- If you need to back up or migrate the runtime data, archive the `instance/` directory separately.

### Updating an Existing Deployment
Use the helper script to pull the latest tagged release or main branch while keeping local files:

```bash
./scripts/update.sh
```

By default the script pulls from `origin/main`. Override with environment variables:

```bash
AIOPS_UPDATE_REMOTE=github AIOPS_UPDATE_BRANCH=stable ./scripts/update.sh
```

The script automatically stashes and reapplies local changes (including untracked files) before rebasing.
You can now trigger the same workflow from **Admin → Settings → System Update**. Set
`UPDATE_RESTART_COMMAND` (for example `systemctl restart aiops`) if you want the web UI
to restart the service automatically after a successful update.

## Development Tasks
- `make sync` – create the uv-managed virtualenv (Python 3.12 by default) and install runtime dependencies.
- `make sync-dev` – add development/test extras (override with `make PYTHON_SPEC=3.13 sync-dev`).
- `make seed AIOPS_ADMIN_EMAIL=you@example.com` – run migrations and seed default tenants/projects (dcx, iwf, kbe).
- `make seed-identities AIOPS_ADMIN_EMAIL=you@example.com [SEED_SOURCE=/path/to/keys]` – import syseng SSH identities (defaults to `~/.ssh/syseng`).
- `.venv/bin/flask --app manage.py seed-identities --owner-email you@example.com` – import syseng SSH key pairs from `~/.ssh/syseng` (or `--source-dir`).
- `make all` – install dev dependencies and start the aiops server.
- `make format` – format Python code (Black-compatible tooling via Ruff).
- `make lint` – run Ruff linting and MyPy.
- `make test` – execute Pytest suite.
- `make check` – run linting, typing, and tests.
- `make start|stop|restart|status` – manage the aiops development server (logs in `/tmp/aiops.log`).

## AI Console

- Browser sessions default to the `codex` CLI when no tool is selected, falling back to `DEFAULT_AI_SHELL` only if the Codex command is unavailable.
- When tmux is installed, terminals attach to a per-tenant session (`<tenant>-shell`), reusing the same workspace on subsequent launches.
- Configure defaults with `DEFAULT_AI_TOOL` and `DEFAULT_AI_SHELL` in `.env`; toggle multiplexing with `USE_TMUX_FOR_AI_SESSIONS`.

## Semaphore Integration

Configure aiops to trigger Ansible automation through Semaphore by setting the following environment variables (for local development place them in `.env`):

- `SEMAPHORE_BASE_URL` – Semaphore instance URL, e.g. `https://semaphore.example.com`.
- `SEMAPHORE_API_TOKEN` – API token created under `User > API Keys`.
- `SEMAPHORE_DEFAULT_PROJECT_ID` – optional integer to pre-populate the Semaphore project field in the console.
- `SEMAPHORE_VERIFY_TLS` – set to `false` to skip TLS verification (defaults to `true`; only use for testing).
- `SEMAPHORE_HTTP_TIMEOUT` – per-request timeout in seconds (default `15`).
- `SEMAPHORE_TASK_TIMEOUT` – maximum wait time in seconds for a job to finish (default `600`).
- `SEMAPHORE_POLL_INTERVAL` – seconds between task status checks (default `2`).

After configuring the variables restart the server and open a project. The **Ansible Console** now lists templates fetched from Semaphore; select the template to launch, optionally override arguments, and submit to queue the task remotely.

## GitLab Personal Access Token

Issue synchronization and repository actions against GitLab require a personal access token:

1. Sign in to GitLab, open your avatar menu, and choose **Edit profile** (or **Preferences** on GitLab.com).
2. Select **Access Tokens** (or **Personal Access Tokens**) and create a new token for aiops.
3. Enter a descriptive name, set an expiry date, and grant the `read_api` scope. Add `read_repository`
   and `write_repository` if you plan to push over HTTPS through aiops.
4. Click **Create personal access token** and copy the token value immediately—GitLab will not show it
   again.
5. In aiops, go to **Admin → Integrations**, add a GitLab integration, paste the token, and set the base
   URL (`https://gitlab.com` by default, or your self-hosted domain).

Store the token securely (for example in `.env`) and rotate it if it becomes exposed.

## Publishing to GitHub

To publish the open-source tree:

```bash
git remote add github git@github.com:floadsio/aiops.git
git push github main
```

Only tracked application code, tests, and documentation are pushed. Runtime artifacts (`instance/`, `.env`, private keys, etc.) remain local thanks to `.gitignore`. Review custom Ansible inventories or docs before pushing to ensure they do not contain proprietary hostnames or credentials.

## Architecture Overview
- **Flask Application** – handles routes, authentication, and rendering.
- **SQLAlchemy Models** – represent users, tenants, projects, SSH keys, and automation tasks.
- **Services** – encapsulate Git operations, AI assistant invocation, and Ansible execution.
- **Task Queue (Planned)** – placeholder for future asynchronous execution (Celery or RQ).

## Roadmap
- Integrate background task processing for long-running AI and Ansible jobs.
- Expand role-based access controls beyond the built-in admin role.
- Enhance audit logging and execution history for compliance.
- Add real-time status updates via WebSockets or Server-Sent Events.

## SSH Access
- Register public SSH keys via the admin UI (`/admin/ssh-keys`) for auditing and ownership tracking.
- Seed syseng key material with `.venv/bin/flask --app manage.py seed-identities --owner-email you@example.com` to copy private keys into `instance/keys/` and register them per tenant.
- Private keys remain on disk only; ensure filesystem permissions restrict access (the importer sets `chmod 600`). Configure runtime access (e.g., `ssh-agent`, `GIT_SSH_COMMAND`) if you prefer not to rely on the copied files.
- Ensure the process owner that runs `make start` has access to the required private key material before triggering repository operations.
