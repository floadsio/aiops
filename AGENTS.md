# Project Overview _(version 0.1.4)_

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

## Sudo Service Architecture

**CRITICAL: All code modifications must be made in your personal workspace** at `/home/{username}/workspace/aiops/`,
NOT in the running Flask instance at `/home/syseng/aiops/`. The running instance is for the Flask application
server only. Always use `pwd` to verify you're in your workspace before editing files.

aiops uses a centralized sudo utility service (`app/services/sudo_service.py`) to execute operations as different
Linux users. This is essential because:
- The Flask app runs as `syseng` but needs to access per-user workspaces
- User workspaces live in `~/workspace/` with restrictive permissions (drwx------)
- Git operations must run with user-specific SSH keys and configurations
- Workspace initialization requires creating directories as the target user

### Available Sudo Functions

Import from `app.services.sudo_service`:

```python
from app.services.sudo_service import (
    SudoError,           # Exception raised on sudo operation failures
    SudoResult,          # Dataclass with returncode, stdout, stderr, success
    run_as_user,         # Execute any command as a different user
    test_path,           # Check if a path exists as a user
    mkdir,               # Create directories as a user
    chown,               # Change file/directory ownership
    chmod,               # Change file/directory permissions
    chgrp,               # Change file/directory group
    rm_rf,               # Recursively remove directories as a user
)
```

### Core Function: run_as_user()

The most flexible function for executing commands as different users:

```python
def run_as_user(
    username: str,                    # Linux username (e.g., "ivo", "michael")
    command: list[str],               # Command and args (e.g., ["git", "status"])
    *,
    timeout: float = 30.0,            # Timeout in seconds
    env: dict[str, str] | None = None,  # Environment variables to pass
    check: bool = True,               # Raise SudoError on failure
    capture_output: bool = True,      # Capture stdout/stderr
) -> SudoResult:
    """Execute a command as a different Linux user via sudo."""
```

**Example Usage:**
```python
# Check git status in user's workspace
result = run_as_user(
    "ivo",
    ["git", "status"],
    timeout=10.0,
)
print(result.stdout)

# Clone repository with SSH environment
result = run_as_user(
    "ivo",
    ["git", "clone", "--branch", "main", repo_url, target_path],
    env={"GIT_SSH_COMMAND": "ssh -i /path/to/key"},
    timeout=300.0,  # 5 minutes for large repos
)

# Run command without raising on failure
result = run_as_user(
    "ivo",
    ["test", "-f", "/some/file"],
    check=False,  # Don't raise if file doesn't exist
)
if result.success:
    print("File exists")
```

### Helper Functions

**test_path()** - Check if a path exists:
```python
if test_path("ivo", "/home/ivo/workspace/aiops/.git"):
    print("Workspace initialized")
```

**mkdir()** - Create directories:
```python
mkdir("ivo", "/home/ivo/workspace/newproject", parents=True)
```

**File Permission Operations:**
```python
# Change ownership
chown("/path/to/file", owner="syseng", group="syseng")
chown("/path/to/file", group="developers")  # Group only

# Change permissions (use octal notation)
chmod("/path/to/file", 0o644)      # -rw-r--r--
chmod("/path/to/dir", 0o755)       # drwxr-xr-x
chmod("/path/to/dir", 0o2775)      # drwxrwsr-x (with setgid)

# Change group
chgrp("/path/to/file", "syseng")
```

**rm_rf()** - Recursive removal:
```python
# Clean up failed clone attempt
try:
    rm_rf("ivo", "/home/ivo/workspace/failed_clone")
except SudoError as e:
    log.warning(f"Cleanup failed: {e}")
```

### Integration with Workspace Service

The `workspace_service.py` uses sudo operations extensively:

