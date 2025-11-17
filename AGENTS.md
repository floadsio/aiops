# Project Overview _(version 0.3.0)_

aiops is a multi-tenant Flask control plane that unifies Git workflows, external issue trackers,
AI-assisted tmux sessions, and Ansible automation. Platform engineers use it to synchronise issues,
triage incidents, and trigger automation tasks without leaving the dashboard. The codebase favours
thin blueprints, well-tested service helpers, and clear separation between configuration, database
models, and provider adapters. Secrets stay in `instance/` and `.env`, while infrastructure assets
live under `ansible/`.

## UI Framework & Styling

aiops uses **[Pico CSS](https://picocss.com/)** as the base framework with custom **Material Design enhancements**:

- **Pico CSS** provides semantic HTML styling, dark mode support, and minimal footprint (~10KB)
- **Custom Material Design layer** adds professional polish with:
  - Elevation shadows: `--shadow-1` through `--shadow-4` (4-level system)
  - Color system: `--md-primary` (#1976d2), `--md-surface`, `--md-border`, `--md-surface-hover`
  - Smooth transitions using `cubic-bezier(0.4, 0, 0.2, 1)` easing
  - Micro-interactions: hover effects, active states, slide animations
- **Collapsible sidebar navigation** similar to MkDocs Material and FastAPI docs
  - Floating toggle button (☰/✕) that completely collapses sidebar to width: 0
  - Active page indicators with auto-detection via JavaScript
  - localStorage persistence for collapsed state
- **All styling lives in `app/templates/base.html`** with minimal external dependencies
- **Responsive design** with mobile/tablet/desktop breakpoints preserved
- When making UI changes, maintain the Pico CSS + Material Design hybrid approach

## AIops REST API

aiops provides a comprehensive **REST API** (v1) for programmatic access to all major functionality. This API is designed for:
- **AI agents** to autonomously manage issues, code, and workflows
- **CLI clients** for scripting and automation
- **Integration testing** during development

### API Documentation

- **Interactive API Docs**: http://localhost:5000/api/docs (Swagger UI)
- **API Base Path**: `/api/v1`
- **Authentication**: Token-based using API keys (see below)
- **Rate Limiting**: 200 requests/day, 50 requests/hour per IP

### Authentication

1. Create an API key via the web UI or API endpoint:
   ```bash
   POST /api/v1/auth/keys
   {
     "name": "My API Key",
     "scopes": ["read", "write"],
     "expires_days": 90  # optional
   }
   ```

2. Use the API key in requests:
   ```bash
   # Option 1: Bearer token
   Authorization: Bearer aiops_your_api_key_here

   # Option 2: X-API-Key header
   X-API-Key: aiops_your_api_key_here
   ```

### Available Scopes

- `read` - Read access to all resources
- `write` - Create, update, and delete resources
- `admin` - Full administrative access

### Key API Endpoints

#### Issue Management
- `GET /api/v1/issues` - List issues with filtering
- `POST /api/v1/issues` - Create issue on GitHub/GitLab/Jira
- `PATCH /api/v1/issues/<id>` - Update issue
- `POST /api/v1/issues/<id>/close` - Close issue
- `POST /api/v1/issues/<id>/comments` - Add comment
- `POST /api/v1/issues/<id>/assign` - Assign issue

#### Git Operations
- `GET /api/v1/projects/<id>/git/status` - Get repository status
- `POST /api/v1/projects/<id>/git/pull` - Pull latest changes
- `POST /api/v1/projects/<id>/git/push` - Push changes
- `POST /api/v1/projects/<id>/git/commit` - Create commit
- `GET /api/v1/projects/<id>/git/branches` - List branches
- `POST /api/v1/projects/<id>/git/branches` - Create branch
- `GET /api/v1/projects/<id>/files` - List files
- `GET /api/v1/projects/<id>/files/<path>` - Read file

#### AI Agent Workflows
- `POST /api/v1/workflows/claim-issue` - Claim issue and get workspace info
- `POST /api/v1/workflows/update-progress` - Update issue status with comment
- `POST /api/v1/workflows/submit-changes` - Commit and comment on issue
- `POST /api/v1/workflows/request-approval` - Request review
- `POST /api/v1/workflows/complete-issue` - Mark issue complete and close

#### Projects & Tenants
- `GET /api/v1/tenants` - List tenants
- `POST /api/v1/tenants` - Create tenant
- `GET /api/v1/projects` - List projects
- `POST /api/v1/projects` - Create project

### Example AI Agent Workflow

```bash
# 1. Authenticate
curl -H "Authorization: Bearer aiops_your_key" http://localhost:5000/api/v1/auth/me

# 2. Claim an issue
curl -X POST -H "Authorization: Bearer aiops_your_key" \\
  -H "Content-Type: application/json" \\
  -d '{"issue_id": 42}' \\
  http://localhost:5000/api/v1/workflows/claim-issue

# 3. Initialize workspace (if needed)
curl -X POST -H "Authorization: Bearer aiops_your_key" \\
  http://localhost:5000/api/v1/projects/1/workspace/init

# 4. Make changes, then commit
curl -X POST -H "Authorization: Bearer aiops_your_key" \\
  -H "Content-Type: application/json" \\
  -d '{"message": "Fix bug in authentication", "files": ["app/auth.py"]}' \\
  http://localhost:5000/api/v1/projects/1/git/commit

# 5. Submit changes and update issue
curl -X POST -H "Authorization: Bearer aiops_your_key" \\
  -H "Content-Type: application/json" \\
  -d '{"issue_id": 42, "project_id": 1, "commit_message": "Fix bug", "comment": "Bug fixed!"}' \\
  http://localhost:5000/api/v1/workflows/submit-changes

# 6. Complete the issue
curl -X POST -H "Authorization: Bearer aiops_your_key" \\
  -H "Content-Type: application/json" \\
  -d '{"issue_id": 42, "summary": "Fixed authentication bug"}' \\
  http://localhost:5000/api/v1/workflows/complete-issue
```

### Testing the API

During development, you can test the API using:
- **Swagger UI**: http://localhost:5000/api/docs (interactive documentation)
- **curl**: Command-line HTTP requests (examples above)
- **Python**: Using `requests` library
- **Postman**: Import OpenAPI spec from `/api/v1/apispec.json`

## AIops CLI for AI Agents

The `aiops` CLI is a powerful command-line interface that wraps the REST API and provides AI agents with convenient access to all aiops functionality. The CLI is pre-configured in tmux sessions and can be used directly by Claude, Codex, Gemini, and other AI agents.

### CLI Configuration

The CLI is already configured in your workspace with:
- **API URL**: Automatically configured (usually `http://dev.floads:5000`)
- **API Key**: Pre-configured for your user session
- **Config location**: `~/.config/aiops/config.json`

Check your configuration:
```bash
aiops config show
```

### Issue Management via CLI

AI agents can interact with external issue trackers (Jira, GitHub, GitLab) using these commands:

```bash
# List issues
aiops issues list                              # All issues
aiops issues list --status open               # Open issues only
aiops issues list --project aiops             # Filter by project

# Get issue details (includes comments with Jira account IDs)
aiops issues get 254

# Add comments to issues (automatic @mention resolution for Jira)
aiops issues comment 254 "Fixed the tunnel configuration"
aiops issues comment 254 "@jens The issue is resolved"

# Modify existing comments (for fixing typos or updating information)
aiops issues modify-comment 254 <comment_id> "Updated: Fixed the tunnel configuration"
aiops issues modify-comment 254 <comment_id> "@jens The issue is fully resolved now"

# Update issue status
aiops issues update 254 --title "New title"
aiops issues close 254

# Assign issues
aiops issues assign 254                       # Assign to self
aiops issues assign 254 --user 5              # Assign to specific user

# Synchronize issues from external providers
aiops issues sync                             # Sync all
aiops issues sync --project aiops             # Sync specific project
aiops issues sync --force-full                # Force full sync
```

**Important**: When commenting on Jira issues, the CLI automatically resolves @mentions to Jira account IDs by looking up users from the issue's comment history. This means you can write `@jens` and it will be converted to `[~accountid:557058:49affac3-cdf1-4248-8e0b-1cffc2e4360e]` automatically.

### Git Operations via CLI

Manage git repositories in your workspace:

```bash
# Check repository status
aiops git status aiops

# Pull latest changes
aiops git pull aiops

# Commit changes
aiops git commit aiops "Fix authentication bug" --files "app/auth.py,app/models.py"

# Push changes
aiops git push aiops

# Branch management
aiops git branches aiops                      # List branches
aiops git branch aiops feature-x              # Create branch
aiops git checkout aiops feature-x            # Switch branch

# Read files from repository
aiops git cat aiops app/models.py
aiops git files aiops app/                    # List files in directory
```

### System Management via CLI

AI agents can update the aiops system itself (requires admin API key):

```bash
# Update aiops application (git pull + dependencies + migrations)
aiops system update

# Restart aiops application
aiops system restart

# Update and restart in one command
aiops system update-and-restart

# Update the aiops CLI itself
aiops update                                   # Update CLI to latest version
aiops update --check-only                     # Check for updates without installing
```

**Note**: System update commands require an admin-scoped API key. Regular development work uses user-scoped API keys.

### Workflow Commands for AI Agents

High-level workflow commands that combine multiple operations:

```bash
# Claim an issue and get workspace information
aiops workflow claim 254

# Start AI session on an issue (claims + starts tmux session)
aiops issues work 254 --tool claude --attach

# Update progress on an issue
aiops workflow progress 254 "in_progress" --comment "Working on this now"

# Submit changes with commit and comment
aiops workflow submit 254 --project 1 --message "Fix bug" --comment "Bug fixed!"

# Request approval
aiops workflow approve 254 --message "Ready for review"

# Complete an issue
aiops workflow complete 254 --summary "Fixed authentication bug"
```

### Project and Tenant Management

```bash
# List projects
aiops projects list
aiops projects list --tenant floads

# Get project details
aiops projects get aiops

# Create new project
aiops projects create --name "new-project" --repo-url "git@github.com:org/repo.git" --tenant floads

# Manage tenants
aiops tenants list
aiops tenants get floads
aiops tenants create --name "New Tenant" --color "#ff6600"
```

### Authentication and API Keys

```bash
# Check current user
aiops auth whoami

# Manage API keys (requires existing key)
aiops auth keys list
aiops auth keys create --name "My Agent Key" --scopes "read,write"
aiops auth keys delete 123
```

### Output Formats

The CLI supports multiple output formats for easy parsing:

```bash
aiops issues list --output json              # JSON output
aiops issues list --output yaml              # YAML output
aiops issues list --output table             # Table output (default)
```

### Using the CLI in AI Agent Workflows

**Example: Fix a bug reported in Jira**

```bash
# 1. Get issue details
aiops issues get 254

# 2. Work on the issue
cd /home/ivo/workspace/floads/aiops
# ... make code changes ...

# 3. Commit changes
aiops git commit aiops "Fix tunnel configuration" --files "ansible/playbooks/wireguard.yml"

# 4. Push changes
aiops git push aiops

# 5. Comment on issue
aiops issues comment 254 "@jens Fixed the tunnel configuration. Changes have been deployed."

# 6. Close issue
aiops issues close 254
```

**Example: Update aiops system**

```bash
# Pull latest code, install dependencies, run migrations
aiops system update

# Restart the application
aiops system restart
```

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
- **CRITICAL: NEVER commit or push `AGENTS.override.md`** — This file is auto-generated workspace
  context and should NOT be tracked in version control. Always exclude it from git commits.
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

**IMPORTANT: Never include AI attribution in commits.** Do not add footers like "🤖 Generated with [Claude Code]" or "Co-Authored-By: Claude" to commit messages. All commits should appear as human-authored work without mentioning AI assistance.

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

## Current Issue Context
<!-- issue-context:start -->

_No issue context populated yet. Use the Populate AGENTS.override.md button to generate it._

<!-- issue-context:end -->
