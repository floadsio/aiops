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

# 62 - Auto-generate AGENTS.override.md for all AI sessions with merged context

        _Updated: 2025-11-20 17:56:08Z_

        ## Issue Snapshot
        - Provider: github
        - Status: open
        - Assignee: Ivo Marino
        - Labels: enhancement, feature
        - Source: https://github.com/floadsio/aiops/issues/62
        - Last Synced: 2025-11-20 17:54 UTC

        ## Issue Description
        ## Overview

Ensure that `AGENTS.override.md` is automatically generated and properly populated when starting any AI session (Claude, Codex, Gemini), combining project context, global agent instructions, and issue-specific information into a single unified context file.

## Background

Currently, AGENTS.override.md generation may be inconsistent or incomplete when starting AI sessions. This file should always be generated automatically and contain the merged context from:
- Project's AGENTS.md file (if present in the repository)
- Global agent context (stored in the database)
- Issue context (when starting an issue-specific session)

## Requirements

- **Auto-generate AGENTS.override.md** when starting any AI session:
  - From web UI (all AI tool buttons)
  - From aiops CLI (`aiops sessions start`, `aiops issues work`, etc.)
  - For both project sessions and issue-specific sessions

- **Merge context sources in order**:
  1. Global agent context from database (if configured)
  2. Project's AGENTS.md file from repository (if present)
  3. Issue context (only for issue sessions)

- **Provide user feedback**:
  - Display confirmation message after generation
  - Show which sources were merged (e.g., "Generated AGENTS.override.md from: global context + AGENTS.md + issue #62")

- **Update instruction files**:
  - Ensure CLAUDE.md explicitly instructs to read AGENTS.override.md
  - Ensure GEMINI.md explicitly instructs to read AGENTS.override.md
  - Ensure AGENTS.md explicitly instructs to read AGENTS.override.md

- **Add test coverage**:
  - Test generation for project-only sessions
  - Test generation for issue sessions
  - Test merging of all three context sources
  - Test graceful handling when sources are missing

## Acceptance Criteria

- [ ] AGENTS.override.md is automatically generated for all AI session starts (web UI + CLI)
- [ ] File correctly merges global context + AGENTS.md + issue context (when applicable)
- [ ] User receives confirmation message showing what was merged
- [ ] CLAUDE.md, GEMINI.md, and AGENTS.md all reference AGENTS.override.md
- [ ] Test coverage added for generation and merging logic
- [ ] Works for all AI tools: Claude, Codex, Gemini
- [ ] Works for both project sessions and issue sessions
- [ ] Gracefully handles missing context sources (e.g., no AGENTS.md in repo)

## Technical Notes

- Generation should happen in `app/ai_sessions.py` before starting the tmux session
- May need to call workspace service to get project's AGENTS.md from repository
- Global context is retrieved via `app/services/agent_context_service.py`
- Issue context formatting is already handled by the populate AGENTS.override.md feature
- Consider using the existing `AGENTS.override.md` generation logic and ensuring it's called consistently

        