```python
from .sudo_service import SudoError, mkdir, rm_rf, run_as_user, test_path

# Check if workspace exists
def workspace_exists(project, user) -> bool:
    workspace_path = get_workspace_path(project, user)
    linux_username = resolve_linux_username(user)

    exists = test_path(linux_username, str(workspace_path))
    has_git = exists and test_path(linux_username, str(workspace_path / ".git"))
    return exists and has_git

# Initialize workspace
def initialize_workspace(project, user) -> Path:
    linux_username = resolve_linux_username(user)
    workspace_path = get_workspace_path(project, user)

    # Create workspace directory
    mkdir(linux_username, str(workspace_path))

    # Clone repository with SSH credentials
    try:
        run_as_user(
            linux_username,
            ["git", "clone", "--branch", branch, repo_url, str(workspace_path)],
            env=build_project_git_env(project),
            timeout=300,
        )
    except SudoError as exc:
        # Cleanup on failure
        if test_path(linux_username, str(workspace_path)):
            rm_rf(linux_username, str(workspace_path), timeout=10)
        raise WorkspaceError(str(exc)) from exc
```

### Error Handling

All sudo functions raise `SudoError` on failure:

```python
from app.services.sudo_service import SudoError

try:
    mkdir("ivo", "/home/ivo/workspace/project")
except SudoError as exc:
    # exc contains detailed error message including stderr
    log.error(f"Failed to create workspace: {exc}")
    # Re-raise as service-specific exception if needed
    raise WorkspaceError(f"Cannot create workspace: {exc}") from exc
```

### Best Practices

1. **Always use sudo utilities instead of raw subprocess calls:**
   ```python
   # ❌ Don't do this
   subprocess.run(["sudo", "-n", "-u", username, "mkdir", "-p", path])

   # ✅ Do this
   mkdir(username, path)
   ```

2. **Set appropriate timeouts:**
   - File operations: 5-10 seconds
   - Directory creation: 10 seconds
   - Git clone: 300 seconds (5 minutes)
   - Git operations: 30-60 seconds

3. **Pass environment variables for git operations:**
   ```python
   env = build_project_git_env(project)  # Gets SSH keys
   run_as_user(username, ["git", "pull"], env=env)
   ```

4. **Check paths via sudo when dealing with restrictive permissions:**
   ```python
   # Direct path.exists() will fail if syseng can't read parent dir
   try:
       exists = workspace_path.exists()
   except PermissionError:
       # Fall back to sudo check
       exists = test_path(linux_username, str(workspace_path))
   ```

5. **Clean up on failures:**
   ```python
   try:
       mkdir(username, workspace_path)
       run_as_user(username, ["git", "clone", ...])
   except SudoError:
       # Remove partial directory
       if test_path(username, workspace_path):
           rm_rf(username, workspace_path)
       raise
   ```

### Sudoers Configuration Requirements

For production deployments, the Flask app user (`syseng`) needs passwordless sudo access:

```bash
# /etc/sudoers.d/aiops
# Allow syseng to run commands as any Linux user without password
syseng ALL=(ALL) NOPASSWD: ALL

# More restrictive option (recommended for production):
# Only allow specific commands for specific users
syseng ALL=(ivo,michael) NOPASSWD: /usr/bin/test, /bin/mkdir, /usr/bin/git, /bin/rm, /bin/chmod, /bin/chgrp, /usr/bin/chown
```

Test sudo configuration:
```bash
# As syseng user, should not prompt for password:
sudo -n -u ivo test -e /home/ivo
```

### Git Safe Directory Configuration

When the Flask app (running as `syseng`) needs to read git repositories owned by other users,
add them to git's safe directory list:

```bash
# As syseng user
sudo -u syseng git config --global --add safe.directory '/home/ivo/workspace/aiops'
sudo -u syseng git config --global --add safe.directory '/home/michael/workspace/aiops'

# Or use wildcard (Git 2.36+)
sudo -u syseng git config --global --add safe.directory '*'
```

This prevents "dubious ownership" errors when GitPython accesses user workspaces.

