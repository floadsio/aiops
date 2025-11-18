# aiops Control Panel

> Current release: **0.3.0** (November 2025)

This project provides a Flask-based web UI and CLI that orchestrates multi-tenant source control workspaces, AI-assisted code editing, and infrastructure automation.

## Features
- **Multi-tenant Management** – Manage tenants and associated projects stored in a relational database (SQLite by default).
- **Issue Tracking Integration** – Sync and manage issues from GitHub, GitLab, and Jira with automatic assignment and status updates.
- **Per-User Workspaces** – Isolated workspace directories for each user with their own git configuration and SSH keys.
- **AI-Assisted Development** – Launch AI sessions (Claude Code, Codex, Gemini) directly on issues with automatic context population.
- **Cross-Platform CLI** – Command-line client for macOS and Linux to manage issues, start AI sessions, and attach to remote tmux sessions via SSH.
- **Git Operations** – Clone, update, push repositories, manage branches through web UI or CLI.
- **AI Tool Management** – Install and upgrade AI CLIs (Codex, Gemini, Claude) without shell access via admin settings.
- **Ansible Automation** – Run Ansible jobs via Semaphore to provision remote environments after code updates.
- **Session Management** – List and reuse active AI sessions, attach to remote tmux sessions from your local machine.

## Getting Started
1. Install [uv](https://github.com/astral-sh/uv) (macOS/Linux/OpenBSD/FreeBSD binaries available). Example: `curl -Ls https://astral.sh/uv/install.sh | sh`.
2. Sync dependencies (creates `.venv/` with Python 3.12 by default): `make sync` or `make sync-dev` for contributor tooling. Override the interpreter with `make PYTHON_SPEC=3.13 sync`.
3. (Recommended) Activate the environment for interactive work: `source .venv/bin/activate` (macOS/Linux) or `.venv\Scripts\activate` (Windows). If you skip activation, prefix commands with `.venv/bin/`.
4. Copy `.env.example` to `.env` and adjust values (Git storage path, AI command, etc.).
5. Initialize the database: `.venv/bin/flask --app manage.py db_init`.
6. Apply migrations (run this after every pull that adds migrations): `.venv/bin/flask --app manage.py db upgrade`.
7. Create an admin user: `.venv/bin/flask --app manage.py create-admin`.
8. (Optional) Seed demo data: `.venv/bin/flask --app manage.py seed-data --owner-email <admin email>`.
9. Start the development server: `make start` (listens on http://127.0.0.1:8060 by default).

If you skip step 6 after pulling new code, runtime errors such as
`sqlite3.OperationalError: no such column: tenants.color` will occur whenever features rely on
new fields. Running `flask db upgrade` keeps SQLite/Postgres schemas aligned with the models.

### Keeping Local Runtime Data Private
- Runtime state (SQLite DB, SSH keys, tmux configs) lives under `instance/` and is ignored by git.
- Environment overrides should go in `.env` which is also ignored; copy from `.env.example`.
- If you need to back up or migrate the runtime data, archive the `instance/` directory separately.
- Application logs default to `logs/aiops.log`; adjust `LOG_FILE` in `.env` to relocate them.

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
- `make seed AIOPS_ADMIN_EMAIL=you@example.com` – run migrations and seed default tenants/projects (tenant-alpha, tenant-beta, tenant-gamma).
- `make seed-identities AIOPS_ADMIN_EMAIL=you@example.com [SEED_SOURCE=/path/to/keys]` – import syseng SSH identities (defaults to `~/.ssh/syseng`).
- `.venv/bin/flask --app manage.py seed-identities --owner-email you@example.com` – import syseng SSH key pairs from `~/.ssh/syseng` (or `--source-dir`).
- `make all` – install dev dependencies and start the aiops server.
- `make format` – format Python code (Black-compatible tooling via Ruff).
- `make lint` – run Ruff linting and MyPy.
- `make test` – execute Pytest suite.
- `make check` – run linting, typing, and tests.
- `make start|stop|restart|status` – manage the aiops development server (logs in `/tmp/aiops.log`).
- Dashboard project cards include branch-aware git controls; use the inline branch forms to
  checkout/create feature branches or merge them back into your default branch without leaving aiops.

## CLI Client

The aiops CLI provides a powerful command-line interface for managing issues and AI sessions from your local machine (macOS/Linux).

### Installation

```bash
cd cli
pip install -e .
# or with uv
uv pip install -e .
```

### Configuration

```bash
# Set API URL and authenticate
aiops config set url http://dev.example:5000
aiops config set api_key aiops_your_api_key_here

# Verify authentication
aiops auth whoami
```

### Common Commands

```bash
# List issues
aiops issues list

# Start AI session on an issue (claims, starts session, populates context)
aiops issues work 501 --tool claude

# Start AI session without an issue
aiops issues start --project aiops --tool shell

# Admin: Start session as another user (for testing/support)
aiops issues start --project aiops --tool codex --user user@example.com

# Start AI session and attach to remote tmux session via SSH
aiops issues work 501 --tool claude --attach

# List active AI sessions for a project
aiops issues sessions --project 1

# Admin: List all users' sessions
aiops issues sessions --all-users

# Attach directly to a running AI session by ID/prefix or tmux target
aiops issues sessions --attach cb3877c65dbd
aiops issues sessions --attach user:aiops-p6

# View issue details
aiops issues view 501

# Database backups (admin only)
aiops system backup create --description "Pre-deployment backup"
aiops system backup list
aiops system backup download <id>
aiops system backup restore <id>
```

### Admin Session Management

Administrators can start and manage sessions as other users for testing, debugging, and support purposes:

```bash
# Start a session as another user (by email or ID)
aiops issues start --project myproject --tool shell --user user@example.com
aiops issues start --project 6 --tool codex --user 5

# View all users' sessions (admin only)
aiops issues sessions --all-users

# Attach to any user's session
aiops issues sessions --attach user:aiops-p6
```

**Key features:**
- Sessions run with the target user's UID, workspace, and SSH keys
- Security: Only admins can use the `--user` flag (non-admins get 403 Forbidden)
- Flexibility: Specify users by email address or database ID
- Auto-attach: Sessions attach by default (use `--no-attach` to skip)
- **Critical functionality**: Thoroughly tested in `tests/test_admin_session_creation.py`

### Remote Session Attachment

The `--attach` flag enables seamless remote development:
1. Derives SSH hostname from your configured API URL
2. Connects as the system user running the Flask app
3. Attaches to the tmux session running your AI tool
4. Automatically populates `AGENTS.override.md` with issue context

Example workflow:
```bash
$ aiops issues work 501 --tool claude --attach
✓ Issue 501 claimed successfully!
✓ AI session started (session ID: eb5b5248f1a0...)
Workspace: /home/<user>/workspace/<tenant>/<project>
Context: AGENTS.override.md populated with issue details

Attaching to tmux session...
[Connected to remote tmux session with Claude Code]
```

Press `Ctrl+B` then `D` to detach and return to your local shell. Run the same command again to re-attach to the existing session.

## AI Console

- Browser sessions default to the `codex` CLI when no tool is selected, falling back to `DEFAULT_AI_SHELL` only if the Codex command is unavailable. By default we run `codex --sandbox danger-full-access --ask-for-approval never` so Codex starts with full permissions; override `CODEX_COMMAND`, `CODEX_SANDBOX_MODE`, or `CODEX_APPROVAL_MODE` in `.env` if you prefer another setup.
- Add Gemini (`gemini-cli`) to `ALLOWED_AI_TOOLS` automatically by setting `GEMINI_COMMAND` (defaults to `gemini`).
- Add Claude (`claude`) to `ALLOWED_AI_TOOLS` by setting `CLAUDE_COMMAND` (defaults to `claude`). Store per-user Anthropic API keys via the admin settings and these keys are exported as `CLAUDE_CODE_OAUTH_TOKEN` before Claude sessions start.
- Use Admin → Settings to check the Claude CLI status and run the `CLAUDE_UPDATE_COMMAND` (default `sudo npm install -g @anthropic-ai/claude-code`) without leaving the browser.
- The AI Tool Maintenance cards on Admin → Settings run the configured npm or Homebrew updates for Codex, Gemini, and Claude. Override `CODEX_UPDATE_COMMAND`, `GEMINI_UPDATE_COMMAND`, and `CLAUDE_UPDATE_COMMAND`, plus optional `CODEX_BREW_PACKAGE`, `GEMINI_BREW_PACKAGE`, or `CLAUDE_BREW_PACKAGE`, in `.env`.
- When tmux is installed, terminals attach to a per-tenant session (`<tenant>-shell`), reusing the same workspace on subsequent launches.
- Configure defaults with `DEFAULT_AI_TOOL` and `DEFAULT_AI_SHELL` in `.env`; toggle multiplexing with `USE_TMUX_FOR_AI_SESSIONS`.
- Use the admin settings cards to install or update Codex (`CODEX_UPDATE_COMMAND`) and Gemini (`GEMINI_UPDATE_COMMAND`) CLIs via npm.
- Paste the required `google_accounts.json` / `oauth_creds.json` payloads into Admin → Settings for each user via the Gemini credentials dropdown; aiops stores the JSON per user under `instance/gemini/user-<id>/` and writes it into their CLI directory (`GEMINI_CONFIG_DIR/user-<id>`, default `~/.gemini/user-<id>`) whenever they save or launch a Gemini session, so authentication persists automatically.
- Paste Codex `auth.json` payloads into the Codex credentials card; aiops keeps per-user copies under `instance/codex/user-<id>/auth.json` and copies the selected user's file into `CODEX_CONFIG_DIR/auth.json` (default `~/.codex/auth.json`) right before launching a Codex tmux session, so credentials never leak between accounts.
- Customize each user's Gemini CLI behavior (default model, UI theme, sandboxing) by editing `settings.json` in the same admin card; aiops mirrors it into `GEMINI_CONFIG_DIR/user-<id>/settings.json` per the [Gemini CLI configuration guide](https://geminicli.com/docs/get-started/configuration/).
- Set `GEMINI_APPROVAL_MODE` (defaults to `auto_edit`) if you want aiops to automatically append `--approval-mode <value>` to the Gemini CLI command; if you provide your own `GEMINI_COMMAND` that already contains the flag, aiops leaves it untouched.
- Ensure Homebrew-installed binaries are picked up by setting `CLI_EXTRA_PATHS` (defaults to `/opt/homebrew/bin:/usr/local/bin`), which aiops prepends to `PATH` whenever it checks or updates Codex, Claude, or Gemini.
- CLI status cards first run the configured `codex`, `gemini`, and `claude` binaries (falling back to npm metadata, or `brew info --json` for Claude) so version checks work whether you installed the tools via Homebrew on macOS or npm on Debian. Override `CLAUDE_BREW_PACKAGE` if you use a different tap name.
- When a tmux window launches with Gemini selected, aiops copies that user's `google_accounts.json` / `oauth_creds.json` (and a safe fallback `settings.json`) into the live CLI directory (`~/.gemini`) before running the command so the official CLI sees the files without relying on any `GEMINI_*` environment overrides.

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
git remote add github https://github.com/exampleorg/aiops.git
git push github main
```

Only tracked application code, tests, and documentation are pushed. Runtime artifacts (`instance/`, `.env`, private keys, etc.) remain local thanks to `.gitignore`. Review custom Ansible inventories or docs before pushing to ensure they do not contain proprietary hostnames or credentials.

## Architecture Overview
- **Flask Application** – handles routes, authentication, and rendering.
- **SQLAlchemy Models** – represent users, tenants, projects, SSH keys, and automation tasks.
- **Services** – encapsulate Git operations, AI assistant invocation, and Ansible execution.
- **Task Queue (Planned)** – placeholder for future asynchronous execution (Celery or RQ).
- **UI Framework** – [Pico CSS](https://picocss.com/) with custom Material Design enhancements
  - Pico CSS provides semantic HTML styling and dark mode support
  - Custom Material Design layer adds elevation shadows, color system, and micro-interactions
  - CSS variables for theming: `--md-primary`, `--md-surface`, `--md-border`, `--shadow-1` through `--shadow-4`
  - Fully responsive with collapsible sidebar navigation
  - All styling lives in `app/templates/base.html` with minimal external dependencies

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
