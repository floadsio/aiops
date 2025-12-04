Content:
Global Agent Context

Updated: 2025-12-02T15:57:46.768679

Content:
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
3. **Auto-injection**: When you start work on an issue with a plan, the plan is 
automatically included in `AGENTS.override.md`
4. **Resume capability**: Plans allow you to resume work exactly where you left 
off
5. **Collaboration**: Multiple agents or developers can follow the same plan

### Best Practices

- ✅ **Create plans BEFORE starting complex work** - think through the 
implementation first
- ✅ **Update plans as you work** - document decisions and discoveries
- ✅ **Mark phases complete** - track progress through the implementation
- ✅ **Include file paths** - make it easy to find what needs changing
- ✅ **Document decisions** - explain WHY, not just WHAT
- ❌ **Don't create plans for trivial tasks** - simple one-file changes don't 
need plans
- ❌ **Don't let plans go stale** - update or delete them when no longer 
relevant

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

- NEVER include "Claude", "AI", "Generated with", "Co-Authored-By: Claude" or 
similar references in commit messages
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
  - Additional context labels as needed (e.g., `high-priority`, 
`breaking-change`)

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
   aiops issues list --project <project> -o json | grep 
'"external_id":"<number>"' -B 5 | grep '"id"'

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
git merge feature/xyz-description --no-ff -m "Merge: Feature - Description 
(closes #XXX)"
git push origin main

# Step 3: Deploy to production
cd /home/syseng/aiops
sudo git fetch origin main
sudo git reset --hard origin/main

# CRITICAL: Sync dependencies after pulling code updates
sudo su - syseng -c "cd /home/syseng/aiops && /home/syseng/.local/bin/uv pip 
install -r requirements.txt"
# OR use make sync if available
sudo su - syseng -c "cd /home/syseng/aiops && make sync"

sudo systemctl restart aiops

# Step 4: Verify deployment
sudo systemctl status aiops --no-pager
git log --oneline -1
```

**IMPORTANT:** Always run `make sync` or `uv pip install -r requirements.txt` 
after pulling code updates to ensure all dependencies (including new ones like 
`ollama`) are installed. Skipping this step can cause runtime errors due to 
missing libraries.

### 5. Close the Issue

```bash
# After merged and deployed to production
aiops issues comment <internal-id> "✅ Implemented and merged in $(git rev-parse
--short HEAD)"
aiops issues close <internal-id>
```

---

## Pull/Merge Request Creation

**CRITICAL: ALWAYS use `aiops git pr-create` for creating pull requests (GitHub)
or merge requests (GitLab)**

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
- **NEVER use `gh pr create`, `glab mr create`, or direct git push with PR 
creation**
- **ALWAYS use `aiops git pr-create`** to create PRs/MRs
- **ALWAYS use `aiops git pr-merge`** to merge PRs/MRs
- The CLI automatically detects provider (GitHub/GitLab) and creates appropriate
PR/MR
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

**CRITICAL: ALWAYS use `aiops git pr-merge` for merging pull requests (GitHub) 
or merge requests (GitLab)**

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
- **NEVER use `gh pr merge`, `glab mr merge`, or GitHub/GitLab web UI for 
merging**
- **ALWAYS use `aiops git pr-merge`** to merge PRs/MRs
- The CLI automatically detects provider (GitHub/GitLab)
- Merge methods:
  - `merge` (default): Creates a merge commit preserving all commits
  - `squash`: Combines all commits into a single commit
  - `rebase`: Rebases commits onto target branch
- Use `--delete-branch` to automatically clean up the source branch after merge
- Requires integration with "Pull requests: Write" and "Contents: Write" 
permissions

### Commit Message Best Practices
- Reference issue in commits: `"Add validation (refs #123)"`
- Use descriptive commit messages
- Commit frequently with logical changes
- Each commit should be a working state when possible

## Production System Management

**IMPORTANT: AI agents CAN restart production when configuration changes require
it**

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
- ✅ **DO restart production** when configuration changes require it (e.g., 
`.env` updates)
- ✅ **DO use `aiops system restart`** for controlled restarts
- ✅ **DO verify changes** before restarting when possible
- ✅ **DO sync dependencies** after pulling code updates
- ❌ **NEVER modify `/home/syseng/aiops/` directly** - work in personal 
workspaces and merge via PRs
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

**Key Principle:** Configuration changes in production `.env` files are safe to 
apply immediately with restarts. Code changes should always go through workspace
→ PR → merge → production deployment workflow.

---

# AGENTS.md – How to Not Sound Like ChatGPT Wrote Your Shit

## Why this matters
Your audience smells AI from a mile away. The moment they do, they stop trusting
you and scroll past. You're not saving time—you're erasing what makes you 
different and blending into the same grey noise as everyone else.

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
GIT_SSH_COMMAND="ssh -i ~/.ssh/syseng/id_rsa-iwf-syseng -o IdentitiesOnly=yes" 
git push origin main
```