## Issue Comments (1)

            **ivomarino** on 2025-11-20T17:54:52+00:00 ([link](https://github.com/floadsio/aiops/issues/62#issuecomment-3559330450))

## Issue Ready for Implementation

I've structured this issue and prepared it for implementation:

### ✅ Updated Title
**Auto-generate AGENTS.override.md for all AI sessions with merged context**

### ✅ Created Comprehensive Description
The issue now has a clear structure with:
- **Overview**: High-level summary of the feature
- **Background**: Context about why this is needed
- **Requirements**: Detailed list of what needs to be implemented
- **Acceptance Criteria**: Checkboxes for tracking completion
- **Technical Notes**: Implementation guidance

### ✅ Updated Labels
- Removed: `draft`, `bug`
- Added: `feature`, `enhancement`

### ✅ Created Feature Branch
Branch `feature/62-auto-generate-agents-override` has been created and checked out.

### Next Steps

The implementation should focus on:

1. **Core generation logic** - Ensure AGENTS.override.md is created automatically in `app/ai_sessions.py` before starting tmux sessions

2. **Context merging** - Combine three sources in order:
   - Global agent context from database
   - Project's AGENTS.md from repository
   - Issue context (for issue sessions)

3. **User feedback** - Display what was merged after generation

4. **Instruction file updates** - Update CLAUDE.md, GEMINI.md, and AGENTS.md to reference AGENTS.override.md

5. **Test coverage** - Add tests for all generation scenarios

Ready to start implementation! 🚀

## Project Context
        - Project: aiops
        - Repository: git@github.com:floadsio/aiops.git
        - Local Path: instance/repos/aiops

        ## Other Known Issues
        - [github] 56: When I want to start a new Session in aiops and select Codex or other AI, it should not reuse another tool; status=closed; assignee=Michael Turko; labels=bug; updated=2025-11-20 17:38 UTC; url=https://github.com/floadsio/aiops/issues/56
- [github] 55: Add Activity page to track all aiops operations; status=closed; assignee=Ivo Marino; labels=enhancement, feature; updated=2025-11-20 12:05 UTC; url=https://github.com/floadsio/aiops/issues/55
- [github] 53: Enable Claude Code yolo mode for AI sessions by default; status=closed; assignee=Ivo Marino; labels=enhancement, feature; updated=2025-11-19 23:13 UTC; url=https://github.com/floadsio/aiops/issues/53
- [github] 51: Auto-assign AI-assisted issues to creating user; status=closed; labels=bug; updated=2025-11-19 23:01 UTC; url=https://github.com/floadsio/aiops/issues/51
- [github] 49: Handle failed integrations gracefully during issue sync; status=closed; assignee=Ivo Marino; labels=bug; updated=2025-11-19 22:50 UTC; url=https://github.com/floadsio/aiops/issues/49
- [github] 45: Draft: When you refresh issues it may fail because a private GitLab...; status=closed; labels=bug, draft; updated=2025-11-19 22:42 UTC; url=https://github.com/floadsio/aiops/issues/45
- [github] 46: Draft: When you refresh issues it may fail because a private GitLab...; status=closed; labels=bug, draft; updated=2025-11-19 22:42 UTC; url=https://github.com/floadsio/aiops/issues/46
- [github] 48: Draft: When you refresh issues it may fail because a private GitLab...; status=closed; labels=bug, draft; updated=2025-11-19 22:37 UTC; url=https://github.com/floadsio/aiops/issues/48
- [github] 36: Feature: AI-assisted issue creation with automated branch and session setup; status=closed; assignee=Ivo Marino; labels=enhancement, feature, ai; updated=2025-11-19 22:36 UTC; url=https://github.com/floadsio/aiops/issues/36
- [github] 47: Draft: When you refresh issues it may fail because a private GitLab...; status=closed; labels=bug, draft; updated=2025-11-19 22:29 UTC; url=https://github.com/floadsio/aiops/issues/47
- [github] 44: Draft: When you refresh issues it may fail because a private GitLab...; status=closed; labels=bug, draft; updated=2025-11-19 22:22 UTC; url=https://github.com/floadsio/aiops/issues/44
- [github] 43: Draft: When you refresh issues it may fail because a private GitLab...; status=closed; labels=bug, draft; updated=2025-11-19 22:22 UTC; url=https://github.com/floadsio/aiops/issues/43
- [github] 42: Draft: When you refresh issues it may fail because a private GitLab...; status=closed; labels=bug, draft; updated=2025-11-19 22:22 UTC; url=https://github.com/floadsio/aiops/issues/42
- [github] 41: Draft: When you refresh issues it may fail because a private GitLab...; status=closed; labels=bug, draft; updated=2025-11-19 22:21 UTC; url=https://github.com/floadsio/aiops/issues/41
- [github] 40: Draft: When you refresh issues it may fail because a private GitLab...; status=closed; labels=bug, draft; updated=2025-11-19 22:21 UTC; url=https://github.com/floadsio/aiops/issues/40
- [github] 39: Draft: When you refresh issues it may fail because a private GitLab...; status=closed; labels=bug, draft; updated=2025-11-19 22:21 UTC; url=https://github.com/floadsio/aiops/issues/39
- [github] 38: Draft: When you refresh issues it may fail because a private GitLab...; status=closed; labels=bug, draft; updated=2025-11-19 22:21 UTC; url=https://github.com/floadsio/aiops/issues/38
- [github] 34: Evaluate using official CLI tools (gh, glab) for git operations; status=closed; assignee=Ivo Marino; labels=enhancement, feature, evaluation; updated=2025-11-19 17:22 UTC; url=https://github.com/floadsio/aiops/issues/34
- [github] 32: SSH key management: Store keys in database for multi-user access; status=closed; assignee=Ivo Marino; labels=enhancement, feature, security; updated=2025-11-19 17:22 UTC; url=https://github.com/floadsio/aiops/issues/32
- [github] 31: Add --file option to 'aiops issues comment' command; status=closed; assignee=Ivo Marino; labels=enhancement, feature; updated=2025-11-19 15:36 UTC; url=https://github.com/floadsio/aiops/issues/31
- [github] 15: Feature: Add GitHub Comment Editing Support; status=closed; assignee=Ivo Marino; labels=enhancement, feature; updated=2025-11-19 13:36 UTC; url=https://github.com/floadsio/aiops/issues/15
- [github] 19: Issue: Per-user workspaces require directory traversal permissions; status=closed; assignee=Ivo Marino; labels=bug, infrastructure, workspace; updated=2025-11-19 13:25 UTC; url=https://github.com/floadsio/aiops/issues/19
- [github] 16: User-specific integration credentials for personal tokens; status=closed; assignee=Ivo Marino; updated=2025-11-19 13:25 UTC; url=https://github.com/floadsio/aiops/issues/16
- [github] 29: Add pr-merge command to aiops CLI for GitHub and GitLab; status=closed; assignee=Ivo Marino; labels=enhancement, feature; updated=2025-11-19 13:13 UTC; url=https://github.com/floadsio/aiops/issues/29
- [github] 22: Fix tmux session buttons visibility on mobile (responsive mode); status=closed; assignee=Ivo Marino; updated=2025-11-19 13:13 UTC; url=https://github.com/floadsio/aiops/issues/22
- [github] 27: Fix AI tool button routing - wrong tool started from pinned issues; status=closed; assignee=Ivo Marino; updated=2025-11-19 13:13 UTC; url=https://github.com/floadsio/aiops/issues/27
- [github] 25: Group duplicate assignee names in Issues dashboard; status=closed; assignee=Ivo Marino; updated=2025-11-19 10:53 UTC; url=https://github.com/floadsio/aiops/issues/25
- [github] 23: Add web UI for editing integration names and details; status=closed; assignee=Ivo Marino; updated=2025-11-19 10:12 UTC; url=https://github.com/floadsio/aiops/issues/23
- [github] 24: Fix 500 error when setting personal API token for integration; status=closed; assignee=Ivo Marino; updated=2025-11-19 10:04 UTC; url=https://github.com/floadsio/aiops/issues/24
- [github] 21: Decouple tmux sessions from backend process lifecycle; status=closed; assignee=Ivo Marino; updated=2025-11-18 15:29 UTC; url=https://github.com/floadsio/aiops/issues/21
- [github] 20: Bug: Per-user sessions not using sudo when reusing existing tmux windows; status=closed; assignee=Ivo Marino; labels=bug, critical, security; updated=2025-11-18 13:32 UTC; url=https://github.com/floadsio/aiops/issues/20
- [github] 18: Setup: Michael needs personal SSH key for GitHub authentication; status=closed; assignee=Ivo Marino; labels=setup, infrastructure; updated=2025-11-18 13:15 UTC; url=https://github.com/floadsio/aiops/issues/18
- [github] 17: Issue: Confusing 'Status unavailable' message for newly initialized workspaces; status=closed; assignee=Ivo Marino; labels=bug, ux; updated=2025-11-18 12:29 UTC; url=https://github.com/floadsio/aiops/issues/17
- [github] 13: Feature: Database Backup and Download via CLI and Web UI; status=closed; assignee=Ivo Marino; labels=enhancement, feature; updated=2025-11-18 11:45 UTC; url=https://github.com/floadsio/aiops/issues/13
- [github] 14: Feature: Add GitLab Issue Comment Support; status=closed; assignee=Ivo Marino; labels=enhancement, feature; updated=2025-11-18 02:49 UTC; url=https://github.com/floadsio/aiops/issues/14
- [github] 12: Cleanup tests and test CLI commenting features; status=closed; updated=2025-11-17 22:07 UTC; url=https://github.com/floadsio/aiops/issues/12
- [github] 11: Feature: Global AGENTS.md content for override files; status=closed; assignee=Ivo Marino; labels=enhancement, feature; updated=2025-11-17 22:00 UTC; url=https://github.com/floadsio/aiops/issues/11
- [github] 10: Publish aiops-cli v0.3.0 to PyPI; status=open; assignee=Ivo Marino; labels=enhancement; updated=2025-11-17 21:45 UTC; url=https://github.com/floadsio/aiops/issues/10
- [github] 8: Issue: Implement aiops CLI Client for macOS & Linux; status=closed; assignee=Ivo Marino; labels=enhancement; updated=2025-11-17 21:00 UTC; url=https://github.com/floadsio/aiops/issues/8
- [github] 9: Publish aiops-cli to PyPI; status=closed; assignee=Ivo Marino; labels=enhancement; updated=2025-11-17 20:56 UTC; url=https://github.com/floadsio/aiops/issues/9
- [github] 7: Issue: Implement a Public AIops API for AI Agents and CLI Clients; status=closed; assignee=Ivo Marino; labels=enhancement; updated=2025-11-16 22:55 UTC; url=https://github.com/floadsio/aiops/issues/7
- [github] 4: Issue: Improve UI Responsiveness + Redesign Main Menu Layout; status=closed; assignee=Ivo Marino; labels=enhancement; updated=2025-11-16 13:43 UTC; url=https://github.com/floadsio/aiops/issues/4
- [github] 5: Issue: Add Project Filter to Issues Page; status=closed; assignee=Ivo Marino; updated=2025-11-15 17:34 UTC; url=https://github.com/floadsio/aiops/issues/5
- [github] 3: Feature: Create New Issues Directly from the AIops Issues Page; status=closed; assignee=Ivo Marino; updated=2025-11-15 17:34 UTC; url=https://github.com/floadsio/aiops/issues/3
- [github] 6: Issue: Add Close Button to Pinned Issues on Dashboard; status=closed; assignee=Ivo Marino; updated=2025-11-15 17:33 UTC; url=https://github.com/floadsio/aiops/issues/6
- [github] 1: Add Cross-Platform Issue Creation + User Mapping Support in aiops; status=closed; assignee=Ivo Marino; labels=enhancement; updated=2025-11-15 14:41 UTC; url=https://github.com/floadsio/aiops/issues/1
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
