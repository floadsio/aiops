# Project Overview _(version 0.3.1)_

aiops is a multi-tenant Flask control plane that unifies Git workflows, external issue trackers,
AI-assisted tmux sessions, and Ansible automation. The codebase favours thin blueprints, well-tested
service helpers, and clear separation between configuration, database models, and provider adapters.

## Architecture Overview

- **Frontend**: Pico CSS with Material Design enhancements (`app/templates/base.html`)
- **Backend**: Flask blueprints (`app/routes/`), services (`app/services/`), models (`app/models.py`)
- **Storage**: SQLite (`instance/app.db`), secrets (`.env`), SSH keys (`instance/keys/`), **backups** (`instance/backups/`)
- **Infrastructure**: Ansible playbooks (`ansible/playbooks/`)
- **API**: REST API at `/api/v1` with Swagger UI at `/api/docs`

## AIops CLI for AI Agents

**CRITICAL**: AI agents MUST use the `aiops` CLI for all operations. The CLI is pre-installed at `./.venv/bin/aiops`
and pre-configured with API credentials. Never call external APIs directly.

```bash
# Check configuration
aiops config show

# Activate virtualenv (optional)
source .venv/bin/activate
```

## IMPORTANT: Database IDs vs External Issue Numbers

**CRITICAL RULE**: The aiops API uses **database IDs** for ALL operations, NOT external issue numbers.