### Workspace Directory Permissions

For the Flask app to check workspace status, parent directories need execute permissions:

```bash
# Allow directory traversal (doesn't expose file contents)
chmod o+rx /home/ivo
chmod o+rx /home/ivo/workspace

# Workspace itself can remain user-owned
ls -la /home/ivo/workspace/aiops
# drwxrwxr-x 10 ivo ivo 4096 Nov 13 06:16 aiops
```

This allows `syseng` to stat paths and read .git metadata while keeping files secure.

## Issue Management & Status Normalization

aiops aggregates issues from multiple providers (GitHub, GitLab, Jira) and normalizes their statuses for unified filtering and display.

### Status Normalization

The `normalize_issue_status()` function (`app/services/issues/utils.py`) maps provider-specific statuses to standardized keys:

**Open Issues** - Mapped to status key `"open"`:
- GitHub: `open`
- GitLab: `opened` (note the past tense)
- Jira: `todo`, `To Do`, `In Progress`, `In Review`
- Generic tokens: `open`, `opened`, `todo`, `doing`, `backlog`, `triage`, `progress`, `review`, `active`, `blocked`, `pending`

**Closed Issues** - Mapped to status key `"closed"`:
- All providers: `closed`, `done`, `resolved`, `fixed`, `complete`, `merged`, `shipped`, `deployed`, `cancelled`

This normalization ensures that the `/issues` page groups similar statuses together, so users see all actionable work items under a single "Open" filter regardless of the source provider.

### Dashboard Workspace Display

Project cards on the dashboard now display the workspace path where code changes are monitored:

```
floads
Last modified by Ivo Marino on Nov 13, 2025 • 11:07 UTC (branch main)
/home/ivo/workspace/aiops
```

This path indicates:
- The actual filesystem location of the user's working copy
- Where git operations (pull, push, commit) are executed
- Where the workspace is checked for uncommitted changes

The workspace path is retrieved from `get_repo_status()` service (`app/services/git_service.py`) which returns `workspace_path: repo.working_dir` in the status dictionary.

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

aiops generates issue-specific context files to help AI agents understand what they're working on. The `AGENTS.override.md` file is automatically created in the user's workspace with issue details, requirements, and project context.

### Workspace-Aware Context Files

**Important**: When clicking "Populate AGENTS.override.md" from the issues page, the file is created in the **logged-in user's workspace**, not in the Flask app directory.

For example, if user `ivo@floads.io` (Linux user `ivo`) clicks the button for the `aiops` project:
- **File created at**: `/home/ivo/workspace/aiops/AGENTS.override.md`
- **File ownership**: `ivo:ivo`
- **Operations**: Executed via `sudo -n -u ivo tee /path/to/file`

Implementation details (`app/services/agent_context.py`):
- `write_tracked_issue_context()` accepts an `identity_user` parameter
- When provided, resolves the user's workspace via `get_workspace_path(project, user)`
- Uses `run_as_user()` from sudo service to read/write files as the target user
- Reads existing `AGENTS.md` base instructions via sudo
- Writes merged content (base + issue context) to user's workspace

This ensures AI agents work with the actual code location and file ownership is correct.

### Manual Context Management

- Refresh project guidance in `AGENTS.override.md` with `python3 scripts/agent_context.py write --issue <ID> --title "<short blurb>" <<'EOF'`.
- Append new notes for the same issue by rerunning the command with the `append` subcommand.
- Clear the override file between issues with `python3 scripts/agent_context.py clear`.
- Use the "Populate AGENTS.override.md" button next to an issue in the project dashboard to refresh the repository context (creates file in your workspace).
- When you start a Codex session, ask the agent to read `AGENTS.override.md` so it loads the latest instructions before doing work.

## Current Issue Context
<!-- issue-context:start -->

_No issue context populated yet. Use the Populate AGENTS.override.md button to generate it._

<!-- issue-context:end -->