**Alternative Key:** `~/.ssh/deploy/id_rsa-iwf-deploy` (also works if write 
access enabled)

**Important:** Deploy keys must have write access enabled in GitLab repository 
settings:
- Settings → Repository → Deploy Keys → "Write access allowed" checkbox

---

## Creating Jira Issues with aiops CLI

**CRITICAL: Jira projects may have different issue types than the default 
"Task"**

### Issue Creation Command

```bash
aiops issues create --project <project-id-or-name> --integration 
<integration-id> \
  --title "Issue Title" \
  --description "Issue description" \
  --labels "label1,label2"
```

### Common Issue Creation Error

**Error:** `Jira API error: The issue type selected is invalid.`

**Cause:** The Jira project doesn't have the default issue type "Task". Some 
Jira projects use localized issue types (e.g., "Aufgabe" in German Jira 
projects).

### Solution: Configure issue_type in ProjectIntegration

1. **Check available issue types** in the Jira project:

```python
cd /home/syseng/aiops && sudo su - syseng -c "source .venv/bin/activate && 
python3 << 'EOF'
from app import create_app
from app.models import TenantIntegration

app = create_app()
with app.app_context():
    integration = TenantIntegration.query.get(<integration-id>)
    if integration:
        settings = integration.settings or {}
        username = settings.get('username', '')
        
        from jira import JIRA
        client = JIRA(
            server=integration.base_url,
            basic_auth=(username, integration.api_token),
            timeout=30,
        )
        
        # Get project-specific issue types
        meta = client.createmeta(projectKeys='<PROJECT-KEY>', 
expand='projects.issuetypes')
        for project in meta.get('projects', []):
            print(f'Project: {project[\"key\"]}')
            for issuetype in project.get('issuetypes', []):
                print(f'  - {issuetype[\"name\"]} (ID: {issuetype[\"id\"]})')
        
        client.close()
EOF"
```

2. **Configure the correct issue_type** for the project:

```bash
sudo su - syseng -c "cd /home/syseng/aiops && source .venv/bin/activate && 
python3 << 'EOF'
from app import create_app
from app.models import ProjectIntegration, db

app = create_app()
with app.app_context():
    pi = ProjectIntegration.query.filter_by(project_id=<project-id>, 
integration_id=<integration-id>).first()
    if pi:
        pi.config = {'issue_type': 'Aufgabe'}  # Use the correct issue type name
        db.session.commit()
        print(f'Updated config: {pi.config}')
EOF"
```

3. **Try creating the issue again** - it should now work!

### Example: IWF Infrastructure Projects

For IWF infrastructure projects (k8s-infra-stage, k8s-infra) using the IWFCLOUD2
Jira project:

**Available issue types in IWFCLOUD2:**
- Aufgabe (German for "Task") - **use this for general tasks**
- Story
- Bug
- Epic
- Incident
- Service Request
- etc.

**Configuration:**
```python
# Project 8 (k8s-infra-stage) and Project 9 (k8s-infra) both use:
pi.config = {'issue_type': 'Aufgabe'}
```

