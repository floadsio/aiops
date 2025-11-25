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

```bash
# Create feature issue (works identically for GitHub, GitLab, Jira)
aiops issues create --project <project> \
  --integration <integration-id> \
  --title "Add user authentication system" \
  --description "Requirements:
- JWT-based authentication
- Login/logout endpoints
- Password hashing with bcrypt
- Session management

Acceptance criteria:
- Users can register and login
- Passwords are securely hashed
- Sessions expire after 24h" \
  --labels "feature,enhancement"

# Update issue (modify title, description, labels)
aiops issues update <issue-id> --title "Updated title" --description "New description"

# Comment on issue - IMPORTANT: Use internal issue ID, not external GitLab issue number
# Step 1: Find the internal ID by listing issues
aiops issues list --project <project> -o json | grep "external_id.*<external-number>"
# Step 2: Use the internal ID from the "id" field
aiops issues comment <internal-id> "Working on this issue"
# Step 3: Or use file for longer comments
aiops issues comment <internal-id> --file comment.txt

# Edit existing comment
aiops issues modify-comment <internal-id> <comment-id> "Updated comment text"

# Assign issue
aiops issues assign <internal-id> --user <username/account-id>
```

### Publishing Comments to Issues

**CRITICAL: Always use the internal issue ID, not the external GitLab/GitHub issue number**

1. **Find the internal issue ID:**
   ```bash
   aiops issues list --project <project> -o json | grep "external_id.*<number>"
   ```
   Use the value from the "id" field, not "external_id"

2. **Post comment from command line:**
   ```bash
   aiops issues comment <internal-id> "Your comment text"
   ```

3. **Post comment from file (recommended for longer comments):**
   ```bash
   aiops issues comment <internal-id> --file comment.txt
   ```

4. **Example workflow:**
   ```bash
   # Find issue (external ID 29 → internal ID 521)
   aiops issues list --project flamelet-kbe -o json | grep -A 15 '"external_id":"29"'

   # Post comment using internal ID
   aiops issues comment 521 --file comment.txt
   ```

### 2. Complete Issue Management Support

All providers (GitHub, GitLab, Jira) support full CRUD operations:

| Feature          | GitHub | GitLab | Jira |
|------------------|--------|--------|------|
| Create Issues    |   ✓    |   ✓    |  ✓   |
| Update Issues    |   ✓    |   ✓    |  ✓   |
| Close Issues     |   ✓    |   ✓    |  ✓   |
| Reopen Issues    |   ✓    |   ✓    |  ✓   |
| Add Comments     |   ✓    |   ✓    |  ✓   |
| Edit Comments    |   ✓    |   ✓    |  ✓   |
| Assign Issues    |   ✓    |   ✓    |  ✓   |

**Key capabilities:**
- User-level credential overrides (use personal tokens)
- Project-level credential overrides (project-specific tokens)
- Automatic @mention resolution for Jira
- Configurable transitions for Jira (close_transition, reopen_transition)

### 3. Create Feature/Fix Branch
- **NEVER commit directly to `main`** - main is for stable, tested code only
- **ALWAYS create a branch** after creating the issue
- Use descriptive branch names:
  - `feature/<feature-name>` for new features
  - `fix/<bug-description>` for bug fixes
  - `refactor/<component>` for refactoring
- Only merge to `main` after testing and code review (via PR/MR)

### Complete Workflow
```bash
# 1. Create issue (get the issue ID from output)
aiops issues create --project <project> --integration <id> --title "Fix login validation" --labels "bug"

# 2. Start from main and pull latest
aiops git checkout <project> main
aiops git pull <project>

# 3. Create and switch to feature/fix branch
# For features:
aiops git branch <project> feature/user-authentication
# For bugs:
aiops git branch <project> fix/login-empty-password-500

aiops git checkout <project> fix/login-empty-password-500

# 4. Make changes, commit frequently with issue reference
aiops git commit <project> "Add password validation (refs #123)" --files "app/routes/auth.py"
aiops git commit <project> "Add unit tests for validation (refs #123)" --files "tests/test_auth.py"

# 5. Push branch
aiops git push <project>

# 6. Create PR/MR for review
aiops git pr-create <project> \
  --title "Fix login 500 error with empty password (closes #123)" \
  --description "Fixes 500 error when submitting login with empty password.

Closes #123

Changes:
- Added password validation in login route
- Returns 400 with clear error message
- Added unit tests for edge cases

Testing:
- Tested manual login with empty password
- All existing tests pass" \
  --source fix/login-empty-password-500 \
  --target main \
  --assignee reviewer-username

# 7. After PR is approved, merge it
aiops git pr-merge <project> <pr-number> --delete-branch

# 8. Switch back to main and pull
aiops git checkout <project> main
aiops git pull <project>

# 9. Update and close the issue
aiops issues comment <internal-id> "Fixed and merged in PR #<pr-number>"
aiops issues close <internal-id>
```

### When to Create Issue + Branch
- ✅ New features or capabilities → `feature/` branch with `feature` or `enhancement` label
- ✅ Bug fixes → `fix/` branch with `bug` label
- ✅ Significant refactoring → `refactor/` branch with `refactor` label
- ✅ Breaking changes → `feature/` or `refactor/` branch with `breaking-change` label
- ✅ Experimental work → `feature/` or `experiment/` branch
- ✅ Any work that requires testing before deployment

### When Direct Commits to Main Are Acceptable (NO issue needed)
- ✅ Documentation updates (README, comments)
- ✅ Typo fixes in code or docs
- ✅ Version bumps
- ✅ Minor formatting/style fixes
- ✅ Urgent hotfixes (but still prefer branch + issue when time allows)

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

# 116 - Add Ollama availability check to System Status > AI Tools

        _Updated: 2025-11-25 23:17:04Z_

        ## Issue Snapshot
        - Provider: github
        - Status: open
        - Assignee: Ivo Marino
        - Labels: ai-tools, enhancement, system-status
        - Source: https://github.com/floadsio/aiops/issues/116
        - Last Synced: 2025-11-25 23:17 UTC

        ## Issue Description
        ## Overview
The System Status page includes an AI Tools section that monitors the availability of essential AI components. Ollama is a critical dependency required for AI-Assisted Issue Creation functionality, but there is currently no health check for it in the system status dashboard.

## Requirements
- Add an Ollama availability check to the System Status > AI Tools section
- Display Ollama connection status (available/unavailable)
- Show Ollama version information when available
- Follow the existing pattern used for other AI tool checks in the system status page

## Acceptance Criteria
- [ ] Ollama status appears in the AI Tools section of System Status
- [ ] Check correctly identifies when Ollama is running and accessible
- [ ] Check correctly identifies when Ollama is unavailable or not responding
- [ ] Ollama version is displayed when the service is available
- [ ] Error messages are user-friendly when Ollama is not available
- [ ] Check does not cause page load delays (reasonable timeout)

## Technical Notes
- Ollama typically runs on `http://localhost:11434`
- The `/api/version` endpoint can be used to check availability and get version info
- Consider using the existing health check patterns in `app/services/` or `app/routes/admin.py`
- Reference the existing AI tool checks for consistent UI presentation

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
