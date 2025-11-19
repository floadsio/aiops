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

## Current Issue Context
<!-- issue-context:start -->

NOTE: Generated issue context. Update before publishing if needed.

# 22 - Fix tmux session buttons visibility on mobile (responsive mode)

        _Updated: 2025-11-18 18:48:11Z_

        ## Issue Snapshot
        - Provider: github
        - Status: open
        - Assignee: ivomarino
        - Labels: none
        - Source: https://github.com/floadsio/aiops/issues/22
        - Last Synced: 2025-11-18 18:47 UTC

        ## Issue Description
        No additional details provided by the issue tracker.

        ## Project Context
        - Project: aiops
        - Repository: git@github.com:floadsio/aiops.git
        - Local Path: instance/repos/aiops

        ## Other Known Issues
        - [github] 21: Decouple tmux sessions from backend process lifecycle; status=closed; assignee=ivomarino; updated=2025-11-18 15:29 UTC; url=https://github.com/floadsio/aiops/issues/21
- [github] 20: Bug: Per-user sessions not using sudo when reusing existing tmux windows; status=closed; assignee=ivomarino; labels=bug, critical, security; updated=2025-11-18 13:32 UTC; url=https://github.com/floadsio/aiops/issues/20
- [github] 19: Issue: Per-user workspaces require directory traversal permissions; status=open; assignee=ivomarino; labels=bug, infrastructure, workspace; updated=2025-11-18 13:15 UTC; url=https://github.com/floadsio/aiops/issues/19
- [github] 18: Setup: Michael needs personal SSH key for GitHub authentication; status=closed; assignee=ivomarino; labels=setup, infrastructure; updated=2025-11-18 13:15 UTC; url=https://github.com/floadsio/aiops/issues/18
- [github] 17: Issue: Confusing 'Status unavailable' message for newly initialized workspaces; status=closed; assignee=ivomarino; labels=bug, ux; updated=2025-11-18 12:29 UTC; url=https://github.com/floadsio/aiops/issues/17
- [github] 13: Feature: Database Backup and Download via CLI and Web UI; status=closed; assignee=ivomarino; labels=enhancement, feature; updated=2025-11-18 11:45 UTC; url=https://github.com/floadsio/aiops/issues/13
- [github] 16: User-specific integration credentials for personal tokens; status=open; assignee=ivomarino; updated=2025-11-18 10:04 UTC; url=https://github.com/floadsio/aiops/issues/16
- [github] 14: Feature: Add GitLab Issue Comment Support; status=closed; assignee=ivomarino; labels=enhancement, feature; updated=2025-11-18 02:49 UTC; url=https://github.com/floadsio/aiops/issues/14
- [github] 15: Feature: Add GitHub Comment Editing Support; status=open; assignee=ivomarino; labels=enhancement, feature; updated=2025-11-18 02:43 UTC; url=https://github.com/floadsio/aiops/issues/15
- [github] 12: Cleanup tests and test CLI commenting features; status=closed; updated=2025-11-17 22:07 UTC; url=https://github.com/floadsio/aiops/issues/12
- [github] 11: Feature: Global AGENTS.md content for override files; status=closed; assignee=ivomarino; labels=enhancement, feature; updated=2025-11-17 22:00 UTC; url=https://github.com/floadsio/aiops/issues/11
- [github] 10: Publish aiops-cli v0.3.0 to PyPI; status=open; assignee=ivomarino; labels=enhancement; updated=2025-11-17 21:45 UTC; url=https://github.com/floadsio/aiops/issues/10
- [github] 8: Issue: Implement aiops CLI Client for macOS & Linux; status=closed; assignee=ivomarino; labels=enhancement; updated=2025-11-17 21:00 UTC; url=https://github.com/floadsio/aiops/issues/8
- [github] 9: Publish aiops-cli to PyPI; status=closed; assignee=ivomarino; labels=enhancement; updated=2025-11-17 20:56 UTC; url=https://github.com/floadsio/aiops/issues/9
- [github] 7: Issue: Implement a Public AIops API for AI Agents and CLI Clients; status=closed; assignee=ivomarino; labels=enhancement; updated=2025-11-16 22:55 UTC; url=https://github.com/floadsio/aiops/issues/7
- [github] 4: Issue: Improve UI Responsiveness + Redesign Main Menu Layout; status=closed; assignee=ivomarino; labels=enhancement; updated=2025-11-16 13:43 UTC; url=https://github.com/floadsio/aiops/issues/4
- [github] 5: Issue: Add Project Filter to Issues Page; status=closed; assignee=ivomarino; updated=2025-11-15 17:34 UTC; url=https://github.com/floadsio/aiops/issues/5
- [github] 3: Feature: Create New Issues Directly from the AIops Issues Page; status=closed; assignee=ivomarino; updated=2025-11-15 17:34 UTC; url=https://github.com/floadsio/aiops/issues/3
- [github] 6: Issue: Add Close Button to Pinned Issues on Dashboard; status=closed; assignee=ivomarino; updated=2025-11-15 17:33 UTC; url=https://github.com/floadsio/aiops/issues/6
- [github] 1: Add Cross-Platform Issue Creation + User Mapping Support in aiops; status=closed; assignee=ivomarino; labels=enhancement; updated=2025-11-15 14:41 UTC; url=https://github.com/floadsio/aiops/issues/1
- [github] 2: Test issue - organization token; status=closed; updated=2025-11-15 14:36 UTC; url=https://github.com/floadsio/aiops/issues/2

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