**Issue creation after config:**
```bash
aiops issues create --project 9 --integration 6 \
  --title "Your Issue Title" \
  --description "Description" \
  --labels "label"
```

### Issue Type Priority

The issue type is resolved in this order:
1. `request.issue_type` (not exposed in CLI currently)
2. `project_integration.config['issue_type']` (set via Python script above)
3. `DEFAULT_ISSUE_TYPE` ("Task" - may not exist in all Jira projects)

### Best Practices

- ✅ **Check issue types** before creating issues in a new Jira project
- ✅ **Configure issue_type** in project_integration.config if default "Task" 
doesn't exist
- ✅ **Use localized names** (e.g., "Aufgabe" for German Jira, "Task" for 
English)
- ❌ **Don't assume** "Task" exists in all Jira projects

---

## Jira Wiki Markup Formatting

**CRITICAL: Jira uses Wiki Markup, NOT Markdown!**

When creating or updating Jira issues and comments via `aiops issues create`, 
`aiops issues update`, or `aiops issues comment`, you MUST use Jira Wiki Markup 
syntax, not Markdown.

### Text Formatting

| Style | Jira Markup | Example | Rendered |
|-------|-------------|---------|----------|
| **Bold** | `*text*` | `*bold text*` | **bold text** |
| _Italic_ | `_text_` | `_italic text_` | _italic text_ |
| Monospace | `{{text}}` | `{{code}}` | `code` |
| Strikethrough | `-text-` | `-deleted-` | ~~deleted~~ |
| Underline | `+text+` | `+underlined+` | <u>underlined</u> |
| Superscript | `^text^` | `x^2^` | x² |
| Subscript | `~text~` | `H~2~O` | H₂O |

**DO NOT USE:**
- ❌ `**bold**` (Markdown) → Use `*bold*`
- ❌ `` `code` `` (Markdown) → Use `{{code}}`

### Headings

| Level | Jira Markup | Example |
|-------|-------------|---------|
| H1 | `h1. ` | `h1. Main Heading` |
| H2 | `h2. ` | `h2. Section` |
| H3 | `h3. ` | `h3. Subsection` |
| H4 | `h4. ` | `h4. Minor Heading` |
| H5 | `h5. ` | `h5. Small Heading` |
| H6 | `h6. ` | `h6. Tiny Heading` |

**DO NOT USE:**
- ❌ `# Heading` (Markdown) → Use `h1. Heading`
- ❌ `## Heading` (Markdown) → Use `h2. Heading`
- ❌ `### Heading` (Markdown) → Use `h3. Heading`

### Lists

**Unordered Lists (Bullets):**
```
* Level 1
** Level 2
*** Level 3
* Back to Level 1
```

**Ordered Lists (Numbered):**
```
# First item
# Second item
## Nested item
## Another nested
# Third item
```

**DO NOT USE:**
- ❌ `- bullet` (Markdown) → Use `* bullet`
- ❌ `1. item` (Markdown) → Use `# item`

### Code Blocks

**Simple code block:**
```
{code}
code here
{code}
```

**Code block with language syntax:**
```
{code:python}
def hello():
    print("Hello, world!")
{code}

{code:bash}
kubectl get pods
{code}

{code:yaml}
apiVersion: v1
kind: Pod
{code}
```

**DO NOT USE:**
- ❌ ` ```python ` (Markdown) → Use `{code:python}`
- ❌ ` ``` ` (Markdown) → Use `{code}`

### Links

**External links:**
```
[Link text|http://example.com]
  (auto-linked)
```

**User mentions:**
```
[~accountid:557058:49affac3-cdf1-4248-8e0b-1cffc2e4360e]
[~accountid:557058:5010d224-86bf-47de-bff7-d7f9406b362b]
```

**Issue links:**
```
IWFCLOUD2-44
IWFCLOUD2-43
```

**DO NOT USE:**
- ❌ `(url)` (Markdown) → Use ``

### Tables

