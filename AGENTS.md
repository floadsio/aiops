# Project Overview _(version 0.3.1)_

aiops is a multi-tenant Flask control plane that unifies Git workflows, external issue trackers,
AI-assisted tmux sessions, and Ansible automation. The codebase favours thin blueprints, well-tested
service helpers, and clear separation between configuration, database models, and provider adapters.

## Architecture Overview

- **Frontend**: Pico CSS with Material Design enhancements (`app/templates/base.html`)
- **Backend**: Flask blueprints (`app/routes/`), services (`app/services/`), models (`app/models.py`)
- **Storage**: SQLite (`instance/app.db`), secrets (`.env`), SSH keys (`instance/keys/`)
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

### CLI Command Reference

#### Issue Management
```bash
# Sync and list
aiops issues sync --project <project>          # Sync from GitHub/GitLab/Jira
aiops issues list --status open --project <project>  # List issues
aiops issues get <id> --output json            # Get details (use DB ID, not external number)

# Update and comment
aiops issues comment <id> "Your update"        # Add comment (@mentions auto-resolve for Jira)
aiops issues modify-comment <id> <comment_id> "Updated text"  # Edit comment
aiops issues update <id> --title "New title"   # Update fields
aiops issues assign <id> --user <user_id>      # Assign issue
aiops issues close <id>                        # Close issue

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
aiops workflow claim <issue_id>                # Claim issue
aiops workflow progress <issue_id> "status" --comment "..."  # Update progress
aiops workflow submit <issue_id> --project <id> --message "..." --comment "..."
aiops workflow complete <issue_id> --summary "..."  # Complete and close
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
```

### Standard Workflow for AI Agents

**Complete issue workflow:**

1. **Sync**: `aiops issues sync --project <project>`
2. **Read**: `aiops issues get <id> --output json`
3. **Comment**: `aiops issues comment <id> "Starting work..."`
4. **Work**: Make code changes in your workspace
5. **Commit**: `aiops git commit <project> "Fix bug" --files "..."`
6. **Update**: `aiops issues comment <id> "Completed: - Fixed X\n- Updated Y\n\nTests passing."`
7. **Close**: `aiops issues close <id>`

**Best practices:**
- Use DB IDs from `aiops issues list`, not external issue numbers
- Add `--output json` for programmatic parsing
- Comment frequently with file paths and specific changes
- Use `@username` in Jira comments (auto-resolves to account IDs)
- Create follow-up issues instead of expanding scope
- Get integration ID via `aiops issues get <any-id> --output json | grep integration_id`


## Critical Guidelines for AI Agents

### Workspace Context
- **Work in your workspace**: `/home/{username}/workspace/{tenant_slug}/{project}/`
- **NEVER modify `/home/syseng/aiops`** - that's the running Flask instance
- **NEVER commit `AGENTS.override.md`** - auto-generated file, exclude from version control
- Use `pwd` to verify your location before editing files

### Production Safety
- **NEVER auto-update or restart production** (`/home/syseng/aiops/`)
- Only work in personal workspaces, commit, and push
- Admin handles production deployments manually

### Development Workflow
- Load `AGENTS.override.md` for current issue context before coding
- Keep routes (`app/routes/`) thin, push logic to services (`app/services/`)
- Add provider stubs in `tests/services/issues/` for external integrations
- Run `.venv/bin/flask db upgrade` before starting server if migrations pending
- Use `make start-dev` for auto-reload during development
- Run `make check` before commits (lint + tests)

### Per-User Workspaces & SSH Keys
- Each user has a workspace at `/home/{username}/workspace/{tenant_slug}/{project}/`
- Initialize with: `.venv/bin/flask init-workspace --user-email user@example.com --project-id 1`
- Use your own SSH keys (`~/.ssh/id_ed25519` or `~/.ssh/id_rsa`) for git authentication
- Set up: `ssh-keygen -t ed25519 -C "your_email@example.com"` and add public key to GitHub/GitLab

## Development Commands

- `make sync` - Install dependencies with uv (Python 3.12)
- `make format` - Auto-format with Ruff
- `make lint` - Ruff + MyPy checks
- `make test` - Run Pytest
- `make check` - Lint + tests (run before commits)
- `make start-dev` - Start Flask with auto-reload
- `.venv/bin/flask version` - Display current version

## Coding Standards

- Follow PEP 8: 4-space indent, 100-char lines, snake_case for modules/functions, PascalCase for classes
- Type hints required on new code, MyPy warnings are errors
- Keep routes thin, push logic to `app/services/`
- Test coverage target: 90% on core services
- **Never include AI attribution in commits** - no "Generated with" footers

## Version Management

Update both locations when bumping version:
1. Header in `AGENTS.md`: `# Project Overview _(version X.Y.Z)_`
2. Root `VERSION` file (read by `app/version.py`)

## Global Agent Context

aiops supports **global AGENTS.md content** stored in the database and included in all `AGENTS.override.md` files.

**Manage via CLI:**
```bash
aiops agents global get                        # View current
aiops agents global set -f path/to/content.md  # Set from file
aiops agents global clear                      # Revert to repo AGENTS.md
```

**Or via Web UI:** Admin → Settings → Global Agent Context

## Current Issue Context
<!-- issue-context:start -->

_No issue context populated yet. Use the Populate AGENTS.override.md button to generate it._

<!-- issue-context:end -->
