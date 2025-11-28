## Development Workflow - Features & Bug Fixes

**CRITICAL: ALWAYS follow this workflow for new features AND bug fixes**

### 1. Create an Issue First
- **ALWAYS create an issue** before starting work on:
  - ✅ New features
  - ✅ Bug fixes
  - ✅ Significant refactoring
  - ✅ Breaking changes
- Document requirements/bug description, acceptance criteria, and scope
- Use the issue for discussion and planning
- Link all commits and PRs to the issue
- **ALWAYS set appropriate labels** when creating issues:
  - `bug` for bug fixes
  - `feature` or `enhancement` for new features
  - `refactor` for refactoring work
  - `documentation` for docs updates
  - Additional context labels as needed (e.g., `high-priority`, `breaking-change`)

### 2. Live Testing on Production

**When you create a feature branch and want to test it live on production:**

```bash
# Step 1: Create feature branch and PR (as described below)
git checkout -b feature/xyz-description
# ... make changes ...
git commit -m "Feature: description"
git push -u origin feature/xyz-description

# Step 2: Create PR via aiops CLI
aiops git pr-create <project> \
  --title "Feature: description" \
  --description "..." \
  --source feature/xyz-description \
  --target main

# Step 3: Switch production to feature branch for live testing
# SSH into production server or use direct git commands:
cd /home/syseng/aiops
sudo git fetch origin feature/xyz-description
sudo git checkout feature/xyz-description
sudo systemctl restart aiops
```

### 3. Document Completed Features

**AFTER a feature has been implemented and tested (before merging to main):**

1. **Post Implementation Summary to GitHub Issue**
   - Include complete list of features delivered
   - Document all files modified with brief descriptions
   - List key functions/components and their purposes
   - Document API endpoints (if applicable)
   - Include design decisions and rationale
   - List all commits in feature branch
   - Example structure:
     ```markdown
     ## ✅ Implementation Complete - Feature Name (Issue #XXX)
     
     ### Overview
     [Brief description of what was built]
     
     ### Features Implemented
     - Feature 1 with details
     - Feature 2 with details
     
     ### Technical Implementation
     #### Files Modified
     1. path/to/file.py (description)
     2. path/to/template.html (description)
     
     #### Key Functions
     - function_name() - what it does
     
     ### API Endpoints
     - GET /api/v1/endpoint - description
     
     ### Design Decisions
     1. Decision 1 - rationale
     2. Decision 2 - rationale
     
     ### How to Resume/Extend
     [Notes on future enhancements and testing]
     
     ### Commits
     [List of all commits in feature branch]
     ```

2. **Use aiops CLI to Post Comment**
   ```bash
   # Find internal issue ID
   aiops issues list --project <project> -o json | grep '"external_id":"<number>"' -B 5 | grep '"id"'
   
   # Post implementation summary from file
   aiops issues comment <internal-id> --file /path/to/summary.txt
   ```

3. **This Documents For Future Resume**
   - Future developers can understand the complete architecture
   - Design decisions are explained for context
   - Extension points are documented
   - Testing notes are available
   - Commit history is summarized

### 4. Merge and Deploy Workflow

```bash
# Step 1: Switch production back to main (if on feature branch)
cd /home/syseng/aiops
sudo git fetch origin main
sudo git checkout main
sudo systemctl restart aiops

# Step 2: Merge feature branch to main (from workspace)
git checkout main
git pull origin main
git merge feature/xyz-description --no-ff -m "Merge: Feature - Description (closes #XXX)"
git push origin main

# Step 3: Deploy to production
cd /home/syseng/aiops
sudo git fetch origin main
sudo git reset --hard origin/main

# CRITICAL: Sync dependencies after pulling code updates
sudo su - syseng -c "cd /home/syseng/aiops && /home/syseng/.local/bin/uv pip install -r requirements.txt"
# OR use make sync if available
sudo su - syseng -c "cd /home/syseng/aiops && make sync"

sudo systemctl restart aiops

# Step 4: Verify deployment
sudo systemctl status aiops --no-pager
git log --oneline -1
```

**IMPORTANT:** Always run `make sync` or `uv pip install -r requirements.txt` after pulling code updates to ensure all dependencies (including new ones like `ollama`) are installed. Skipping this step can cause runtime errors due to missing libraries.

### 5. Close the Issue

```bash
# After merged and deployed to production
aiops issues comment <internal-id> "✅ Implemented and merged in $(git rev-parse --short HEAD)"
aiops issues close <internal-id>
```

---

## Pull/Merge Request Creation

**CRITICAL: ALWAYS use `aiops git pr-create` for creating pull requests (GitHub) or merge requests (GitLab)**

### Command Syntax
```bash
aiops git pr-create <project> \
  --title "Feature: Add authentication (closes #123)" \
  --description "Implements user authentication with JWT tokens.

Closes #123

Changes:
- Added User model
- Implemented JWT auth
- Added login/logout endpoints

Testing:
- Manual testing completed
- Unit tests added and passing" \
  --source feature-auth \
  --target main \
  --assignee githubusername \
  --draft                                      # Optional: create as draft PR
```