- ✅ **Correct**: Use database ID from `aiops issues list` (e.g., 506)
- ❌ **Wrong**: Use external issue number (e.g., GitHub #13)

**Why?** Database IDs are globally unique across all providers (GitHub, GitLab, Jira), preventing conflicts.

**How to find the database ID:**
```bash
# Step 1: List issues to get database IDs
aiops issues list --project <project> --status open

# Output shows:
# Id    External  Title                Status    Provider
# 506   13        Feature: Backup...   open      github
# ^^^   ^^
# DB ID External #

# Step 2: Use the database ID (506) for all operations
aiops issues comment 506 "Working on this"  # ✅ Correct
aiops issues comment 13 "Working on this"   # ❌ Wrong - will get 404 error!
```

### CLI Command Reference

#### Issue Management
```bash
# ALWAYS get database IDs first!
aiops issues sync --project <project>          # Sync from GitHub/GitLab/Jira
aiops issues list --status open --project <project>  # List issues (shows DB IDs)

# Use database IDs for all operations (not external issue numbers!)
aiops issues get <db_id> --output json         # Get details with DB ID
aiops issues comment <db_id> "Your update"     # Add comment with DB ID
aiops issues modify-comment <db_id> <comment_id> "Updated text"  # Edit comment
aiops issues update <db_id> --title "New title"   # Update fields
aiops issues assign <db_id> --user <user_id>      # Assign issue
aiops issues close <db_id>                        # Close issue

# Create (need integration ID from existing issue)
aiops issues create --project <project> --integration <id> --title "..." --description "..."
```

#### Git Operations
```bash
# Repository status and updates
aiops git status <project>                     # Check repo status
aiops git pull <project>                       # Pull latest changes
aiops git push <project>                       # Push commits

# Make changes
aiops git commit <project> "Message" --files "app/auth.py,app/models.py"

# Branch management
aiops git branches <project>                   # List branches
aiops git branch <project> feature-x           # Create branch
aiops git checkout <project> feature-x         # Switch branch

# Read files
aiops git cat <project> app/models.py          # Read file
aiops git files <project> app/                 # List directory
```

#### Workflow Commands
```bash
# High-level workflows combining multiple operations
# These also use database IDs!
aiops workflow claim <db_id>                   # Claim issue
aiops workflow progress <db_id> "status" --comment "..."  # Update progress
aiops workflow submit <db_id> --project <id> --message "..." --comment "..."
aiops workflow complete <db_id> --summary "..."  # Complete and close
```

#### Project & Tenant Management
```bash
aiops projects list --tenant <tenant>          # List projects
aiops projects get <project>                   # Get project details
aiops projects create --name "..." --repo-url "..." --tenant <tenant>

aiops tenants list                             # List tenants
aiops tenants get <tenant>                     # Get details
```

#### System Management (admin only)
```bash
aiops system update                            # Update aiops (git pull + deps + migrations)
aiops system restart                           # Restart application
aiops system update-and-restart                # Combined operation
aiops update                                   # Update CLI itself

# Database backups (IMPORTANT for data protection!)
aiops system backup create                                    # Create backup
aiops system backup create --description "Before migration"  # Create with description
aiops system backup list                                      # List all backups
aiops system backup download <backup_id>                      # Download backup file
aiops system backup restore <backup_id>                       # Restore from backup (destructive!)
```

### Database Backup Best Practices

**When to create backups:**
- Before running database migrations
- Before major configuration changes
- Before destructive operations
- Before upgrading aiops version
- Periodically (daily/weekly based on change frequency)

**Backup workflow example:**
```bash
# Create a backup before migration
aiops system backup create --description "Before migration to v0.4.0"

# List backups to verify (note: backup IDs are shown)
aiops system backup list

# If something goes wrong, restore:
aiops system backup restore <backup_id>  # Will prompt for confirmation
```

**Important notes:**
- Backups include SQLite database + SSH keys in compressed tar.gz format
- Backups are stored in `instance/backups/` directory
- All backup operations require admin API scope
- Restore operation is destructive - always confirm you have the right backup ID
- After restore, you may need to restart the application

### Standard Workflow for AI Agents

**Complete issue workflow (with correct ID usage):**

1. **Sync & List**: `aiops issues sync --project <project> && aiops issues list --status open --project <project>`
2. **Get DB ID**: Note the database ID from the list (leftmost "Id" column, NOT "External" column)
3. **Read**: `aiops issues get <db_id> --output json`
4. **Comment**: `aiops issues comment <db_id> "Starting work..."`
5. **Work**: Make code changes in your workspace
6. **Commit**: `aiops git commit <project> "Fix bug" --files "..."`
7. **Update**: `aiops issues comment <db_id> "Completed: - Fixed X\n- Updated Y\n\nTests passing."`
8. **Close**: `aiops issues close <db_id>`

**Example with real IDs:**
```bash
# List shows: Id=506, External=13, Title="Feature: Backup..."
aiops issues comment 506 "Working on this"  # ✅ Use DB ID 506
# NOT: aiops issues comment 13 "..."        # ❌ Will fail with 404!
```

**Best practices:**
- **ALWAYS use database IDs from `aiops issues list`, NEVER use external issue numbers**
- The "Id" column in `aiops issues list` shows database IDs (use these!)
- The "External" column shows external issue numbers (GitHub #, GitLab !, Jira key)
- If you get a 404 error, you probably used the external number instead of database ID
- Add `--output json` for programmatic parsing
- Comment frequently with file paths and specific changes
- Use `@username` in Jira comments (auto-resolves to account IDs)
- Create follow-up issues instead of expanding scope
- Get integration ID via `aiops issues get <db_id> --output json | grep integration_id`
- **Create backups before risky operations like migrations or major refactors**

---

# Project Overview _(version 0.1.7)_

aiops is a multi-tenant Flask control plane that unifies Git workflows, external issue trackers,
AI-assisted tmux sessions, and Ansible automation. Platform engineers use it to synchronise issues,
triage incidents, and trigger automation tasks without leaving the dashboard. The codebase favours
thin blueprints, well-tested service helpers, and clear separation between configuration, database
models, and provider adapters. Secrets stay in `instance/` and `.env`, while infrastructure assets
live under `ansible/`.

## How Agents Should Work Here

- **CRITICAL: Working Directory Context** — aiops uses **per-user workspaces** for all development work.
  When running in a tmux session, you'll be in your personal workspace at `/home/{username}/workspace/{tenant_slug}/{project}/`
  (e.g., `/home/ivo/workspace/floads/aiops/`). This is where you edit code, commit, and push changes.
  **NEVER modify files in `/home/syseng/aiops` directly**, as that is the running aiops Flask instance.
  Each user has their own isolated workspace with their own git configuration and shell environment.
  Check your current directory with `pwd` if uncertain.
- **CRITICAL: Production Environment Management** — **NEVER automatically update or restart the
  production aiops environment** (running at `/home/syseng/aiops/`). All production deployments,
  service restarts, and environment updates are performed manually by the system administrator.
  Agents should only work in their personal workspaces, commit changes, and push to the repository.
  The production environment will be updated separately by the admin.
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
- **Per-User Workspaces** — Each user has their own workspace directory at `/home/{username}/workspace/{tenant_slug}/{project}/`
  where they clone and work on projects. Workspaces must be initialized before use:
  ```bash
  # Initialize workspace for a user and project
  .venv/bin/flask init-workspace --user-email ivo@floads.io --project-id 1
  ```
  Once initialized, tmux sessions automatically start in the user's workspace, and all git operations
  (pull, push, branch management) operate on the user's workspace. The dashboard shows status from
  the logged-in user's workspace. This architecture eliminates permission conflicts and provides
  clean isolation between users.
- **Per-User SSH Keys** — Each user must configure their own SSH keys for git authentication.
  Per-user workspaces do NOT use project SSH keys to avoid permission issues. To set up:
  1. Generate an SSH key pair: `ssh-keygen -t ed25519 -C "your_email@example.com"`
  2. Add the public key to your GitHub/GitLab account
  3. Test authentication: `ssh -T git@github.com`
  4. Your `~/.ssh/id_ed25519` or `~/.ssh/id_rsa` will be used automatically for git operations
  Project SSH keys (stored in `instance/keys/`) are only used for system-level operations run by
  the Flask app user (`syseng`). AI sessions (Claude, Codex, Gemini) running as your Linux user
  will use your personal SSH keys, ensuring proper file permissions and security isolation.
- Use `make start-dev` during development so Flask auto-reloads changes. The legacy `make start`
  runs detached and will not reload code.
- Prefer built-in CLI commands (`flask version`, `flask sync-issues`, etc.) over ad-hoc scripts so
  teammates can reproduce results.
- During implementation, focus on code changes and skip tests (`make lint` only). Run `make check` before commits; treat style/type errors as blockers. Use `make test-file FILE=tests/test_<area>.py` to test specific modules during development.

## Sudo Service Architecture

**CRITICAL: All code modifications must be made in your personal workspace** at `/home/{username}/workspace/floads/aiops/`,
NOT in the running Flask instance at `/home/syseng/aiops/`. The running instance is for the Flask application
server only. Always use `pwd` to verify you're in your workspace before editing files.

aiops uses a centralized sudo utility service (`app/services/sudo_service.py`) to execute operations as different
Linux users. This is essential because:
- The Flask app runs as `syseng` but needs to access per-user workspaces
- User workspaces live in `~/workspace/` with restrictive permissions (drwx------)
- Git operations run with each user's own SSH keys (`~/.ssh/id_ed25519` or `~/.ssh/id_rsa`)
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
if test_path("ivo", "/home/ivo/workspace/floads/aiops/.git"):
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

    # Clone repository using user's own SSH keys
    # Note: env=None means the user's default SSH key (~/.ssh/id_ed25519 or id_rsa) will be used
    try:
        run_as_user(
            linux_username,
            ["git", "clone", "--branch", branch, repo_url, str(workspace_path)],
            env=None,  # Let user's own SSH keys handle authentication
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

3. **Git operations use user's own SSH keys:**
   ```python
   # For per-user git operations, don't pass env - let user's SSH keys work
   run_as_user(username, ["git", "pull"], env=None)

   # Project SSH keys are only for system-level operations (syseng)
   # env = build_project_git_env(project)  # Only use for syseng operations
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
sudo -u syseng git config --global --add safe.directory '/home/ivo/workspace/floads/aiops'
sudo -u syseng git config --global --add safe.directory '/home/michael/workspace/floads/aiops'

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
ls -la /home/ivo/workspace/floads/aiops
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
/home/ivo/workspace/floads/aiops
```

This path indicates:
- The actual filesystem location of the user's working copy
- Where git operations (pull, push, commit) are executed
- Where the workspace is checked for uncommitted changes

The workspace path is retrieved from `get_repo_status()` service (`app/services/git_service.py`) which returns `workspace_path: repo.working_dir` in the status dictionary.

# Repository Guidelines

## Project Structure & Module Organization
The aiops Flask app lives in `app/`, with blueprints in `app/routes/`, forms in `app/forms/`, and shared helpers in `app/services/`. Database models sit in `app/models.py`, configuration glue in `app/config.py` and `app/extensions.py`, and CLI entry points in `manage.py`. Store infrastructure assets under `ansible/playbooks/`, documentation in `docs/`, and keep tests parallel to runtime modules inside `tests/`.

## Version Management
When updating the aiops version, **always update both version locations**:
1. **`AGENTS.md`**: Update the version number in the header line `# Project Overview _(version X.Y.Z)_`
2. **`VERSION` file**: Update the version string in the root `VERSION` file (read by `app/version.py`)

The version follows semantic versioning (MAJOR.MINOR.PATCH). Use `.venv/bin/flask version` to display the current version. The version is displayed in the admin UI footer and used for tracking deployments.

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
- **File created at**: `/home/ivo/workspace/floads/aiops/AGENTS.override.md`
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

---

---

---

---

---

---

---

---

---

---

---

## Current Issue Context
<!-- issue-context:start -->

NOTE: Generated issue context. Update before publishing if needed.

# 13 - Feature: Database Backup and Download via CLI and Web UI

        _Updated: 2025-11-18 11:42:38Z_

        ## Issue Snapshot
        - Provider: github
        - Status: closed
        - Assignee: ivomarino
        - Labels: enhancement, feature
        - Source: https://github.com/floadsio/aiops/issues/13
        - Last Synced: 2025-11-18 02:32 UTC

        ## Issue Description
        This feature aims to implement database backup, download, and restore via CLI and Web UI.

**CLI Functionality:**
*   `aiops system backup create`: Command to initiate a database backup.
*   `aiops system backup list`: Command to list available backups.
*   `aiops system backup download <backup_id>`: Command to download a specific backup.
*   `aiops system restore <backup_id>`: Command to restore the database from a specific backup.

**Web UI Functionality:**
*   An administrative interface (e.g., under \"Admin\" -> \"Settings\") to trigger manual backups.
*   A list of available backups with options to download them and trigger a restore.

**Considerations:**
*   **Storage Location:** Define a secure and configurable location for storing backup files.
*   **Backup Format:** Determine the appropriate format for database backups (e.g., SQLite dump, compressed archive).
*   **Security:** Ensure that only authorized users (e.g., administrators) can create, download, and restore backups.
*   **Retention Policy:** Consider implementing a configurable retention policy for old backups to manage storage space.
*   **Error Handling:** Robust error handling and user feedback for backup and restore operations.
*   **Downtime:** Consider the impact of database restore on application availability and plan for minimal downtime.
*   **Confirmation:** Implement clear confirmation steps before initiating a database restore, as it is a destructive operation.

        

## Issue Comments (4)

            **ivomarino** on 2025-11-18T02:32:16+00:00 ([link](https://github.com/floadsio/aiops/issues/13#issuecomment-3544756296))

Completed: Added backup download feature to the web UI

## Changes Implemented

- Added `download_backup_web()` route to admin blueprint at `/settings/backups/<int:backup_id>/download`
- Added Download button to the backup list table in Admin Settings
- Button appears before Restore and Delete buttons with consistent styling
- Uses Flask's `send_file()` to serve backup files (.db.gz) as downloads
- Includes proper error handling with flash messages

## Technical Details

**Backend** (app/routes/admin.py:3529-3548):
- GET endpoint for downloading backup files
- Reuses existing `get_backup()` service function
- Returns file with `application/gzip` mimetype
- Graceful error handling for missing backups

**Frontend** (app/templates/admin/settings.html:360):
- Download link styled as button matching existing UI
- Positioned first in action buttons (Download, Restore, Delete)
- No form submission needed (simple GET request)

## Commit
https://github.com/floadsio/aiops/commit/3c79c54

The web UI download feature is now fully functional and complements the existing CLI command `aiops system backup download <id>`.

---

**ivomarino** on 2025-11-18T02:23:27+00:00 ([link](https://github.com/floadsio/aiops/issues/13#issuecomment-3544739628))

**Status Update:** Completed implementation

## Summary

Successfully implemented the database backup and download feature across CLI, Web API, and Web UI.

## Changes Made

### Backend Implementation (commit 6455063)
- **Backup Service** (`app/services/backup_service.py`): Core functionality for creating, listing, downloading, and restoring backups
  - SQLite database + SSH keys packaged in compressed tar.gz format
  - Backups stored in `instance/backups/` directory
  - Automatic cleanup and validation

- **Database Models** (`app/models.py`): Added `Backup` model to track backup metadata
  - Timestamps, descriptions, file paths, sizes, checksums

- **API Endpoints** (`app/routes/api_v1/system.py`):
  - `POST /api/v1/system/backups` - Create backup
  - `GET /api/v1/system/backups` - List all backups
  - `GET /api/v1/system/backups/<id>` - Get backup details
  - `GET /api/v1/system/backups/<id>/download` - Download backup file
  - `POST /api/v1/system/backups/<id>/restore` - Restore from backup

- **Database Migration**: Created migration for Backup model

### CLI Integration (commit 6455063)
- `aiops system backup create [--description]` - Create new backup
- `aiops system backup list` - List all backups with details
- `aiops system backup download <id>` - Download backup to local file
- `aiops system backup restore <id>` - Restore database (with confirmation prompt)

### Web UI (commit 0c00375)
- **Admin → Settings**: Added "Database Backups" section
- Manual backup creation with optional description
- Backup list table showing:
  - ID, creation timestamp, description, file size
  - Download and Restore action buttons
- Confirmation dialog for destructive restore operations
- Real-time feedback via toast notifications

### Documentation Updates (commit 810362e)
- Updated `AGENTS.md` with comprehensive backup CLI documentation
- Added best practices section for backup workflows
- Documented when to create backups (migrations, upgrades, etc.)
- Added security and retention policy considerations

## Testing

All backup operations tested and working:
- ✅ Backup creation with SQLite + SSH keys
- ✅ Backup listing and metadata retrieval
- ✅ Backup download via CLI and Web UI
- ✅ Backup restore with confirmation
- ✅ Error handling for missing files and invalid IDs
- ✅ Admin-only access control enforced

## Files Modified

- `app/models.py`
- `app/services/backup_service.py` (new)
- `app/routes/api_v1/system.py`
- `app/templates/admin/settings.html`
- `cli/aiops_cli/cli.py`
- `cli/aiops_cli/client.py`
- `AGENTS.md`
- `migrations/versions/[hash]_add_backup_model.py` (new)

## Next Steps

Feature is complete and ready for production use. All acceptance criteria met.

---

**ivomarino** on 2025-11-18T02:05:01+00:00 ([link](https://github.com/floadsio/aiops/issues/13#issuecomment-3544699586))

**Status Update:** completed

## Implementation Summary

Successfully implemented database backup and restore functionality for aiops.

### Features Implemented

**Backend:**
- ✅ Created `Backup` model for metadata tracking (filename, size, description, creator, timestamps)
- ✅ Implemented `backup_service.py` with full backup/restore capabilities
- ✅ Backups include SQLite database + SSH keys in compressed tar.gz format
- ✅ Backups stored in `instance/backups/` directory

**API Endpoints (Admin-only):**
- ✅ `POST /api/v1/system/backups` - Create backup with optional description
- ✅ `GET /api/v1/system/backups` - List all backups with metadata
- ✅ `GET /api/v1/system/backups/<id>` - Get backup details
- ✅ `GET /api/v1/system/backups/<id>/download` - Download backup file
- ✅ `POST /api/v1/system/backups/<id>/restore` - Restore from backup

**CLI Commands:**
```bash
aiops system backup create [--description "..."]
aiops system backup list
aiops system backup download <id>
aiops system backup restore <id>
```

**Security:**
- ✅ All operations require admin API scope
- ✅ Confirmation prompt for destructive restore operations
- ✅ Proper error handling with BackupError exception
- ✅ File validation before restore

**Database:**
- ✅ Created migration for backups table with foreign key to users

**Documentation:**
- ✅ Updated AGENTS.md with CLI command reference
- ✅ Updated global agents context with backup best practices

### Files Modified
- `app/models.py` - Added Backup model
- `app/services/backup_service.py` - New service (144 lines)
- `app/routes/api_v1/system.py` - Added 5 backup endpoints
- `cli/aiops_cli/client.py` - Added 5 client methods
- `cli/aiops_cli/cli.py` - Added 4 CLI commands with rich output
- `AGENTS.md` - Updated documentation
- `migrations/` - New migration file

### Usage Example
```bash
# Create a backup
aiops system backup create --description "Before schema changes"

# List all backups
aiops system backup list

# Download backup
aiops system backup download 5

# Restore from backup (with confirmation)
aiops system backup restore 5
```

Commit: 6455063

---

**ivomarino** on 2025-11-17T22:37:36+00:00 ([link](https://github.com/floadsio/aiops/issues/13#issuecomment-3544145632))

**Status Update:** in progress

Starting work on Feature: Database Backup and Download via CLI and Web UI.

## Project Context
        - Project: aiops
        - Repository: git@github.com:floadsio/aiops.git
        - Local Path: instance/repos/aiops

        ## Other Known Issues
        - [github] 1: Add Cross-Platform Issue Creation + User Mapping Support in aiops; status=closed; assignee=ivomarino; labels=enhancement; updated=2025-11-15 14:41 UTC; url=https://github.com/floadsio/aiops/issues/1
- [github] 2: Test issue - organization token; status=closed; updated=2025-11-15 14:36 UTC; url=https://github.com/floadsio/aiops/issues/2
- [github] 3: Feature: Create New Issues Directly from the AIops Issues Page; status=closed; assignee=ivomarino; updated=2025-11-15 17:34 UTC; url=https://github.com/floadsio/aiops/issues/3
- [github] 5: Issue: Add Project Filter to Issues Page; status=closed; assignee=ivomarino; updated=2025-11-15 17:34 UTC; url=https://github.com/floadsio/aiops/issues/5
- [github] 4: Issue: Improve UI Responsiveness + Redesign Main Menu Layout; status=closed; assignee=ivomarino; labels=enhancement; updated=2025-11-16 13:43 UTC; url=https://github.com/floadsio/aiops/issues/4
- [github] 6: Issue: Add Close Button to Pinned Issues on Dashboard; status=closed; assignee=ivomarino; updated=2025-11-15 17:33 UTC; url=https://github.com/floadsio/aiops/issues/6
- [github] 7: Issue: Implement a Public AIops API for AI Agents and CLI Clients; status=closed; assignee=ivomarino; labels=enhancement; updated=2025-11-16 22:55 UTC; url=https://github.com/floadsio/aiops/issues/7
- [github] 8: Issue: Implement aiops CLI Client for macOS & Linux; status=closed; assignee=ivomarino; labels=enhancement; updated=2025-11-17 21:00 UTC; url=https://github.com/floadsio/aiops/issues/8
- [github] 9: Publish aiops-cli to PyPI; status=closed; assignee=ivomarino; labels=enhancement; updated=2025-11-17 20:56 UTC; url=https://github.com/floadsio/aiops/issues/9
- [github] 10: Publish aiops-cli v0.3.0 to PyPI; status=open; assignee=ivomarino; labels=enhancement; updated=2025-11-17 21:45 UTC; url=https://github.com/floadsio/aiops/issues/10
- [github] 11: Feature: Global AGENTS.md content for override files; status=closed; assignee=ivomarino; labels=enhancement, feature; updated=2025-11-17 22:00 UTC; url=https://github.com/floadsio/aiops/issues/11
- [github] 12: Cleanup tests and test CLI commenting features; status=closed; updated=2025-11-17 22:07 UTC; url=https://github.com/floadsio/aiops/issues/12
- [github] 14: Feature: Add GitLab Issue Comment Support; status=closed; assignee=ivomarino; labels=enhancement, feature; updated=2025-11-18 02:49 UTC; url=https://github.com/floadsio/aiops/issues/14
- [github] 15: Feature: Add GitHub Comment Editing Support; status=open; assignee=ivomarino; labels=enhancement, feature; updated=2025-11-18 02:43 UTC; url=https://github.com/floadsio/aiops/issues/15
- [github] 16: User-specific integration credentials for personal tokens; status=open; assignee=ivomarino; updated=2025-11-18 10:04 UTC; url=https://github.com/floadsio/aiops/issues/16

        ## Workflow Reminders
        1. Confirm the acceptance criteria with the external issue tracker.
        2. Explore relevant code paths and recent history.
        3. Draft a short execution plan before editing files.
        4. Implement changes with tests or validation steps.
        5. Summarize modifications and verification commands when you finish.

## Git Identity
        Use this identity for commits created while working on this issue.

        - Name: Ivo Marino
- Email: ivo@floads.io

        ```bash
git config user.name 'Ivo Marino'
git config user.email ivo@floads.io

export GIT_AUTHOR_NAME='Ivo Marino'
export GIT_COMMITTER_NAME='Ivo Marino'
export GIT_AUTHOR_EMAIL=ivo@floads.io
export GIT_COMMITTER_EMAIL=ivo@floads.io
```
<!-- issue-context:end -->