```
|| Heading 1 || Heading 2 || Heading 3 ||
| Cell A1 | Cell A2 | Cell A3 |
| Cell B1 | Cell B2 | Cell B3 |
```

**DO NOT USE:**
- ❌ `| Header |` (Markdown) → Use `|| Header ||`
- ❌ `|---|` separator → Not needed in Jira

### Quotes and Panels

**Quote:**
```
{quote}
This is a quoted text.
Multiple lines work fine.
{quote}
```

**Info Panel:**
```
{panel:title=Information|borderStyle=dashed|borderColor=#ccc|titleBGColor=#F7D6C
1|bgColor=#FFFFCE}
Important information here
{panel}
```

**DO NOT USE:**
- ❌ `> quote` (Markdown) → Use `{quote}quote{quote}`

### Line Breaks and Spacing

- **Single line break:** Just press Enter once
- **Paragraph break:** Press Enter twice (blank line)
- **Force line break:** Use `\\` at end of line

### Horizontal Rule

```
----
```

### Special Characters

To display Jira markup literally without rendering:
```
\{noformat}
*This will not be bold*
{{This will not be monospace}}
\{noformat}
```

### Complete Example: Issue Description

**BAD (Markdown):**
```markdown
## Overview
This is a **critical** bug fix.

### Steps to reproduce:
1. Navigate to `/dashboard`
2. Click on `Settings`
3. See error

### Code Example:
```python
def broken():
    return None
```

### Expected Result:
- Should work
- No errors
```

**GOOD (Jira Wiki Markup):**
```
h2. Overview
This is a *critical* bug fix.

h3. Steps to reproduce:
# Navigate to {{/dashboard}}
# Click on {{Settings}}
# See error

h3. Code Example:
{code:python}
def broken():
    return None
{code}

h3. Expected Result:
* Should work
* No errors
```

### CLI Examples

**Creating issue with Jira formatting:**
```bash
aiops issues create --project 9 --integration 6 \
  --title "Bug: Login fails on mobile" \
  --description "h2. Problem
The login form does not work on mobile devices.

h3. Steps to reproduce:
# Open app on mobile
# Enter credentials
# Click {{Login}}

h3. Expected:
* User logs in successfully

h3. Actual:
* Error: {{Authentication failed}}

h3. Environment:
* Device: iPhone 13
* OS: iOS 17.2
* App Version: 2.1.0" \
  --labels "bug,mobile"
```

**Adding comment with code block:**
```bash
aiops issues comment 763 "h3. Implementation Update

Fixed the authentication issue by updating the token validation.

h4. Changes:
{code:python}
def validate_token(token):
    # Added expiry check
    if token.is_expired():
        raise TokenExpiredError()
    return token.verify()
{code}

h4. Testing:
* Unit tests passing
* Integration tests passing
* Deployed to staging

Ready for review [~accountid:557058:5010d224-86bf-47de-bff7-d7f9406b362b]"
```

**Updating issue description:**
```bash
aiops issues update 763 --description "h2. Updated Requirements

The requirements have changed:

h3. New Scope:
* Support OAuth2
* Add MFA
* Implement session timeout

h3. Implementation Plan:
# Update authentication service
# Add OAuth2 provider integration
# Implement MFA flow
# Add session management

h3. Acceptance Criteria:
* Users can log in with OAuth2
* MFA is enforced for admin users
* Sessions expire after 30 minutes

h3. References:
See IWFCLOUD2-44 for related work."
```

### Best Practices

1. ✅ **Always use Jira Wiki Markup** for issues and comments
2. ✅ **Test formatting** in Jira UI first if unsure
3. ✅ **Use headings** (h2, h3) to structure content
4. ✅ **Use code blocks** `{code}` for command output, YAML, code
5. ✅ **Use inline code** `{{text}}` for file paths, commands, values
6. ✅ **Use bullets** `*` for lists (not `-`)
7. ✅ **Mention users** with `[~accountid:...]` format
8. ✅ **Reference issues** with just the key (IWFCLOUD2-44)

### Common Mistakes to Avoid

