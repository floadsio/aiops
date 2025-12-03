## Issue Implementation Plans

**CRITICAL: Use issue plans to document and resume complex implementation work**

### When to Create Plans
- **Multi-step features** requiring careful coordination
- **Complex refactoring** with multiple affected components
- **Breaking changes** needing detailed migration strategy
- **Large features** that span multiple sessions or days
- **Architectural decisions** that need documentation

### Creating and Managing Plans

```bash
# Create/update a plan for an issue
aiops issues plan set <issue-id> -f PLAN.md

# Or pipe from stdin
cat PLAN.md | aiops issues plan set <issue-id> --stdin

# View existing plan
aiops issues plan get <issue-id>

# Remove plan
aiops issues plan clear <issue-id>
```

### Plan Structure

Implementation plans should follow this structure:

```markdown
# Implementation Plan: [Feature Name]

## Overview
Brief description of what needs to be built and why.

## Architecture
Key architectural decisions and design patterns to use.

## Implementation Phases

### Phase 1: [Name]
**Files to modify:**
- `path/to/file.py` - What changes are needed
- `path/to/template.html` - What changes are needed

**Tasks:**
1. Task description
2. Task description

### Phase 2: [Name]
...

## API Design (if applicable)
Document new API endpoints, request/response formats.

## Testing Strategy
How to test each phase.

## Rollout Plan
Steps for deploying to production.
```

### How Plans Work

1. **Storage**: Plans are stored in the database, associated with issues
2. **Visibility**: Issues list shows 📋 indicator when a plan exists
3. **Auto-injection**: When you start work on an issue with a plan, the plan is automatically included in `AGENTS.override.md`
4. **Resume capability**: Plans allow you to resume work exactly where you left off
5. **Collaboration**: Multiple agents or developers can follow the same plan

### Best Practices

- ✅ **Create plans BEFORE starting complex work** - think through the implementation first
- ✅ **Update plans as you work** - document decisions and discoveries
- ✅ **Mark phases complete** - track progress through the implementation
- ✅ **Include file paths** - make it easy to find what needs changing
- ✅ **Document decisions** - explain WHY, not just WHAT
- ❌ **Don't create plans for trivial tasks** - simple one-file changes don't need plans
- ❌ **Don't let plans go stale** - update or delete them when no longer relevant

### Example Workflow

```bash
# Step 1: Create issue for new feature
aiops issues create --project myproject --integration 1 \
  --title "Feature: Add user authentication" \
  --description "Implement JWT-based authentication..."

# Step 2: Create implementation plan
cat > PLAN.md <<'EOF'
# Implementation Plan: User Authentication

## Overview
Add JWT-based authentication to API endpoints.

## Implementation Phases

### Phase 1: Database Models
- Add User model with hashed passwords
- Add APIKey model for token management

### Phase 2: Authentication Service
- Create auth_service.py with JWT handling
- Add password hashing and verification

### Phase 3: API Endpoints
- POST /api/v1/auth/login
- POST /api/v1/auth/logout
- Protect existing endpoints with @require_auth

### Phase 4: Testing
- Unit tests for auth service
- Integration tests for protected endpoints
EOF

aiops issues plan set 123 -f PLAN.md

# Step 3: Start work (plan auto-loads in AGENTS.override.md)
aiops issues work 123

# Step 4: Update plan as you progress
# Edit PLAN.md to mark Phase 1 complete, add notes
aiops issues plan set 123 -f PLAN.md

# Step 5: When done, close issue (plan remains for reference)
aiops issues close 123
```

---

## Git Commit Guidelines

**CRITICAL: NEVER mention AI tools in commits**

- NEVER include "Claude", "AI", "Generated with", "Co-Authored-By: Claude" or similar references in commit messages
- NEVER include bot co-author lines in commits
- Write commit messages as if a human developer wrote them
- Focus on what changed and why, not how it was created

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

# AGENTS.md – How to Not Sound Like ChatGPT Wrote Your Shit

## Why this matters
Your audience smells AI from a mile away. The moment they do, they stop trusting you and scroll past. You're not saving time—you're erasing what makes you different and blending into the same grey noise as everyone else.

## Dead giveaways (kill these immediately)

### Structure & Rhythm
- Binary opposites when you have nothing to say
  Bad: "Success isn't about hard work, it's about working smart."
  Good: Just say what you mean. No fake contrasts needed.
- Everything in threes
  Bad: "Fast, reliable, and scalable."
  Good: Use two points. Or four. Or one. Mix it up.
- Infomercial questions
  Bad: "The catch?" / "Want the secret?"
  Good: Write like you're talking to a friend at a bar.

### Language
- Corporate zombie verbs
  Bad: highlighting, leveraging, facilitating, optimizing
  Good: show, use, help, improve
- Throat-clearing hedges
  Bad: "It's worth noting that…" / "You might want to consider…"
  Good: Cut the warm-up. Say the thing.
- Thesaurus abuse
  utilize → use
  execute → do
  implement → start
  leverage → use

### Formatting & Style
- Arrow spam → → →
  Use zero or one. Not a fireworks show.
- Emoji confetti 🚀💡🔥
  One per section max. Usually none.
- Em-dash addiction—look—I can't stop—see?
  Use commas and periods like a normal human.

### Robot Phrase Patterns (instant red flags)
- "No fluff. No BS. Just results."
- "Game-changer" / "supercharge" / "this one weird trick"
- "To your success,"
- "If you're serious about …"
- "Enter: the framework"
- "The best part?" / "Ready to 10x?"

All of these scream 2023–2025 ChatGPT. Delete on sight.

### Content Problems
- Symbolism overdose ("This represents a pivotal shift…")
  Just say what happened.
- Fake case studies about "Sarah Chen, a 34-year-old founder from San Francisco"
  Use real stories, real names (with permission), real numbers.
- Universal transformation claims ("This one tweak 10x'd my entire business")
  Be specific or be quiet.

## How to actually write good shit

1. Use AI to think, not to write.
   Brainstorm, outline, poke holes—then close the tab.
2. Write the first draft yourself, in your own voice.
3. Read it out loud. If you cringe, cut it.
4. If a sentence could appear in any other creator's newsletter, delete it.
5. Edit ruthlessly.

## The real cost

You're not paying $20/month for ChatGPT.

You're paying with your voice, your trust, and your differentiation.

People don't leave because the advice is wrong.

They leave because it's forgettable.

## TL;DR

Write like you talk.

Delete anything that sounds like it was generated.

Your voice is the only moat you have left. Don't piss it away.

---

## Git Push Configuration for IWF Infrastructure Repos

**Repository:** git@git.iwf.io:infrastructure/*

**Working SSH Key:** `~/.ssh/syseng/id_rsa-iwf-syseng`

**Push Command:**
```bash
GIT_SSH_COMMAND="ssh -i ~/.ssh/syseng/id_rsa-iwf-syseng -o IdentitiesOnly=yes" git push origin main
```

**Alternative Key:** `~/.ssh/deploy/id_rsa-iwf-deploy` (also works if write access enabled)

**Important:** Deploy keys must have write access enabled in GitLab repository settings:
- Settings → Repository → Deploy Keys → "Write access allowed" checkbox

---

## Current Issue Context
<!-- issue-context:start -->

_No issue context populated yet. Use the Populate AGENTS.override.md button to generate it._

<!-- issue-context:end -->
