## CRITICAL: Issue ID Usage for AI Agents

**NEVER use external issue numbers (e.g., GitHub #118, GitLab !29, Jira PROJ-123) with `aiops` CLI commands.**

**ALWAYS use internal database IDs** for all `aiops issues` commands.

### Quick Reference: Finding Internal IDs

```bash
# Method 1: Sync issues first (REQUIRED if issue not in local DB)
aiops issues sync --project <project>

# Method 2: Find internal ID from external number
aiops issues list --project <project> -o json | grep '"external_id":"118"' -B 5 | grep '"id"'
# Returns: "id": 680  ← Use this number!

# Method 3: List and search visually
aiops issues list --project <project> | grep -i "keyword"
```

### Correct vs Incorrect Usage

❌ **WRONG** - Using external GitHub issue number:
```bash
aiops issues comment 118 "my comment"  # Will fail with 404!
```

✅ **CORRECT** - Using internal database ID:
```bash
# Step 1: Find internal ID
aiops issues list --project aiops -o json | grep '"external_id":"118"' -B 5 | grep '"id"'
# Output: "id": 680

# Step 2: Use internal ID
aiops issues comment 680 "my comment"  # Works!
```

### Standard Workflow for AI Agents

**When working on an issue mentioned in AGENTS.override.md:**

1. **Sync first** (if issue might not be in local DB):
   ```bash
   aiops issues sync --project <project>
   ```

2. **Find internal ID** from external reference:
   ```bash
   aiops issues list --project <project> -o json | grep '"external_id":"<number>"' -B 5 | grep '"id"'
   ```

3. **Use internal ID** for all operations:
   ```bash
   aiops issues comment <internal-id> "Starting work on this issue"
   aiops issues comment <internal-id> --file progress-update.txt
   aiops issues update <internal-id> --title "New title"
   aiops issues close <internal-id>
   ```

### Why This Matters

- **External IDs** (GitHub #118, GitLab !29): What users see in the provider's UI
- **Internal IDs** (680, 521): aiops database primary keys, required for CLI operations
- The `aiops` CLI works with the **local database**, not external APIs directly
- Using external IDs will result in `404 NOT FOUND` errors

---

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

# Comment on issue - IMPORTANT: Use internal issue ID, not external GitLab/GitHub issue number
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

# 9. Update and close the issue (REMEMBER: use internal ID!)
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

---

---

## Current Issue Context
<!-- issue-context:start -->

NOTE: Generated issue context. Update before publishing if needed.

# 123 - Add integration selector to AI-Assisted Issue creation form

        _Updated: 2025-11-26 08:07:05Z_

        ## Issue Snapshot
        - Provider: github
        - Status: open
        - Assignee: ivomarino
        - Labels: enhancement, feature, ui
        - Source: https://github.com/floadsio/aiops/issues/123
        - Last Synced: 2025-11-26 07:43 UTC

        ## Issue Description
        ## Overview

Currently, when creating an AI-Assisted Issue, there is no way to specify which integration (GitHub, GitLab, or Jira) should be used for creating the upstream issue. Since projects can be mapped to multiple integrations, users need the ability to choose which integration to use when creating a new AI-Assisted Issue.

## Requirements

- Add a dynamic dropdown to the AI-Assisted Issue creation form that shows available integrations for the selected project
- The integration dropdown should only populate after a project is selected
- The dropdown should display all integrations linked to the chosen project (GitHub, GitLab, Jira)
- The selected integration should be used when creating the upstream issue
- Handle edge cases: projects with no integrations, projects with only one integration

## Acceptance Criteria

- [ ] Project selection triggers dynamic loading of available integrations
- [ ] Integration dropdown displays integration type and name (e.g., "GitHub - myorg/myrepo")
- [ ] Integration dropdown is disabled/hidden until a project is selected
- [ ] Selected integration is passed through to issue creation logic
- [ ] Form validation ensures an integration is selected before submission
- [ ] UI provides clear feedback when a project has no integrations configured
- [ ] Works correctly with JavaScript enabled (dynamic population)

## Technical Notes

- The AI-Assisted Issue form is likely in `app/templates/` - will need to add JavaScript for dynamic dropdown population
- May need a new API endpoint like `/api/v1/projects/<id>/integrations` to fetch integrations for a project
- The integration selector should use the same styling as other form elements (Pico CSS)
- Consider pre-selecting the integration if a project has only one configured

        

## Issue Comments (1)

            **ivomarino** on 2025-11-26T07:43:43+00:00 ([link](https://github.com/floadsio/aiops/issues/123#issuecomment-3579881153))

_Created via aiops by @ivomarino_

## Project Context
        - Project: aiops
        - Repository: git@github.com:floadsio/aiops.git
        - Local Path: instance/repos/aiops

        ## Other Known Issues
        - [github] 1: Add Cross-Platform Issue Creation + User Mapping Support in aiops; status=closed; assignee=Ivo Marino; labels=enhancement; updated=2025-11-15 14:41 UTC; url=https://github.com/floadsio/aiops/issues/1
- [github] 3: Feature: Create New Issues Directly from the AIops Issues Page; status=closed; assignee=Ivo Marino; updated=2025-11-15 17:34 UTC; url=https://github.com/floadsio/aiops/issues/3
- [github] 5: Issue: Add Project Filter to Issues Page; status=closed; assignee=Ivo Marino; updated=2025-11-15 17:34 UTC; url=https://github.com/floadsio/aiops/issues/5
- [github] 4: Issue: Improve UI Responsiveness + Redesign Main Menu Layout; status=closed; assignee=Ivo Marino; labels=enhancement; updated=2025-11-16 13:43 UTC; url=https://github.com/floadsio/aiops/issues/4
- [github] 6: Issue: Add Close Button to Pinned Issues on Dashboard; status=closed; assignee=Ivo Marino; updated=2025-11-15 17:33 UTC; url=https://github.com/floadsio/aiops/issues/6
- [github] 7: Issue: Implement a Public AIops API for AI Agents and CLI Clients; status=closed; assignee=Ivo Marino; labels=enhancement; updated=2025-11-16 22:55 UTC; url=https://github.com/floadsio/aiops/issues/7
- [github] 8: Issue: Implement aiops CLI Client for macOS & Linux; status=closed; assignee=Ivo Marino; labels=enhancement; updated=2025-11-17 21:00 UTC; url=https://github.com/floadsio/aiops/issues/8
- [github] 9: Publish aiops-cli to PyPI; status=closed; assignee=Ivo Marino; labels=enhancement; updated=2025-11-17 20:56 UTC; url=https://github.com/floadsio/aiops/issues/9
- [github] 10: Publish aiops-cli v0.3.0 to PyPI; status=open; assignee=Ivo Marino; labels=enhancement; updated=2025-11-17 21:45 UTC; url=https://github.com/floadsio/aiops/issues/10
- [github] 11: Feature: Global AGENTS.md content for override files; status=closed; assignee=Ivo Marino; labels=enhancement, feature; updated=2025-11-17 22:00 UTC; url=https://github.com/floadsio/aiops/issues/11
- [github] 12: Cleanup tests and test CLI commenting features; status=closed; updated=2025-11-17 22:07 UTC; url=https://github.com/floadsio/aiops/issues/12
- [github] 13: Feature: Database Backup and Download via CLI and Web UI; status=closed; assignee=Ivo Marino; labels=enhancement, feature; updated=2025-11-18 11:45 UTC; url=https://github.com/floadsio/aiops/issues/13
- [github] 14: Feature: Add GitLab Issue Comment Support; status=closed; assignee=Ivo Marino; labels=enhancement, feature; updated=2025-11-18 02:49 UTC; url=https://github.com/floadsio/aiops/issues/14
- [github] 15: Feature: Add GitHub Comment Editing Support; status=closed; assignee=Ivo Marino; labels=enhancement, feature; updated=2025-11-19 13:36 UTC; url=https://github.com/floadsio/aiops/issues/15
- [github] 16: User-specific integration credentials for personal tokens; status=closed; assignee=Ivo Marino; updated=2025-11-19 13:25 UTC; url=https://github.com/floadsio/aiops/issues/16
- [github] 17: Issue: Confusing 'Status unavailable' message for newly initialized workspaces; status=closed; assignee=Ivo Marino; labels=bug, ux; updated=2025-11-18 12:29 UTC; url=https://github.com/floadsio/aiops/issues/17
- [github] 18: Setup: Michael needs personal SSH key for GitHub authentication; status=closed; assignee=Ivo Marino; labels=setup, infrastructure; updated=2025-11-18 13:15 UTC; url=https://github.com/floadsio/aiops/issues/18
- [github] 19: Issue: Per-user workspaces require directory traversal permissions; status=closed; assignee=Ivo Marino; labels=bug, infrastructure, workspace; updated=2025-11-19 13:25 UTC; url=https://github.com/floadsio/aiops/issues/19
- [github] 20: Bug: Per-user sessions not using sudo when reusing existing tmux windows; status=closed; assignee=Ivo Marino; labels=bug, critical, security; updated=2025-11-18 13:32 UTC; url=https://github.com/floadsio/aiops/issues/20
- [github] 21: Decouple tmux sessions from backend process lifecycle; status=closed; assignee=Ivo Marino; updated=2025-11-18 15:29 UTC; url=https://github.com/floadsio/aiops/issues/21
- [github] 22: Fix tmux session buttons visibility on mobile (responsive mode); status=closed; assignee=Ivo Marino; updated=2025-11-19 13:13 UTC; url=https://github.com/floadsio/aiops/issues/22
- [github] 23: Add web UI for editing integration names and details; status=closed; assignee=Ivo Marino; updated=2025-11-19 10:12 UTC; url=https://github.com/floadsio/aiops/issues/23
- [github] 24: Fix 500 error when setting personal API token for integration; status=closed; assignee=Ivo Marino; updated=2025-11-19 10:04 UTC; url=https://github.com/floadsio/aiops/issues/24
- [github] 25: Group duplicate assignee names in Issues dashboard; status=closed; assignee=Ivo Marino; updated=2025-11-19 10:53 UTC; url=https://github.com/floadsio/aiops/issues/25
- [github] 27: Fix AI tool button routing - wrong tool started from pinned issues; status=closed; assignee=Ivo Marino; updated=2025-11-19 13:13 UTC; url=https://github.com/floadsio/aiops/issues/27
- [github] 29: Add pr-merge command to aiops CLI for GitHub and GitLab; status=closed; assignee=Ivo Marino; labels=enhancement, feature; updated=2025-11-19 13:13 UTC; url=https://github.com/floadsio/aiops/issues/29
- [github] 31: Add --file option to 'aiops issues comment' command; status=closed; assignee=Ivo Marino; labels=enhancement, feature; updated=2025-11-19 15:36 UTC; url=https://github.com/floadsio/aiops/issues/31
- [github] 32: SSH key management: Store keys in database for multi-user access; status=closed; assignee=Ivo Marino; labels=enhancement, feature, security; updated=2025-11-19 17:22 UTC; url=https://github.com/floadsio/aiops/issues/32
- [github] 34: Evaluate using official CLI tools (gh, glab) for git operations; status=closed; assignee=Ivo Marino; labels=enhancement, feature, evaluation; updated=2025-11-19 17:22 UTC; url=https://github.com/floadsio/aiops/issues/34
- [github] 36: Feature: AI-assisted issue creation with automated branch and session setup; status=closed; assignee=Ivo Marino; labels=enhancement, feature, ai; updated=2025-11-19 22:36 UTC; url=https://github.com/floadsio/aiops/issues/36
- [github] 42: Draft: When you refresh issues it may fail because a private GitLab...; status=closed; labels=bug, draft; updated=2025-11-19 22:22 UTC; url=https://github.com/floadsio/aiops/issues/42
- [github] 49: Handle failed integrations gracefully during issue sync; status=closed; assignee=Ivo Marino; labels=bug; updated=2025-11-19 22:50 UTC; url=https://github.com/floadsio/aiops/issues/49
- [github] 51: Auto-assign AI-assisted issues to creating user; status=closed; labels=bug; updated=2025-11-19 23:01 UTC; url=https://github.com/floadsio/aiops/issues/51
- [github] 53: Enable Claude Code yolo mode for AI sessions by default; status=closed; assignee=Ivo Marino; labels=enhancement, feature; updated=2025-11-19 23:13 UTC; url=https://github.com/floadsio/aiops/issues/53
- [github] 55: Add Activity page to track all aiops operations; status=closed; assignee=Ivo Marino; labels=enhancement, feature; updated=2025-11-20 12:05 UTC; url=https://github.com/floadsio/aiops/issues/55
- [github] 56: When I want to start a new Session in aiops and select Codex or other AI, it should not reuse another tool; status=closed; assignee=Michael Turko; labels=bug; updated=2025-11-20 17:38 UTC; url=https://github.com/floadsio/aiops/issues/56
- [github] 62: Auto-generate AGENTS.override.md for all AI sessions with merged context; status=closed; assignee=Ivo Marino; labels=enhancement, feature; updated=2025-11-20 18:15 UTC; url=https://github.com/floadsio/aiops/issues/62
- [github] 64: Add automatic initial prompt to AI tools to read AGENTS.override.md; status=open; assignee=Ivo Marino; labels=enhancement, feature; updated=2025-11-20 18:20 UTC; url=https://github.com/floadsio/aiops/issues/64
- [github] 65: Filter AGENTS.override.md from git dirty status check; status=closed; assignee=Michael Turko; labels=enhancement, ux; updated=2025-11-22 03:29 UTC; url=https://github.com/floadsio/aiops/issues/65
- [github] 66: Add statistics and status page for issue resolution metrics; status=closed; assignee=Ivo Marino; labels=enhancement, feature; updated=2025-11-21 09:10 UTC; url=https://github.com/floadsio/aiops/issues/66
- [github] 68: Add feature to remap issues between aiops projects; status=closed; assignee=Ivo Marino; updated=2025-11-21 09:22 UTC; url=https://github.com/floadsio/aiops/issues/68
- [github] 69: Fix 'aiops update' failure with stale generated files; status=closed; assignee=Ivo Marino; labels=bug, cli; updated=2025-11-21 09:33 UTC; url=https://github.com/floadsio/aiops/issues/69
- [github] 70: Display tenant name alongside project name to avoid confusion; status=closed; assignee=Ivo Marino; updated=2025-11-23 20:00 UTC; url=https://github.com/floadsio/aiops/issues/70
- [github] 71: Allow integrations to map to multiple projects; status=closed; assignee=Ivo Marino; labels=enhancement, feature; updated=2025-11-23 20:00 UTC; url=https://github.com/floadsio/aiops/issues/71
- [github] 73: Enable file/image transfer from local machine to AI session workspace; status=closed; assignee=Michael Turko; labels=draft; updated=2025-11-25 15:09 UTC; url=https://github.com/floadsio/aiops/issues/73
- [github] 76: Fix AI-created issues/PRs showing wrong creator (always ivomarino); status=closed; assignee=Ivo Marino; labels=bug, draft; updated=2025-11-24 14:27 UTC; url=https://github.com/floadsio/aiops/issues/76
- [github] 77: Draft: The AI assisted Issue functionality seems to be broken; status=closed; assignee=Michael Turko; labels=draft; updated=2025-11-22 08:19 UTC; url=https://github.com/floadsio/aiops/issues/77
- [github] 81: Add assignee filtering to issues list command; status=closed; assignee=Michael Turko; labels=enhancement, feature, draft, cli; updated=2025-11-25 04:35 UTC; url=https://github.com/floadsio/aiops/issues/81
- [github] 85: Add creator attribution comments to Jira issues; status=closed; assignee=Michael Turko; labels=enhancement, feature; updated=2025-11-24 14:35 UTC; url=https://github.com/floadsio/aiops/issues/85
- [github] 87: Support per-integration Jira account IDs for attribution; status=closed; assignee=Michael Turko; labels=enhancement, feature; updated=2025-11-24 15:41 UTC; url=https://github.com/floadsio/aiops/issues/87
- [github] 89: Codex AI-assisted issue creation fails with unexpected argument; status=closed; assignee=Ivo Marino; labels=bug; updated=2025-11-25 22:01 UTC; url=https://github.com/floadsio/aiops/issues/89
- [github] 91: Migrate legacy API routes to v1 API (broken after issue #81 fix); status=closed; assignee=Michael Turko; updated=2025-11-25 05:28 UTC; url=https://github.com/floadsio/aiops/issues/91
- [github] 92: Email notifications show wrong sender name (shared PAT owner instead of actual user); status=open; assignee=Michael Turko; updated=2025-11-25 05:39 UTC; url=https://github.com/floadsio/aiops/issues/92
- [github] 93: Add session close/kill button to UI; status=open; assignee=Michael Turko; labels=enhancement, feature, ui; updated=2025-11-25 09:38 UTC; url=https://github.com/floadsio/aiops/issues/93
- [github] 94: Add like button to issues for expressing support; status=closed; assignee=Michael Turko; labels=enhancement, feature, ui; updated=2025-11-25 09:57 UTC; url=https://github.com/floadsio/aiops/issues/94
- [github] 95: Add rocket reaction button to issues for expressing great ideas; status=closed; assignee=Michael Turko; labels=enhancement, feature, ui; updated=2025-11-25 09:57 UTC; url=https://github.com/floadsio/aiops/issues/95
- [github] 96: Add heart button to issues for quick reactions; status=closed; assignee=Michael Turko; labels=enhancement, feature, ui; updated=2025-11-25 09:57 UTC; url=https://github.com/floadsio/aiops/issues/96
- [github] 97: Add thumbs down reaction button to issues; status=closed; assignee=Michael Turko; labels=enhancement, feature, ui; updated=2025-11-25 09:57 UTC; url=https://github.com/floadsio/aiops/issues/97
- [github] 101: Fix: Workspace initialization race condition causing false failures; status=open; labels=bug, enhancement; updated=2025-11-25 10:39 UTC; url=https://github.com/floadsio/aiops/issues/101
- [github] 102: Integrate self-hosted Ollama for AI-assisted issue text generation; status=closed; assignee=Ivo Marino; labels=bug; updated=2025-11-25 18:02 UTC; url=https://github.com/floadsio/aiops/issues/102
- [github] 106: Add end-to-end functional health checks for core aiops features; status=closed; assignee=Ivo Marino; labels=feature, cli, testing, health-monitoring, web-ui; updated=2025-11-25 15:54 UTC; url=https://github.com/floadsio/aiops/issues/106
- [github] 111: Integrate self-hosted Ollama for AI-assisted issue generation; status=closed; assignee=Ivo Marino; labels=enhancement, feature, ai; updated=2025-11-25 22:09 UTC; url=https://github.com/floadsio/aiops/issues/111
- [github] 116: Add Ollama availability check to System Status > AI Tools; status=closed; assignee=Ivo Marino; labels=enhancement, ai-tools, system-status; updated=2025-11-25 23:25 UTC; url=https://github.com/floadsio/aiops/issues/116
- [github] 117: CLI version display is hardcoded instead of reading from VERSION file; status=closed; assignee=Ivo Marino; labels=bug, cli; updated=2025-11-25 23:40 UTC; url=https://github.com/floadsio/aiops/issues/117
- [github] 118: Jira issue comments not syncing on refresh; status=open; assignee=Ivo Marino; labels=bug, jira, sync; updated=2025-11-26 00:26 UTC; url=https://github.com/floadsio/aiops/issues/118
- [github] 119: Test Ollama integration and local LLM functionality; status=closed; assignee=Michael Turko; labels=ai, testing, integration; updated=2025-11-26 05:37 UTC; url=https://github.com/floadsio/aiops/issues/119
- [github] 120: DCX MySQL Backup Restore Test - November 2025; status=open; assignee=Michael Turko; labels=operations, backup, mysql, monthly-task; updated=2025-11-26 05:35 UTC; url=https://github.com/floadsio/aiops/issues/120
- [github] 121: Fix issue/PR attribution to use current user instead of hardcoded author; status=closed; assignee=Michael Turko; labels=bug, authentication, user-context; updated=2025-11-26 06:24 UTC; url=https://github.com/floadsio/aiops/issues/121
- [github] 124: AI tool selection ignored when starting issue work sessions; status=open; assignee=Ivo Marino; labels=bug, cli, sessions; updated=2025-11-26 07:50 UTC; url=https://github.com/floadsio/aiops/issues/124

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