### PR/MR Guidelines
- **NEVER use `gh pr create`, `glab mr create`, or direct git push with PR creation**
- **ALWAYS use `aiops git pr-create`** to create PRs/MRs
- **ALWAYS use `aiops git pr-merge`** to merge PRs/MRs
- The CLI automatically detects provider (GitHub/GitLab) and creates appropriate PR/MR
- Supports both GitHub pull requests and GitLab merge requests
- Assignee becomes reviewer for GitHub, assignee for GitLab
- Use `--draft` flag to create draft PRs (GitHub only)
- **ALWAYS reference the issue** in PR title and description:
  - `closes #123` or `fixes #456` for features/bugs
  - `refs #789` for related work that doesn't close the issue

### GitHub Fine-Grained PAT Requirements
For full PR/MR functionality, GitHub fine-grained personal access tokens need:
- **Contents: Read and write** (required for merging PRs)
- **Issues: Read and write** (for issue synchronization and comments)
- **Pull requests: Read and write** (for creating and merging PRs)
- **Metadata: Read** (automatically added)

## Pull/Merge Request Merging

**CRITICAL: ALWAYS use `aiops git pr-merge` for merging pull requests (GitHub) or merge requests (GitLab)**

### Command Syntax
```bash
# Basic merge (creates merge commit)
aiops git pr-merge <project> <pr-number>

# Squash merge (combines all commits into one)
aiops git pr-merge <project> <pr-number> --method squash

# Rebase merge (rebases commits onto target branch)
aiops git pr-merge <project> <pr-number> --method rebase

# Delete source branch after merging
aiops git pr-merge <project> <pr-number> --delete-branch

# Custom merge commit message
aiops git pr-merge <project> <pr-number> --message "Fix critical bug"

# Combine options
aiops git pr-merge <project> <pr-number> --method squash --delete-branch
```

### Merge Guidelines
- **NEVER use `gh pr merge`, `glab mr merge`, or GitHub/GitLab web UI for merging**
- **ALWAYS use `aiops git pr-merge`** to merge PRs/MRs
- The CLI automatically detects provider (GitHub/GitLab)
- Merge methods:
  - `merge` (default): Creates a merge commit preserving all commits
  - `squash`: Combines all commits into a single commit
  - `rebase`: Rebases commits onto target branch
- Use `--delete-branch` to automatically clean up the source branch after merge
- Requires integration with "Pull requests: Write" and "Contents: Write" permissions

### Commit Message Best Practices
- Reference issue in commits: `"Add validation (refs #123)"`
- Use descriptive commit messages
- Commit frequently with logical changes
- Each commit should be a working state when possible

## Production System Management

**IMPORTANT: AI agents CAN restart production when configuration changes require it**

### When Production Restart is Required
- ✅ Changes to `.env` configuration files
- ✅ Updates to environment variables (permission modes, API keys, etc.)
- ✅ System updates via `aiops system update`
- ✅ Database migrations
- ✅ After merging configuration changes to production
- ✅ After installing new dependencies

### Production Restart Commands
```bash
# Restart production backend (requires sudo/admin)
aiops system restart

# Or use the configured restart command directly
sudo systemctl restart aiops

# Combined update and restart
aiops system update-and-restart
```

### Production Safety Guidelines
- ✅ **DO restart production** when configuration changes require it (e.g., `.env` updates)
- ✅ **DO use `aiops system restart`** for controlled restarts
- ✅ **DO verify changes** before restarting when possible
- ✅ **DO sync dependencies** after pulling code updates
- ❌ **NEVER modify `/home/syseng/aiops/` directly** - work in personal workspaces and merge via PRs
- ❌ **NEVER auto-update production code** without testing in workspace first
- ❌ **NEVER restart production** for experimental changes or untested code

### Example: Configuration Change Workflow
```bash
# 1. Update production configuration (e.g., .env file)
# Edit /home/syseng/aiops/.env

# 2. Verify the change
cat /home/syseng/aiops/.env | grep CLAUDE_PERMISSION_MODE

# 3. Restart production to apply changes
aiops system restart

# 4. Monitor logs to ensure successful restart
tail -f /home/syseng/aiops/logs/aiops.log
```

**Key Principle:** Configuration changes in production `.env` files are safe to apply immediately with restarts. Code changes should always go through workspace → PR → merge → production deployment workflow.

---

## Current Issue Context
<!-- issue-context:start -->

NOTE: Generated issue context. Update before publishing if needed.

# 161 - Fix ModuleNotFoundError in /tmp/test_prod_yadm.py

        _Updated: 2025-11-28 18:11:28Z_

        ## Issue Snapshot
        - Provider: github
        - Status: open
        - Assignee: Ivo Marino
        - Labels: bug, fix
        - Source: https://github.com/floadsio/aiops/issues/161
        - Last Synced: 2025-11-28 18:11 UTC

        ## Issue Description
        Detailed issue description with:

## Overview
During execution of a Python script, we encounter a 'ModuleNotFoundError' for 'dotenv'.

## Requirements
- Ensure the script runs successfully.
- Address any missing dependencies or configuration issues.

## Acceptance Criteria
- [ ] The error is resolved and the script runs without errors.
- [ ] The issue does not reappear in future executions.

## Technical Notes
[Optional implementation notes]

        ## Project Context
        - Project: aiops
        - Repository: git@github.com:floadsio/aiops.git
        - Local Path: instance/repos/aiops

        ## Other Known Issues
        None listed.

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