1. ❌ **Using Markdown syntax** (`## heading`, `**bold**`, `` `code` ``)
2. ❌ **Triple backticks** for code blocks (use `{code}`)
3. ❌ **Dash for bullets** `-` (use `*`)
4. ❌ **Number for ordered lists** `1.` (use `#`)
5. ❌ **Markdown links** `(url)` (use ``)
6. ❌ **Checkbox syntax** `- [ ]` (not supported, use plain bullets)

### Quick Reference

```
Text:       *bold*  _italic_  {{mono}}  -strike-  +underline+
Headings:   h1. h2. h3. h4. h5. h6.
Lists:      * bullet   # numbered
Code:       {code} ... {code}  or  {code:lang} ... {code}
Links:        or  [~accountid:xxx]
Quotes:     {quote} ... {quote}
Panels:     {panel} ... {panel}
Tables:     || Header ||  and  | Cell |
```

### Jira Documentation

Official reference: 
https://jira.atlassian.com/secure/WikiRendererHelpAction.jspa?section=all
# Global Agents Context

## Jira Users and Account IDs Lookup Table

**Quick reference for tagging users in Jira comments using Jira Wiki Markup format: `[~accountid:ACCOUNT_ID]`**

| Name | Account ID | Full Mention Format |
|------|-----------|-------------------|
| Ivo Marino | `557058:49affac3-cdf1-4248-8e0b-1cffc2e4360e` | `[~accountid:557058:49affac3-cdf1-4248-8e0b-1cffc2e4360e]` |
| Jens Hassler | `557058:5010d224-86bf-47de-bff7-d7f9406b362b` | `[~accountid:557058:5010d224-86bf-47de-bff7-d7f9406b362b]` |

**Note:** Add new users to this table as discovered. Org ID is always `557058` for IWF Atlassian instance.

### How to Find User Account IDs

Jira Cloud enforces GDPR strict mode which prevents direct user search via API. To find account IDs:

1. **From Atlassian People Directory (most reliable):**
   - URL: `https://home.atlassian.com/o/3a2b7jk8-35j7-1264-6jc3-a1jacj23033k/people`
   - Search for the user
   - The profile URL contains the account ID: `https://home.atlassian.com/o/{orgId}/people/{accountId}`
   - Extract the account ID (format: `557058:xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`)

2. **From Jira UI (easiest):**
   - Go to any Jira issue and start typing `@` in a comment
   - Type the user's name
   - Jira will show their account ID in the format `[~accountid:557058:xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx]`

3. **From Existing Comments:**
   - Check any issue where the user has been mentioned
   - View the raw comment to find their account ID in format: `[~accountid:557058:xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx]`

## ArgoCD CLI Setup

### Quick Start
```bash
# Get ArgoCD password from cluster
ARGOCD_PASSWORD=$(kubectl get secret argocd-initial-admin-secret -n argocd -o jsonpath='{.data.password}' | base64 -d)

# Login
argocd login argocd.web-solutions.io --insecure --grpc-web --username admin --password "$ARGOCD_PASSWORD"

# List applications
argocd app list --insecure --grpc-web
```

### Common Commands
```bash
# Sync application
argocd app sync <APP_NAME> --insecure --grpc-web

# Wait for sync
argocd app wait <APP_NAME> --sync --insecure --grpc-web

# Get app status
argocd app get <APP_NAME> --insecure --grpc-web

# Hard refresh (bypass cache)
argocd app sync <APP_NAME> --hard-refresh --insecure --grpc-web
```

### Environment Variables for Convenience
```bash
export ARGOCD_INSECURE=true
export ARGOCD_SERVER=argocd.web-solutions.io

# Now you can use shorter commands
argocd app list
argocd app sync cleanup-job
```

For full documentation on ArgoCD CLI, see the AGENTS.override.md file in the k8s-infra repository.

---

## Current Issue Context
<!-- issue-context:start -->

_No issue context populated yet. Use the Populate AGENTS.override.md button to generate it._

<!-- issue-context:end -->
