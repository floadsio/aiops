Global Agent Context

Updated: 2026-01-15T21:08:52.590915

Content:
Global Agent Context

Updated: 2026-01-15T16:25:00.824159

Content:
Global Agent Context

Updated: 2026-01-15T16:23:07.533557

Content:
Global Agent Context

Updated: 2026-01-15T16:19:25.125292

Content:
Global Agent Context

Updated: 2026-01-15T16:15:44.708949

Content:
Global Agent Context

Updated: 2026-01-15T16:13:26.058160

Content:
Global Agent Context

Updated: 2026-01-15T16:13:04.495972

Content:
Global Agent Context

Updated: 2025-12-21T00:48:37.883032

Content:
Global Agent Context

Updated: 2025-12-18T23:29:47.985010

Content:
Global Agent Context

Updated: 2025-12-14T21:40:43.277155

Content:
Global Agent Context

Updated: 2025-12-14T18:50:11.443717

Content:
Global Agent Context

Updated: 2025-12-12T12:14:45.124096

Content:
Global Agent Context

Updated: 2025-12-12T07:41:33.205268

Content:
Global Agent Context

Updated: 2025-12-12T07:37:47.902136

Content:
Global Agent Context

Updated: 2025-12-12T06:04:50.557497

Content:
Global Agent Context

Updated: 2025-12-12T06:00:18.795160

Content:
Global Agent Context

Updated: 2025-12-12T05:57:17.897981

Content:
Global Agent Context

Updated: 2025-12-10T16:59:11.126242

Content:


---

## Repository Management & Issue Tracking Guidelines

### Understanding Repository Structure

This project involves **multiple independent repositories** with different 
purposes:

**Internal Development Repositories (Floads):**
- `/home/michael/workspace/floads/aiops/` - AIOps application and tools 
(internal)
- `/home/michael/workspace/floads/syseng/` - Systems engineering infrastructure 
(internal)

**Client Repositories:**
- `/home/michael/workspace/lnz/k8s-infra/` - LerNetz infrastructure (CLIENT REPO
- read-only for documentation)
- `https://gitlab.com/floads/syseng/customer-lnz/` - Internal Floads project 
tracking for LerNetz issues

### Critical Rule: Issue Location vs Repository Type

**Each issue exists in EXACTLY ONE correct location. Verify before updating.**

| Issue Type | Location | Action |
|-----------|----------|--------|
| Internal project tracking | `floads/syseng/customer-lnz` (GitLab) | ✅ Update 
with findings |
| Client-specific setup | `lnz/k8s-infra` (local client repo) | ❌ DO NOT UPDATE
|
| General infrastructure docs | aiops global agents file | ✅ Update for future 
reference |
| Development work | floads/aiops or floads/syseng | ✅ Update appropriately |

### Issue Relationships Example: Issue #705 (Velero Backup Setup)

**Correct Flow:**
1. **Internal tracking issue:** 
https://gitlab.com/floads/syseng/customer-lnz/-/issues/1
   - External ID: #705 (references GitLab issue #705)
   - Status: Phase 2 complete, Phase 3 ready
   - Updates: Post findings, track progress here ✅

2. **Client repo documentation:** 
`/home/michael/workspace/lnz/k8s-infra/ISSUE_705.agents.md`
   - Purpose: Local documentation for client context
   - Status: DO NOT UPDATE - client owns this file
   - Action: Read-only reference only ❌

3. **Internal documentation:** aiops global agents file
   - Purpose: How to access clusters, remember procedures, store credentials
   - Status: Actively maintain this for future sessions
   - Action: Update with new findings and methods ✅

### How to Verify the Correct Repository

**When an issue is mentioned:**

1. **Check the URL explicitly provided:**
   - If user gives: `https://gitlab.com/floads/syseng/customer-lnz/-/issues/1`
   - This IS the correct location ✅
   - Updates should go HERE, nowhere else

2. **Check for agent context files in client repos:**
   - If you see: `/home/michael/workspace/lnz/k8s-infra/ISSUE_*.agents.md`
   - This is documentation FOR the issue, not the issue itself
   - DO NOT EDIT these files - they are in the client repository

3. **When uncertain:**
   - The URL provided by the user is ALWAYS the authoritative source
   - Internal floads URLs in GitLab = correct location for updates
   - Local client repo files = read-only reference only

### Decision Tree for Issue Updates

```
User mentions an issue
    ↓
Is a GitLab URL explicitly provided?
    ├─ YES: Use ONLY that URL location ✅
    │   └─ Is it floads/syseng/customer-*? → Update there ✅
    │   └─ Is it under /home/michael/workspace/lnz/? → DO NOT TOUCH ❌
    │
    └─ NO: Ask for clarification on which repo/issue
        └─ Never assume or search across multiple repos
        └─ Always verify with user first
```

### Real Example: What Went Right & What Went Wrong

**Today's Session (Issue #705 - Velero Backup for LerNetz Begasoft):**

❌ **Mistake:** Initially attempted to update issues in `lnz/k8s-infra` 
repository
- User had to intervene and explicitly state: "Update ONLY 
https://gitlab.com/floads/syseng/customer-lnz/-/issues/1"
- This was wrong because lnz/k8s-infra is a CLIENT repository

✅ **Corrected:** Updated only the internal Floads repository
- Posted findings to: https://gitlab.com/floads/syseng/customer-lnz/-/issues/1
- Added procedure documentation to: aiops global agents file
- No changes to: `/home/michael/workspace/lnz/k8s-infra/` (client repo)

### Why This Matters

1. **Client Privacy:** Client repositories should not be cluttered with internal
documentation or unnecessary commits
2. **Clear Audit Trail:** Client sees only relevant project updates, not AI tool
references
3. **Project Management:** Internal floads repositories track work and findings
4. **Credentials & Secrets:** Never commit credentials - always use aiops global
agents file instead
5. **No Force-Pushes:** Wrong commits in client repos require force-pushes 
(visible and suspicious to client)

### Checklist Before Updating Any Issue

- [ ] Did user explicitly provide a GitLab URL? If yes, use ONLY that URL
- [ ] Is the repository under `/home/michael/workspace/lnz/`? If yes, DO NOT 
UPDATE
- [ ] Is the URL `floads/syseng/customer-*`? If yes, this is correct for 
internal issue tracking
- [ ] Would this commit be visible/relevant to the client? If no, use aiops 
global agents instead
- [ ] Does this involve credentials or sensitive data? If yes, use aiops global 
agents ONLY
- [ ] Am I about to force-push or modify client repo history? If yes, STOP and 
ask for clarification
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

## K3s Node Access (Flow Swiss - IWF Prod/Stage)

### SSH Access Details

**SSH User:** `core`
**SSH Key:** `~/.ssh/flow/id_rsa-iwf-prod-core`
**Key Location:** `/home/ivo/.ssh/flow/id_rsa-iwf-prod-core`

### SSH Connection Examples

```bash
# Connect to IWF Prod node
ssh -i ~/.ssh/flow/id_rsa-iwf-prod-core core@<node-ip>

# Example: Connect to worker-682f79e9a2a88 (172.33.16.173)
ssh -i ~/.ssh/flow/id_rsa-iwf-prod-core core@172.33.16.173
```

### K3s Service Management

**K3s Service (docker-compose):**
- Service name: `k3s` (runs via docker-compose, not k3s-agent)
- Restart: `sudo systemctl restart k3s`
- Status: `sudo systemctl status k3s`
- Config: `/opt/docker-compose.yaml`
- Process: `/opt/docker-compose -f /opt/docker-compose.yaml up`

### Common Node Tasks

```bash
# Check K3s process
ps aux | grep -i k3s | grep -v grep

# Restart K3s service (correct)
sudo systemctl restart k3s

# View K3s logs
sudo journalctl -u k3s --no-pager

# Check node info
uname -n
lsb_release -d
```

### Node Environment
- **OS:** Flatcar Linux (K3s v1.30.0+k3s1)
- **Container Runtime:** containerd://1.7.15-k3s1
- **Kernel:** 6.6.48-flatcar

---

## K3s Mount Propagation Fix (IWFCLOUD2-45)

### Problem
Pods using HostToContainer mount propagation (e.g., node-exporter) failed with:
```
failed to generate spec: path "/" is mounted on "/" but it is not a shared or
slave mount
```

### Root Cause
- K3s runs in docker-compose container with isolated mount namespace
- Container's own root filesystem (overlay FS) didn't have shared propagation
- runc validates source mount propagation and rejects HostToContainer without
shared/slave

### Permanent Fix (Applied & Tested)

**1. Modified `/opt/docker-compose.yaml`:**
```yaml
volumes:
  - /:/host-root:ro,rshared
  # ... other volumes ...
```

**2. Created Systemd Auto-Fix:**
Path: `/etc/systemd/system/k3s.service.d/mount-propagation.conf`
```ini
[Service]
ExecStartPost=/bin/bash -c 'sleep 2 && docker exec k3s mount --make-shared / ||
true'
```

### How It Works
- On K3s startup, systemd runs: `docker exec k3s mount --make-shared /`
- Remounts K3s container's root filesystem with shared propagation
- Persists through K3s restarts (not through reboots, so systemd triggers it)

### Verification
```bash
# Inside K3s container, verify shared mount:
docker exec k3s cat /proc/self/mountinfo | grep ' / ' | head -1
# Should show: ... shared:N ...
```

### Status
✅ Fixed and verified persistent across node reboot
✅ Implemented on worker-682f79e9a2a88
✅ All 6 node-exporter pods now running
✅ 100% DiskPressure monitoring coverage

### If Issue Recurs
```bash
# Quick fix (temporary until next K3s restart):
ssh -i ~/.ssh/flow/id_rsa-iwf-prod-core core@<node-ip>
sudo docker exec k3s mount --make-shared /

# Verify pods recover:
kubectl -n monitoring get pods -l
app.kubernetes.io/name=prometheus-node-exporter
```

---

## About This Document (AGC)

**Terminology Note:** "Global Agents Context" can be aliased as **AGC** for
faster writing.

Examples:
- "Add this info to AGC" = "Add this info to Global Agents Context"
- "Update AGC with..." = "Update Global Agents Context with..."
- "Check AGC for..." = "Check Global Agents Context for..."

This is the global agents context that appears in all AI agent sessions. Use
`aiops agents global get` to view or `aiops agents global set -f <file>` to
update.

**CRITICAL: Always APPEND to AGC, NEVER override existing context**

When updating the global agents context:
- ✅ **DO**: Append new sections with `---` separator
- ✅ **DO**: Add new information at the end
- ✅ **DO**: Preserve all existing content
- ❌ **DON'T**: Replace or delete existing sections
- ❌ **DON'T**: Override the entire file
- ❌ **DON'T**: Remove historical information

---

## aiops CLI Issue Management - Tenant Filtering

**New Feature:** The `aiops issues list` command now supports filtering by
tenant.

### Usage

```bash
# Filter by tenant slug (recommended)
aiops issues list --tenant floads

# Filter by tenant ID
aiops issues list --tenant 4

# Combine with other filters
aiops issues list --tenant floads --status open
aiops issues list --tenant floads --project aiops --status open
aiops issues list --tenant 4 --assignee "Ivo" --limit 10

# Output formats
aiops issues list --tenant floads --output json
aiops issues list --tenant floads --output yaml
```

### Important Notes

- **Tenant resolution**: Supports both numeric IDs and slugs (case-insensitive)
- **Error handling**: Invalid tenant names return clear error: "Tenant 'xyz' not
found"
- **Combined filters**: Works seamlessly with `--status`, `--project`,
`--assignee`, `--limit`
- **Use cases**:
  - List all issues for a specific customer/tenant
  - Filter multi-tenant projects by tenant
  - Useful in multi-tenant environments

### Available Tenants

To see available tenants:
```bash
aiops tenants list
```
---

## MDO Tenant Configuration

**Tenant Created:** 2025-12-05
**Tenant ID:** 8
**Tenant Slug:** `mdo`
**Description:** MDO Customer

### GitLab Project Integration

**Project:** customer-mdo
**Project ID:** 11
**Repository:** `https://gitlab.com/floads/syseng/customer-mdo.git`
**GitLab URL:** https://gitlab.com/floads/syseng/customer-mdo
**Default Branch:** main
**Local Path:** `instance/repos/customer-mdo`

### Integration Details

**Integration Type:** GitLab (MDO tenant integration)
**Integration ID:** 8 (gitlab-mdo)
**Project Integration ID:** 19
**External Identifier:** `floads/syseng/customer-mdo`

**Important:** The customer-mdo project uses the shared `gitlab-floads`
integration (ID: 4) from the floads tenant. This is the same pattern used for:
- `customer-dcx` (DCX tenant)
- `customer-lnz` (LNZ tenant)
- All projects under `floads/syseng/*` namespace

### Issue Management Commands

```bash
# Sync issues from GitLab
aiops issues sync --project customer-mdo

# List MDO issues
aiops issues list --tenant mdo

# View specific issue
aiops issues get <issue-id>

# Add comment to issue
aiops issues comment <issue-id> "Your comment"

# Close issue
aiops issues close <issue-id>

# Create new issue (IMPORTANT: use integration ID 4)
aiops issues create --project customer-mdo --integration 8 \
  --title "Issue title" \
  --description "Issue description"
```

### Architecture Notes

**Tenant vs Integration Relationship:**
- The `customer-mdo` project belongs to the **MDO tenant** (ID: 8) for
organizational purposes
- However, it uses the **floads GitLab integration** (ID: 4) for API access
- This is because all `floads/syseng/customer-*` projects are managed under the
floads GitLab organization
- When creating issues via CLI, use `--integration 8` (floads) even though the
project is in MDO tenant

**Database Structure:**
```
tenants (id=8, name=mdo)
  └─ projects (id=11, name=customer-mdo, tenant_id=8)
       └─ project_integrations (id=19, project_id=11, integration_id=4,
external_identifier='floads/syseng/customer-mdo')
            └─ external_issues (project_integration_id=19, ...)

tenant_integrations (id=4, tenant_id=4, name=gitlab-floads)
```

### Verification Commands

```bash
# Verify tenant
aiops tenants get mdo

# Verify project
aiops projects list --tenant mdo

# Verify issues synced
aiops issues list --tenant mdo

# Check project integration in database
sqlite3 instance/app.db "SELECT pi.id, pi.project_id, p.name, pi.integration_id,
pi.external_identifier
FROM project_integrations pi
JOIN projects p ON p.id = pi.project_id
WHERE p.name = 'customer-mdo'"
```

### Web UI Access

- **Projects Page:** http://dev.floads:8060/admin/projects (filter by MDO)
- **Issues Page:** http://dev.floads:8060/admin/issues (filter by MDO)
- **Project Detail:** http://dev.floads:8060/projects/11
- **Integrations:** http://dev.floads:8060/admin/integrations

### Issue Sync Status

Initial sync completed with 2 existing issues imported:
- Issue #1: "add Redis" (closed)
- Issue #2: " k8s ssh tunnel" (closed)

All future issues created in GitLab will be automatically synced when running
`aiops issues sync --project customer-mdo`.

---

## Semaphore Automation Integration

**Overview:** aiops integrates with Semaphore UI for running Ansible playbooks
and automation tasks. Semaphore is configured per-tenant (each tenant has one
Semaphore instance), and aiops projects can be linked to Semaphore projects.

### Architecture

- **Per-tenant integration:** Each tenant can have one Semaphore integration
(provider="semaphore" in TenantIntegration)
- **Per-project mapping:** Each aiops project can be linked to a Semaphore
project via `Project.semaphore_project_id`
- **Authentication:** Bearer token authentication via Semaphore API

### CLI Commands

```bash
# List available Semaphore projects
aiops semaphore projects

# List templates for an aiops project
aiops semaphore templates <project>

# Run a template
aiops semaphore run <project> <template_id>

# Run with variables
aiops semaphore run <project> <template_id> --var host=server1 --var env=prod

# Run with host limit (override template default)
aiops semaphore run <project> <template_id> --limit "web1,web2"

# Run with tags (override template default)
aiops semaphore run <project> <template_id> --tags "dns,unbound"

# Run with limit and tags combined
aiops semaphore run <project> <template_id> --limit webservers --tags dns 
--follow

# Run and wait for completion
aiops semaphore run <project> <template_id> --wait

# Check task status
aiops semaphore status <project> <task_id>

# Get task logs
aiops semaphore logs <project> <task_id>

# List recent tasks
aiops semaphore tasks <project>
aiops semaphore tasks <project> --limit 20
```

### Common Workflows

```bash
# Run ping playbook on aiops project
aiops semaphore templates aiops
aiops semaphore run aiops 1 --wait

# Run playbook with variables and monitor
aiops semaphore run aiops 8 --var target=webservers --wait

# Run generic template with specific hosts and tags
aiops semaphore run aiops 15 --limit "backup-03.floads" --tags "users" --follow

# Check what's running
aiops semaphore tasks aiops --limit 5
```

### Web UI Access

- **Project Semaphore Page:** `/projects/<id>/semaphore` - View templates,
trigger tasks, see recent runs
- **Task Detail:** `/projects/<id>/semaphore/task/<task_id>` - View task status
and logs
- **Admin Projects:** Configure `semaphore_project_id` mapping
- **Admin Integrations:** Create Semaphore integrations (provider type
"semaphore")

### REST API Endpoints

```bash
# List Semaphore projects for tenant
GET /api/v1/semaphore/projects

# Test integration connectivity
GET /api/v1/semaphore/test

# List templates for project
GET /api/v1/projects/<id>/semaphore/templates

# Run template
POST /api/v1/projects/<id>/semaphore/run
Body: {"template_id": 1, "variables": {"key": "value"}, "limit": "host1,host2", 
"tags": "tag1,tag2"}

# List tasks
GET /api/v1/projects/<id>/semaphore/tasks

# Get task status
GET /api/v1/projects/<id>/semaphore/tasks/<task_id>

# Get task logs
GET /api/v1/projects/<id>/semaphore/tasks/<task_id>/logs
```

### Current Configuration (floads tenant)

- **Semaphore Host:** `http://10.10.99.16:3000`
- **Integration ID:** 9
- **Semaphore Projects:** floads (ID 1), dcx (ID 2), iwf (ID 3)
- **Linked aiops Projects:**
  - aiops (project ID 6) → Semaphore project ID 1 (floads)
  - flamelet-floads (project ID 4) → Semaphore project ID 1 (floads)

### Adding Semaphore to New Projects

1. **Via Web UI:** Admin → Projects → Edit project → Select Semaphore Project
from dropdown
2. **Via Database:**
   ```python
   project = Project.query.filter_by(name='my-project').first()
   project.semaphore_project_id = 1  # Semaphore project ID
   db.session.commit()
   ```

### Creating New Semaphore Integrations

1. **Via Web UI:** Admin → Integrations → Add Integration
   - Provider: semaphore
   - Name: descriptive name
   - Base URL: `http://semaphore-host:3000`
   - API Token: Semaphore API token

2. **Via Database:**
   ```python
   integration = TenantIntegration(
       tenant_id=4,
       name="semaphore-floads",
       provider="semaphore",
       base_url="http://10.10.99.16:3000",
       api_token="your-token-here",
       enabled=True
   )
   db.session.add(integration)
   db.session.commit()
   ```

---

## Semaphore Template Management via CLI

Templates can be created, updated, and deleted via the aiops CLI. Templates
require references to existing Semaphore resources (inventories, repositories,
environments).

### List Dependencies First

Before creating templates, list available resources to get their IDs:

```bash
# List inventories (get inventory_id)
aiops semaphore inventories <project>

# List repositories (get repository_id)
aiops semaphore repositories <project>

# List environments (get environment_id)
aiops semaphore environments <project>

# List SSH keys (informational)
aiops semaphore keys <project>
```

### Template CRUD Commands

```bash
# Get template details
aiops semaphore template get <project> <template_id>

# Create new template
aiops semaphore template create <project> \
  --name "Template Name" \
  --playbook "ansible/playbook.yml" \
  --inventory 1 \
  --repository 1 \
  --environment 1 \
  [--app ansible|terraform|tofu|bash|powershell] \
  [--description "Description"] \
  [--limit "host1,host2"]        # Ansible host limit pattern \
  [--tags "tag1,tag2"]           # Ansible tags to run \
  [--skip-tags "tag3,tag4"]      # Ansible tags to skip \
  [--branch "main"]              # Git branch to use \
  [--allow-override-args]        # Allow arg override per task \
  [--suppress-alerts]            # Disable success notifications \
  [--autorun]                    # Enable automatic execution

# Update existing template
aiops semaphore template update <project> <template_id> \
  [--name "New Name"] \
  [--playbook "new/path.yml"] \
  [--inventory 2] \
  [--limit "webservers"]         # Update host limit \
  [--tags "newtag1,newtag2"]     # Update tags \
  [--skip-tags "skiptag"]        # Update skip tags \
  [--branch "develop"]           # Change branch \
  [--allow-override-args/--no-allow-override-args]

# Delete template
aiops semaphore template delete <project> <template_id> --yes
```

### Ansible Host Limits

The `--limit` option restricts playbook execution to specific hosts:

```bash
# Single host
aiops semaphore template create aiops --name "Deploy" --playbook "deploy.yml" \
  --inventory 1 --repository 1 --environment 1 --limit "webserver1"

# Multiple hosts (comma-separated)
aiops semaphore template create aiops --name "Deploy" --playbook "deploy.yml" \
  --inventory 1 --repository 1 --environment 1 --limit "web1,web2,db1"

# Host group pattern
aiops semaphore template create aiops --name "Deploy" --playbook "deploy.yml" \
  --inventory 1 --repository 1 --environment 1 --limit "webservers"
```

**Note:** Limits are stored in Semaphore's `task_params.limit` as an array. The
template response includes `task_params` showing the configured limit.

### Ansible Tags

The `--tags` and `--skip-tags` options control which tasks run:

```bash
# Run only specific tags
aiops semaphore template create aiops --name "DNS Config" \
  --playbook "ansible/configure.yml" \
  --inventory 1 --repository 1 --environment 1 \
  --tags "dns,unbound"

# Skip specific tags
aiops semaphore template create aiops --name "Full Deploy" \
  --playbook "ansible/deploy.yml" \
  --inventory 1 --repository 1 --environment 1 \
  --skip-tags "slow,backup"

# Combine tags and limit
aiops semaphore template create aiops --name "DNS on Webservers" \
  --playbook "ansible/configure.yml" \
  --inventory 1 --repository 1 --environment 1 \
  --limit "webservers" \
  --tags "dns,unbound"
```

**Note:** Tags are stored in Semaphore's `task_params.tags` as an array. The
template response includes `task_params` showing configured tags:
```json
{"task_params": {"tags": ["dns", "unbound"], "allow_override_tags": true}}
```

### Example: Create and Run a New Template

```bash
# 1. Check what resources are available
aiops semaphore inventories aiops
aiops semaphore repositories aiops
aiops semaphore environments aiops

# 2. Create template with host limit and tags
aiops semaphore template create aiops \
  --name "Deploy DNS to Webservers" \
  --playbook "ansible/deploy.yml" \
  --inventory 1 \
  --repository 1 \
  --environment 1 \
  --limit "webservers" \
  --tags "dns,unbound" \
  --branch "main"

# Output shows task_params with limit and tags:
# {"task_params": {"limit": ["webservers"], "tags": ["dns", "unbound"], ...}}

# 3. Run the template with real-time logs
aiops semaphore run aiops 21 --follow

# 4. Check task status
aiops semaphore tasks aiops
```

### REST API Endpoints

```bash
# List dependencies
GET /api/v1/projects/{id}/semaphore/inventories
GET /api/v1/projects/{id}/semaphore/environments
GET /api/v1/projects/{id}/semaphore/repositories
GET /api/v1/projects/{id}/semaphore/keys
---

## Cluster Access: lernetz-test-begasoft-k8s

**Cluster Name:** lernetz-test-begasoft-k8s
**Endpoint:** https://193.5.124.83:6443
**Kubernetes Version:** v1.33.6
**Nodes:** 1 control plane + 8 worker nodes (all Ready)

### Authentication Method: Keycloak OIDC

The cluster uses Keycloak OIDC for authentication at 
`https://auth.sso.paas.begasoft.ch/realms/b82ud9`

### Access Steps

1. **Get OIDC Token** (using password grant type):
```bash
# Option A: Direct token retrieval
kubectl-oidc-login get-token \
  --oidc-issuer-url='https://auth.sso.paas.begasoft.ch/realms/b82ud9' \
  --oidc-client-id='kubernetes' \
  --grant-type='password' \
  --username='[YOUR_USERNAME]' \
  --password='[YOUR_PASSWORD]' 2>&1 | jq -r '.status.token' > /tmp/token.txt

# Option B: Store token in environment variable
export KUBE_TOKEN=$(kubectl-oidc-login get-token \
  --oidc-issuer-url='https://auth.sso.paas.begasoft.ch/realms/b82ud9' \
  --oidc-client-id='kubernetes' \
  --grant-type='password' \
  --username='[YOUR_USERNAME]' \
  --password='[YOUR_PASSWORD]' 2>&1 | jq -r '.status.token')
```

2. **Use Token with kubectl**:
```bash
# Access cluster with token
kubectl --token="$(cat /tmp/token.txt)" --insecure-skip-tls-verify get nodes

# Or with environment variable
kubectl --token="$KUBE_TOKEN" --insecure-skip-tls-verify get nodes
```

### Authentication Details
- **OIDC Issuer:** https://auth.sso.paas.begasoft.ch/realms/b82ud9
- **Client ID:** kubernetes
- **Grant Type:** password (resource owner password credentials)
- **Credentials:** Use your personal SSO username and password

### Quick Reference Commands

```bash
# List nodes
kubectl --token="$(cat /tmp/token.txt)" --insecure-skip-tls-verify get nodes

# Get cluster info
kubectl --token="$(cat /tmp/token.txt)" --insecure-skip-tls-verify cluster-info

# List all namespaces
kubectl --token="$(cat /tmp/token.txt)" --insecure-skip-tls-verify get ns

# Current context
kubectl config current-context  # Returns: lernetz-test-begasoft-k8s
```

### Important Notes
- TLS verification is disabled (`--insecure-skip-tls-verify`) - acceptable for 
test clusters
- Token expiration: 300 seconds (5 minutes)
- Refresh token: 1800 seconds (30 minutes)
- The kubectl-oidc-login plugin must be installed 
(`~/.local/bin/kubectl-oidc-login`)
- Each user must use their own SSO credentials

---

## Repository Boundaries & Client Notifications

**CRITICAL: Be aware of client notification systems**

### Important Rules

**DON'T commit to client repositories:**
- ❌ Credentials or sensitive data
- ❌ AI-generated content or AI tool references
- ❌ Temporary documentation or testing files
- ❌ Any changes that require force-pushes to remove

**WHERE to put documentation instead:**
- ✅ Internal documentation → aiops global agents file (this file)
- ✅ Cluster access instructions → aiops global agents file
- ✅ Setup procedures → aiops global agents file
- ✅ Client-facing code/manifests → client repositories only

### Why This Matters

**Client repositories are monitored:**
- Every push triggers notifications to the client
- Force-pushes are visible and suspicious
- AI commits violate client agreements
- Credentials in history cannot be truly removed (still in git objects)

### Real Example: What NOT To Do

❌ **BAD (what happened):**
```
1. Committed documentation with credentials to lernetz k8s-infra repo
2. Client received notification
3. Had to force-push to remove it
4. Client received another notification
5. Visible commit history change (suspicious)
```

✅ **GOOD (what should have happened):**
```
1. Write documentation in aiops global agents file (internal only)
2. No notifications to client
3. No force-pushes needed
4. Clean history, no visible AI activity
```

### Checklist Before Committing to Client Repos

- [ ] Is this code/manifest for actual infrastructure?
- [ ] Does it contain any credentials? (NO - use sealed secrets/environment 
variables instead)
- [ ] Does it reference AI tools? (NO - write human-style commits)
- [ ] Is it documentation? (NO - put in aiops global agents file instead)
- [ ] Will the client see this commit? (If yes, is it appropriate?)

If uncertain, put it in the aiops global agents file instead.


---

## Begasoft Cluster Access: lernetz-test-begasoft-k8s (PYTHON/REQUESTS METHOD)

**Important:** The standard kubectl-oidc-login method requires interactive 
input. For non-interactive automated access, use the Python/requests method 
below.

### Method: Direct OIDC Token via Python (Recommended for Automation)

When kubectl-oidc-login fails with interactive prompts or stdin issues, use 
Python to directly get tokens:

```python
import requests
import subprocess

# 1. Get access token from Keycloak (Python method)
token_url = 
"https://auth.sso.paas.begasoft.ch/realms/b82ud9/protocol/openid-connect/token"
data = {
    "grant_type": "password",
    "client_id": "kubernetes",
    "username": "[YOUR_USERNAME]",
    "password": "[YOUR_PASSWORD]"
}

response = requests.post(token_url, data=data, verify=False)
token_data = response.json()
token = token_data['access_token']

# 2. Use token with kubectl
result = subprocess.run([
    'kubectl',
    '--server=https://193.5.124.83:6443',
    f'--token={token}',
    '--insecure-skip-tls-verify',
    'get', 'cronjobs', '-A'
], capture_output=True, text=True)

print(result.stdout)
```

### Quick Access Commands (Python One-Liner)

```bash
# Get all CronJobs from begasoft-test
python3 << 'EOF'
import requests
import subprocess
token_url = 
"https://auth.sso.paas.begasoft.ch/realms/b82ud9/protocol/openid-connect/token"
response = requests.post(token_url, data={"grant_type": "password", "client_id":
"kubernetes", "username": "[YOUR_USERNAME]", "password": "[YOUR_PASSWORD]"}, 
verify=False)
token = response.json()['access_token']
result = subprocess.run(['kubectl', '--server=https://193.5.124.83:6443', 
f'--token={token}', '--insecure-skip-tls-verify', 'get', 'cronjobs', '-A'], 
capture_output=True, text=True)
print(result.stdout)
EOF

# Get schedules in JSON format for analysis
python3 << 'EOF'
import requests
import subprocess
token_url = 
"https://auth.sso.paas.begasoft.ch/realms/b82ud9/protocol/openid-connect/token"
response = requests.post(token_url, data={"grant_type": "password", "client_id":
"kubernetes", "username": "[YOUR_USERNAME]", "password": "[YOUR_PASSWORD]"}, 
verify=False)
token = response.json()['access_token']
result = subprocess.run(['kubectl', '--server=https://193.5.124.83:6443', 
f'--token={token}', '--insecure-skip-tls-verify', 'get', 'cronjobs', '-A', '-o',
'json'], capture_output=True, text=True)
import json
jobs = json.loads(result.stdout)
for item in jobs['items']:
    print(f"{item['metadata']['namespace']}: {item['metadata']['name']}: 
{item['spec']['schedule']}")
EOF
```

### Key Advantages of Python/Requests Method

1. **No Interactive Input:** Works in automated scripts and CI/CD pipelines
2. **Direct Token Access:** Bypasses kubectl-oidc-login authentication issues
3. **Full Control:** Can parse and process JSON directly in Python
4. **Reliable:** Doesn't depend on kubeconfig setup or environment variables
5. **Scriptable:** Easy to loop through multiple clusters or queries

### Cluster Details

- **Cluster Endpoint:** https://193.5.124.83:6443
- **OIDC Issuer:** https://auth.sso.paas.begasoft.ch/realms/b82ud9
- **Client ID:** kubernetes
- **Grant Type:** password
- **TLS Verification:** Disabled (--insecure-skip-tls-verify)
- **Token Lifespan:** 300 seconds (5 minutes)

### When to Use This Method

- Automated scripts and agents
- CI/CD pipelines
- Analysis tasks requiring multiple queries
- When kubeconfig context setup is not available
- Batch operations on cluster resources

### Related Issues

- **Issue #1 (customer-lnz):** Velero Backup Scheduling Analysis - uses this 
method to access begasoft-test cluster and analyze 107 CronJobs for schedule 
optimization
---

## IWF Infrastructure Deployment (flamelet-iwf)

**Repository:** git@git.iwf.io:infrastructure/flamelet-iwf.git
**Tenant:** iwf
**Semaphore Project ID:** 3
**aiops Project:** flamelet-iwf

### SSH Configuration

**Working SSH Key for Git Operations:**
- Key: `~/.ssh/syseng/id_rsa-iwf-syseng`
- SSH Config: Already configured in `~/.ssh/conf.d/iwf.conf`

```bash
# Git repository access (SSH config entry)
Host git.iwf.io
  User git
  IdentityFile ~/.ssh/syseng/id_rsa-iwf-syseng
  IdentitiesOnly yes
```

### Repository Structure

```
flamelet-iwf/
├── ansible/
│   ├── playbook.yml              # Main Ansible playbook
│   ├── inventory.yml             # Inventory with all hosts
│   ├── group_vars/
│   │   ├── iwf20_stage_fw_bsd   # Staging firewall config
│   │   └── iwf20_prod_fw_bsd    # Production firewall config
│   └── host_vars/               # Per-host variables
└── terraform/                    # Infrastructure as code
```

### Deployment via Semaphore

**Semaphore Host:** `http://10.10.99.16:3000`

**Available Templates:**
- Template 13: `stage-fw-copy` - Deploy to staging firewalls
- Template 14: `prod-fw-copy` - Deploy to production firewalls
- Template 18: `get_url` - Download files to hosts
- Template 7: `tf` - Terraform operations

#### Deploying Configuration Changes

**1. Pull Latest Code:**
```bash
cd /home/ivo/workspace/flamelet-iwf/ansible
git checkout main
git pull
```

**2. Dry Run (Check Mode):**
```bash
aiops semaphore run flamelet-iwf 13 --check --diff --follow
```

**3. Apply Changes:**
```bash
aiops semaphore run flamelet-iwf 13 --follow
```

**4. Deploy to Production Firewalls:**
```bash
# Dry run first
aiops semaphore run flamelet-iwf 14 --check --diff --follow

# Apply
aiops semaphore run flamelet-iwf 14 --follow
```

#### Advanced Options

```bash
# Limit to specific hosts
aiops semaphore run flamelet-iwf 13 --limit "iwf-stage-fw-01.iwf" --follow

# Run specific tags only
aiops semaphore run flamelet-iwf 13 --tags "copy" --follow

# Combined options
aiops semaphore run flamelet-iwf 13 --limit "iwf-stage-fw-01.iwf" --tags "copy" 
--check --diff --follow
```

### Common Configuration Updates

**WireGuard Configuration Changes:**

1. Edit the group_vars file:
```bash
# For staging
vim ansible/group_vars/iwf20_stage_fw_bsd

# For production
vim ansible/group_vars/iwf20_prod_fw_bsd
```

2. Update the WireGuard peer configuration in the `conf_copy_custom` section 
under `/etc/hostname.wg0`

3. Commit and push changes:
```bash
git add ansible/group_vars/
git commit -m "Update wireguard configuration for <user>"
git push origin main
```

4. Deploy via Semaphore (as shown above)

### Inventory Configuration

**Staging Firewalls:**
- `iwf-stage-fw-01.iwf` - 172.23.16.21 (CARP master, advskew: 0)
- `iwf-stage-fw-02.iwf` - 172.23.16.22 (CARP backup, advskew: 100)
- VIP: 172.23.16.20

**Production Firewalls:**
- `iwf-prod-fw-01.iwf` - 172.33.16.21 (CARP master, advskew: 0)
- `iwf-prod-fw-02.iwf` - 172.33.16.22 (CARP backup, advskew: 100)
- VIP: 172.33.16.20

### Ansible Playbook Tags

The playbook supports various tags for targeted deployments:

- `users` - User management
- `packages` - Package installation
- `sysctl` - Kernel parameters
- `pf` - Packet filter (firewall rules)
- `unbound` - DNS resolver
- `monit` - Monitoring
- `post` - Post-configuration tasks
- `copy` - File copy operations

**Example: Deploy only firewall config changes:**
```bash
aiops semaphore run flamelet-iwf 13 --tags "pf" --follow
```

### Troubleshooting

**DNS Resolution Issues:**
If Semaphore can't resolve `.iwf` hostnames:
- The Semaphore server at 10.10.99.16 needs DNS configured for the `.iwf` domain
- Alternative: Uncomment IP addresses in inventory.yml (not recommended)

**SSH Key Issues:**
```bash
# Test SSH connection
ssh -i ~/.ssh/syseng/id_rsa-iwf-syseng git@git.iwf.io

# Verify SSH agent
ssh-add -l

# Add key if needed
ssh-add ~/.ssh/syseng/id_rsa-iwf-syseng
```

**Task Logs:**
```bash
# List recent tasks
aiops semaphore tasks flamelet-iwf --limit 10

# Get task status
aiops semaphore status flamelet-iwf <task-id>

# View task logs
aiops semaphore logs flamelet-iwf <task-id>
```

### Recent Deployments

**2025-12-12:** Updated Christian Huber's wireguard keys
- Task ID: 293
- Template: stage-fw-copy (ID: 13)
- Changes: Updated wgpeer configuration with new public key
- Status: Successfully deployed to both staging firewalls
- Commit: 6c85ab5 "added christian huber to wireguard list (not active yet!)"

---

## DCX Tenant Configuration

**Tenant ID:** 1
**Tenant Name:** `dcx`

### customer-dcx Project (Internal Issue Tracking)

**Purpose:** Internal GitLab project for tracking DCX-related work that should 
NOT be visible to the customer. Use this for internal tasks, planning, and 
documentation instead of the customer-facing Jira.

**Project Details:**
- **Project ID:** 12
- **Project Name:** `customer-dcx`
- **Repository:** https://gitlab.com/floads/syseng/customer-dcx.git
- **GitLab URL:** https://gitlab.com/floads/syseng/customer-dcx
- **Default Branch:** main
- **Tenant:** dcx (ID: 1)

**Integration Details:**
- **Integration Name:** `gitlab-dcx`
- **Integration ID:** 12
- **Provider:** gitlab
- **Base URL:** https://gitlab.com
- **External Identifier:** `floads/syseng/customer-dcx`

### Issue Management Commands

```bash
# Create internal DCX issue (not customer-facing)
aiops issues create --project 12 --integration 12 \
  --title "Issue title" \
  --description "Issue description"

# Or by project name
aiops issues create --project customer-dcx --integration 12 \
  --title "Issue title" \
  --description "Issue description"

# Sync issues from GitLab
aiops issues sync --project 12

# List DCX issues
aiops issues list --tenant dcx
aiops issues list --project customer-dcx

# View specific issue
aiops issues get <issue-id>

# Add comment
aiops issues comment <issue-id> "Your comment"

# Close issue
aiops issues close <issue-id>
```

### When to Use customer-dcx vs jira-dcx

| Use Case | Where to Create Issue |
|----------|----------------------|
| Internal planning/tracking | `customer-dcx` (GitLab, ID 12) |
| Technical notes not for customer | `customer-dcx` (GitLab, ID 12) |
| Customer-facing tickets | `jira-dcx` (Jira, ID 3) |
| Support requests from customer | `jira-dcx` (Jira, ID 3) |

### Architecture Notes

**Similar Pattern to customer-mdo:**
- Both `customer-dcx` and `customer-mdo` follow the same pattern
- GitLab repos under `floads/syseng/customer-*` namespace
- Separate tenant integrations for proper isolation
- Internal-only issue tracking parallel to customer Jira

**Database Structure:**
```
tenants (id=1, name=dcx)
  └─ projects (id=12, name=customer-dcx, tenant_id=1)
       └─ project_integrations (project_id=12, integration_id=12,
            external_identifier='floads/syseng/customer-dcx')

tenant_integrations (id=12, tenant_id=1, name=gitlab-dcx, provider=gitlab)
tenant_integrations (id=13, tenant_id=1, name=semaphore-dcx, provider=semaphore)
```

### Semaphore Integration

**Integration Details:**
- **Integration Name:** `semaphore-dcx`
- **Integration ID:** 13
- **Provider:** semaphore
- **Semaphore Server:** http://10.10.99.16:3000
- **Semaphore Project ID:** 2 (dcx)

**Linked Project:**
- `flamelet-dcx` (ID 1) → Semaphore project 2

### Semaphore Commands for DCX

```bash
# List available templates
aiops semaphore templates flamelet-dcx

# Run a template
aiops semaphore run flamelet-dcx <template_id> --follow

# Run with options
aiops semaphore run flamelet-dcx <template_id> --limit "hostname" --tags 
"tag1,tag2" --follow

# Dry run (check mode)
aiops semaphore run flamelet-dcx <template_id> --check --diff --follow

# List recent tasks
aiops semaphore tasks flamelet-dcx

# Get task status/logs
aiops semaphore status flamelet-dcx <task_id>
aiops semaphore logs flamelet-dcx <task_id>
```

### Available DCX Templates (Semaphore Project 2)

| ID | Name | Description |
|----|------|-------------|
| 12 | all-healthchecksio | Healthchecks.io monitoring |
| 2 | all-shell | Shell commands |
| 5 | all-timezone-file-copy-linux | Timezone file copy |
| 10 | docker | Docker operations |
| 3 | prod-packages | Package management |
| 6 | tf | Terraform |
| 9 | unbound | DNS resolver config |
---

## Terraform/OpenTofu Usage for DCX Infrastructure

**Tool:** OpenTofu v1.11.1 (open-source Terraform fork)
**Working Directory:** `/home/ivo/workspace/flamelet-dcx/terraform`
**Provider:** Flow Swiss (`registry.opentofu.org/flowswiss/flow` v1.1.0)

### Installation

```bash
# Install OpenTofu (one-time setup)
curl -fsSL https://get.opentofu.org/install-opentofu.sh > 
/tmp/install-opentofu.sh
sudo bash /tmp/install-opentofu.sh

# Verify installation
tofu version
# OpenTofu v1.11.1
```

### AWS Credentials for DCX

**Location:** `~/.zshrc.floads`

**Export Command:**
```bash
# Use this alias before running tofu commands
export_aws_dcx

# Or export manually:
export AWS_ACCESS_KEY_ID="f956c16386abf12eSHKO"
export AWS_SECRET_ACCESS_KEY="l7lqJaMfI08qApbQwDTEHGAIcdeRVpUgIM0AnhuE"
```

**Important:** Always export AWS credentials before running tofu commands for 
DCX infrastructure.

### Standard Workflow

```bash
# 1. Navigate to terraform directory
cd /home/ivo/workspace/flamelet-dcx/terraform

# 2. Export AWS credentials
export_aws_dcx

# 3. Initialize (first time or after provider changes)
tofu init -var-file=$HOME/.terraform/dcx.tfvars

# 4. Plan changes
tofu plan -var-file=$HOME/.terraform/dcx.tfvars

# 5. Apply changes
tofu apply -var-file=$HOME/.terraform/dcx.tfvars
```

### Makefile Targets

The `terraform/Makefile` provides convenient targets for common operations:

```bash
# General operations
make init          # Initialize Terraform with DCX vars
make validate      # Validate Terraform configuration
make plan          # Run terraform plan
make apply         # Plan and apply changes (with confirmation)
make apply-approve # Plan and apply changes (auto-approve)

# Targeted provisioning examples
make dcx-test-flow-alp1-db-04-drtest  # Provision DR test host
make backup-volume-all                 # Update all backup volumes

# State management
make state-pull    # Pull remote state to .terraform/remote.tfstate
make state-push    # Push local state to remote
```

### Targeted Resource Operations

For provisioning specific resources (e.g., DR test host):

```bash
# Using Makefile target (recommended)
cd /home/ivo/workspace/flamelet-dcx/terraform
export_aws_dcx
make dcx-test-flow-alp1-db-04-drtest

# Or using tofu directly with targets
tofu plan -var-file=$HOME/.terraform/dcx.tfvars \
  -target=flow_compute_server.DCX_TEST_FLOW_ALP1_DB_04_DRTEST \
  -target=flow_compute_volume.Root_Volume_DCX_TEST_FLOW_ALP1_DB_04_DRTEST \
  -target=flow_compute_volume.Backup_Volume_DCX_TEST_FLOW_ALP1_DB_04_DRTEST \
  -target=flow_compute_volume_attachment.Attachment_DCX_TEST_FLOW_ALP1_DB_04_DRT
EST \
  -target=flow_compute_volume_attachment.Attachment_Backup_DCX_TEST_FLOW_ALP1_DB
_04_DRTEST

tofu apply -var-file=$HOME/.terraform/dcx.tfvars \
  
```

### Backend Configuration

**Backend Type:** S3-compatible (Flow Swiss Object Storage)
**Location:** `terraform/backend.tf`

```hcl
terraform {
  backend "s3" {
    endpoints                   = { s3 = "https://os.zrh1.flow.swiss" }
    bucket                      = "terraform"
    key                         = "state.tfstate"
    region                      = "main"
    skip_credentials_validation = true
    skip_requesting_account_id  = true
    skip_metadata_api_check     = true
    use_path_style              = true
  }
}
```

### Common Tasks

**Provision new infrastructure:**
```bash
cd /home/ivo/workspace/flamelet-dcx/terraform
export_aws_dcx
make dcx-test-flow-alp1-db-04-drtest  # Or other Makefile target
```

**Destroy specific resources:**
```bash
cd /home/ivo/workspace/flamelet-dcx/terraform
export_aws_dcx
tofu destroy -var-file=$HOME/.terraform/dcx.tfvars \
  -target=flow_compute_server.DCX_TEST_FLOW_ALP1_DB_04_DRTEST \
  -target=flow_compute_volume.Root_Volume_DCX_TEST_FLOW_ALP1_DB_04_DRTEST \
  -target=flow_compute_volume.Backup_Volume_DCX_TEST_FLOW_ALP1_DB_04_DRTEST \
  -target=flow_compute_volume_attachment.Attachment_DCX_TEST_FLOW_ALP1_DB_04_DRT
EST \
  -target=flow_compute_volume_attachment.Attachment_Backup_DCX_TEST_FLOW_ALP1_DB
_04_DRTEST
```

**View current state:**
```bash
cd /home/ivo/workspace/flamelet-dcx/terraform
export_aws_dcx
tofu show
```

### Key Files

- `terraform/backend.tf` - S3 backend configuration
- `terraform/dr_test.tf` - DR test infrastructure 
(dcx-test-flow-alp1-db-04-drtest)
- `terraform/Makefile` - Convenience targets for common operations
- `~/.terraform/dcx.tfvars` - DCX-specific variable values (NOT in git)
- `.terraform.lock.hcl` - Provider version lock file

### Important Notes

- **ALWAYS export AWS credentials** before running tofu commands
(`export_aws_dcx`)
- **Use var-file:** All commands require `-var-file=$HOME/.terraform/dcx.tfvars`
- **State is remote:** Stored in Flow Swiss S3, shared across team
- **Targeted operations:** Use `-target=` flags or Makefile targets to operate
on specific resources
- **Exit codes:** `tofu plan` exits with code 2 when changes exist (not an
error)
- **Provider:** Flow Swiss provider v1.1.0 is locked in `.terraform.lock.hcl`

### CRITICAL: Terraform `-target=` Flag Gotcha (GLOBAL RULE)

**LESSON LEARNED (Dec 17, 2025):** When using `-target=` flags in 
Terraform/OpenTofu, **ALWAYS include dependent resources**, not just the primary
resources.

**The Mistake:**
```bash
# ❌ WRONG - Only targets volumes, attachments get removed from state
tofu apply -var-file=$HOME/.terraform/dcx.tfvars \
  -target=flow_compute_volume.Backup_Volume_DCX_DEV_FLOW_ALP1_DB_01 \
  -target=flow_compute_volume.Backup_Volume_DCX_DEV_FLOW_ALP1_DB_02
  # Missing: -target=flow_compute_volume_attachment.*
```

**What Happens:**
1. Volumes are updated in state ✅
2. Attachment resources NOT in targets are **removed from state** ❌
3. Terraform "forgets" attachment management
4. Next `tofu plan` wants to recreate attachments (destructive)
5. Causes unintended resource cycling

**The Fix:**
```bash
# ✅ CORRECT - Include both volumes AND their attachments
tofu apply -var-file=$HOME/.terraform/dcx.tfvars \
  -target=flow_compute_volume.Backup_Volume_DCX_DEV_FLOW_ALP1_DB_01 \
  -target=flow_compute_volume_attachment.Attachment_Backup_DCX_DEV_FLOW_ALP1_DB_
01 \
  -target=flow_compute_volume.Backup_Volume_DCX_DEV_FLOW_ALP1_DB_02 \
  -target=flow_compute_volume_attachment.Attachment_Backup_DCX_DEV_FLOW_ALP1_DB_
02
```

**Resource Dependencies to Remember:**
- Volume → Volume Attachment → Server
- Always include ALL in target list when using `-target=`
- If targeting a child resource (attachment), must target parent (volume)
- If targeting parent (volume), should target child (attachment) too

**This applies to:**
- ✅ All infrastructure (DCX, Floads, any project)
- ✅ Any Terraform/OpenTofu provider
- ✅ Any resource with dependencies (servers+volumes, networks+interfaces, etc.)
- ✅ All environments (dev, test, prod)

**Best Practice:**
When modifying infrastructure with `-target=`:
1. Identify PRIMARY resource (what you want to change)
2. Identify DEPENDENT resources (what attaches to it)
3. Include BOTH in `-target=` list
4. Run `tofu plan` first to verify targets
5. Review plan before apply

**Real-World Impact (Dec 17, 2025):**
- **Affected:** All backup volume attachments (Dev, Test, Prod)
- **Cause:** `make backup-volume-all` only targeted volumes
- **Result:** 9 attachment resources removed from state management
- **Fix:** Update Makefile to include attachment targets

### Troubleshooting

**"Error: Failed to get existing workspaces"**
→ AWS credentials not exported. Run `export_aws_dcx` first.

**"No configuration files"**
→ Wrong directory. Must be in `/home/ivo/workspace/flamelet-dcx/terraform`

**"tofu: command not found"**
→ OpenTofu not installed. Run installation script (see Installation section).

**Semaphore template shows "error" status after plan**
→ Not actually an error. `tofu plan` exits with code 2 when changes exist. 
Review plan output to confirm correctness.
---

## Flow Swiss API & Terraform Provider (DCX Infrastructure)

**API Documentation:** https://doc.flow.swiss/developer-center/api/
**Control Panel:** https://my.flow.swiss/
**API Base URL:** https://api.flow.swiss/

### Authentication

**Method:** Token-based authentication via `X-Auth-Token` header

**Get Token:**
```bash
curl -X POST "https://api.flow.swiss/v3/auth" \
  -H "Content-Type: application/json" \
  -d '{"username": "user@example.com", "password": "password"}'
```

**Response:**
```json
{
  "token": "your-auth-token",
  "id": 1,
  "username": ""
}
```

**Usage:**
```bash
curl -X GET "https://api.flow.swiss/v4/compute/servers" \
  -H "X-AUTH-TOKEN: your-auth-token"
```

### Terraform Provider

**Provider:** `registry.opentofu.org/flowswiss/flow`
**Version:** 1.1.0 (locked in DCX infrastructure)
**Documentation:** 
https://registry.terraform.io/providers/flowswiss/flow/latest/docs

**Authentication for Terraform:**
Uses AWS-style credentials (S3-compatible API):
- `AWS_ACCESS_KEY_ID`: Flow Swiss access key
- `AWS_SECRET_ACCESS_KEY`: Flow Swiss secret key

**DCX Credentials Location:** `~/.zshrc.floads` (export_aws_dcx alias)

### Product IDs (DCX Infrastructure)

**Compute Instances (used in DCX):**
- **Product ID 26:** Small instances (dev/test firewalls)
- **Product ID 30:** Standard instances (test nodes, prod replicas)
- **Product ID 32:** Medium instances (test db-01)
- **Product ID 34:** Large instances (prod db-01)

**General Product Categories:**
- **Mac Bare Metal:** IDs 11-14
- **Object Storage:** ID 20
- **Compute (b1 series):** IDs 24-40 (graduated sizing)
- **Kubernetes k1:** IDs 44-54
- **Kubernetes k2:** IDs 130-140
- **Elastic IP:** ID 8, 23

**Reference:** https://doc.flow.swiss/developer-center/api/product-entities

### Location IDs (DCX Infrastructure)

- **Location ID 1:** ALP1 (Alpnach) - Used for test/dev environments
- **Location ID 2:** ZRH1 (Zurich) - Used for production environments

### Network IDs (DCX Infrastructure)

- **Network ID 1927:** Production network (172.19.0.0/20) - ZRH1
- **Network ID 1928:** Firewall network (172.20.0.0/20) - ZRH1
- **Network ID 2086:** Test firewall network - ALP1
- **Network ID 2437:** Test/dev network (172.19.0.0/20) - ALP1

### Key Pair IDs (DCX Infrastructure)

- **Key Pair ID 132:** FW-DCNX-FLOW-CH (firewall)
- **Key Pair ID 162:** Test Fortigate
- **Key Pair ID 440:** Test database nodes (ALP1)
- **Key Pair ID 441:** Dev database nodes (ALP1)
- **Key Pair ID 457:** Production database nodes (ZRH1)

### Common API Operations

**List Compute Servers:**
```bash
curl -X GET "https://api.flow.swiss/v4/compute/servers" \
  -H "X-AUTH-TOKEN: $TOKEN"
```

**List Routers:**
```bash
curl -X GET "https://api.flow.swiss/v4/compute/routers" \
  -H "X-AUTH-TOKEN: $TOKEN"
```

### Terraform Resources (DCX)

**Common Resources:**
- `flow_compute_server` - Virtual machines
- `flow_compute_volume` - Block storage volumes
- `flow_compute_volume_attachment` - Attach volumes to servers
- `flow_network` - Networks
- `flow_compute_elastic_ip` - Public IPs

**Example (from dr_test.tf):**
```hcl
resource "flow_compute_server" "DCX_TEST_FLOW_ALP1_DB_05_DRTEST" {
  name         = "dcx-test-flow-alp1-db-05-drtest"
  image_id     = 53          # Debian
  location_id  = 1           # ALP1
  product_id   = 30          # Standard instance
  key_pair_id  = 440         # Test nodes SSH key
  network_id   = 2437        # Test network
  private_ip   = "172.19.0.185"
}

resource "flow_compute_volume" "Root_Volume_DCX_TEST_FLOW_ALP1_DB_05_DRTEST" {
  name        = "Root Volume of dcx-test-flow-alp1-db-05-drtest"
  size        = 5760         # GB
  location_id = 1            # ALP1
}

resource "flow_compute_volume_attachment" 
"Attachment_DCX_TEST_FLOW_ALP1_DB_05_DRTEST" {
  server_id = flow_compute_server.DCX_TEST_FLOW_ALP1_DB_05_DRTEST.id
  volume_id = flow_compute_volume.Root_Volume_DCX_TEST_FLOW_ALP1_DB_05_DRTEST.id
}
```

### Image IDs (DCX Infrastructure)

- **Image ID 18:** FortiGate
- **Image ID 24:** Test FortiGate
- **Image ID 53:** Debian (used for all database nodes)

### Useful Links

- **API Documentation:** https://doc.flow.swiss/developer-center/api/
- **Product Entities:** 
https://doc.flow.swiss/developer-center/api/product-entities
- **Authentication:** https://my.flow.swiss/#/doc/authentication
- **Control Panel:** https://my.flow.swiss/
- **Terraform Provider:** 
https://registry.terraform.io/providers/flowswiss/flow/latest/docs

---

---

## CRITICAL: Terraform `-target=` Flag Gotcha (GLOBAL RULE)

**LESSON LEARNED (Dec 17, 2025):** When using `-target=` flags in 
Terraform/OpenTofu, **ALWAYS include dependent resources**, not just the primary
resources.

### The Mistake:
```bash
# ❌ WRONG - Only targets volumes, attachments get removed from state
tofu apply -var-file=$HOME/.terraform/dcx.tfvars \
  -target=flow_compute_volume.Backup_Volume_DCX_DEV_FLOW_ALP1_DB_01 \
  -target=flow_compute_volume.Backup_Volume_DCX_DEV_FLOW_ALP1_DB_02
  # Missing: -target=flow_compute_volume_attachment.*
```

### What Happens:
1. Primary resources are updated in state ✅
2. Dependent resources NOT in targets are **removed from state** ❌
3. Terraform "forgets" dependent resource management
4. Next `tofu plan` wants to recreate dependent resources (destructive)
5. Causes unintended resource cycling and data loss risk

### The Fix:
```bash
# ✅ CORRECT - Include both primary resources AND their dependent resources
tofu apply -var-file=$HOME/.terraform/dcx.tfvars \
  -target=flow_compute_volume.Backup_Volume_DCX_DEV_FLOW_ALP1_DB_01 \
  -target=flow_compute_volume_attachment.Attachment_Backup_DCX_DEV_FLOW_ALP1_DB_
01 \
  -target=flow_compute_volume.Backup_Volume_DCX_DEV_FLOW_ALP1_DB_02 \
  -target=flow_compute_volume_attachment.Attachment_Backup_DCX_DEV_FLOW_ALP1_DB_
02
```

### Common Resource Dependencies:
- **Volume + Attachment**: Volume → Volume Attachment → Server
- **Network + Interface**: Network → Network Interface → Server

### MANDATORY: Always Plan + Ask First
- For Terraform: `tofu plan` before `tofu apply`
- For Ansible: `ansible-playbook --check --diff` before real run
- ALWAYS ask user first before running ANY infrastructure change

---

## CRITICAL: Mandatory Safety Protocol for ALL Infrastructure Changes

**GLOBAL RULE (Effective Immediately):** Before making ANY changes to 
infrastructure via Ansible, Terraform, or OpenTofu:

### MANDATORY Checklist:
1. ✅ **ASK USER FIRST** - Get explicit approval
2. ✅ **PLAN/DRY-RUN FIRST** - Preview changes before executing
3. ✅ **SHOW FULL OUTPUT** - Display complete plan to user
4. ✅ **GET EXPLICIT APPROVAL** - Wait for confirmation
5. ✅ **DOCUMENT WHAT YOU'RE DOING** - State clearly what will happen

**Never:**
- Run infrastructure commands without asking user first
- Skip planning/check phase
- Use auto-approve flags without asking
- Batch commands without per-command approval
- Make changes in background without approval

**Applies to:** All infrastructure projects (DCX, Floads, CloudBit, etc.), all 
environments, all cloud providers, ALL AGENTS


---

## ⚠️ UNIVERSAL INFRASTRUCTURE SAFETY RULE (ALL ENVIRONMENTS)

**This applies to EVERY infrastructure change, EVERYWHERE, for ALL projects and 
environments:**

### The Golden Rule:
```
NO INFRASTRUCTURE CHANGE WITHOUT:
1. ASK USER FIRST
2. PLAN/DRY-RUN FIRST
3. SHOW FULL OUTPUT
4. GET EXPLICIT APPROVAL
5. DOCUMENT WHAT YOU'RE DOING
```

### This is NOT optional. It applies globally to:

- ✅ **All Projects:** DCX, Floads, CloudBit, LNZ, any customer, any internal 
project
- ✅ **All Environments:** dev, test, staging, prod, DR, any environment
- ✅ **All Tools:** Terraform, OpenTofu, Ansible, Puppet, CloudFormation, any 
IaC
- ✅ **All Cloud Providers:** AWS, GCP, Azure, Flow Swiss, any provider
- ✅ **All Teams:** SysEng, DevOps, Platform, any team
- ✅ **All Agents:** AI agents, automation, CI/CD pipelines, humans, any 
executor

### Before ANY of These Commands:

```bash
# ❌ FORBIDDEN without asking + plan first
terraform apply
tofu apply
ansible-playbook ... (real execution)
kubectl apply
helm upgrade
aws cli commands (that create/modify/delete resources)
ssh user@prod 'sudo systemctl restart ...'
```

### Required Protocol:

1. **ASK USER:** "I'm about to make infrastructure changes. Do you approve?"
2. **PLAN:** Show `terraform plan`, `tofu plan`, `ansible --check --diff`, etc.
3. **SHOW OUTPUT:** Display FULL plan to user (all resources, changes, 
deletions)
4. **GET APPROVAL:** Wait for explicit "yes" or "approve" from user
5. **DOCUMENT:** State clearly what will happen, impact, downtime, rollback

### Exception: Read-Only Operations

Only these DO NOT require asking first:
- `terraform plan` (without apply)
- `ansible --check` (without real execution)
- `kubectl get`, `kubectl describe`, `kubectl logs`
- Reading configs, viewing status, displaying information

### Violation = Critical Safety Issue

If ANY infrastructure change happens without this protocol:
- 🚨 It's a CRITICAL SAFETY VIOLATION
- 🚨 Must be prevented and reported
- 🚨 Could result in data loss, downtime, security breach

### Why This Exists

Infrastructure changes affect:
- **Data:** Production databases, customer information, backups
- **Availability:** Services, users, business continuity, SLAs
- **Security:** Access control, compliance, audit trails
- **Cost:** Resource spending, budget impact
- **People:** Team impact, on-call situations, incident response

### Never Assume You Can:

- ❌ "It's just dev, no need to ask"
- ❌ "It's a small change, I'll just do it"
- ❌ "The user is busy, I'll apply it and tell them later"
- ❌ "Automation approved this, so it's OK"
- ❌ "I've done this before, no need to check"

### Always:

- ✅ Ask first, every single time
- ✅ Show the plan, every single time
- ✅ Wait for approval, every single time
- ✅ Document what you did, every single time

**This is non-negotiable. No exceptions. Across all projects, all teams, all 
environments.**


---

## CRITICAL: Global Agents Context Management Rule

**MANDATORY RULE FOR AGC ITSELF:**

### The Golden Rule of AGC Updates:
```
ALWAYS APPEND to Global Agents Context
NEVER OVERWRITE Global Agents Context
```

### How to Update AGC Correctly:

```bash
# ❌ FORBIDDEN - This OVERWRITES and DELETES previous content
aiops agents global set --file /tmp/new_content.md

# ✅ CORRECT - This APPENDS to existing content
# 1. Get current AGC
aiops agents global get > /tmp/current_agc.md

# 2. Append new content to it
cat >> /tmp/current_agc.md << 'NEWCONTENT'
## New Section
Your new content here
NEWCONTENT

# 3. Update with combined content
aiops agents global set --file /tmp/current_agc.md
```

### Why This Rule Exists:

The Global Agents Context is:
- ✅ **Cumulative knowledge** - Information builds over time
- ✅ **Historical record** - Contains lessons learned, guidelines, fixes
- ✅ **Used by all agents** - Every agent relies on complete context
- ✅ **Critical reference** - Contains infrastructure, team workflows, 
procedures

Overwriting AGC:
- 🚨 **Loses critical information** - Previous lessons disappear
- 🚨 **Breaks agent guidance** - Agents lose access to important context
- 🚨 **Violates compliance** - Audit trails, historical context erased
- 🚨 **Causes repeated mistakes** - Teams forget lessons already learned
- 🚨 **Damages institutional knowledge** - Hard-won expertise is lost

### Enforcement:

**If AGC was overwritten (by mistake or intentionally):**

1. ✅ Immediately rollback to previous version
   ```bash
   aiops agents global rollback VERSION_NUMBER
   ```

2. ✅ Retrieve the overwritten content from git or backup
   ```bash
   git show HEAD:AGENTS.override.md > /tmp/backup.md
   ```

3. ✅ Properly APPEND the new content
   ```bash
   cat >> /tmp/backup.md << 'EOF'
   ... new content ...
   EOF
   aiops agents global set --file /tmp/backup.md
   ```

4. ✅ Verify nothing was lost
   ```bash
   aiops agents global get | wc -l
   # Should be LARGER than before, not smaller
   ```

### Checklist Before Updating AGC:

- ✅ Have you retrieved current AGC first? (`aiops agents global get`)
- ✅ Are you APPENDING to existing content?
- ✅ Did you preserve ALL previous sections?
- ✅ Is the new file LARGER than before (in line count)?
- ✅ Are you using `--file` with combined content (not piping small chunks)?
- ✅ Have you verified the update succeeded?
- ✅ Have you verified nothing was deleted?

### Size Verification:

```bash
# Before update
BEFORE=$(aiops agents global get | wc -l)

# After update
AFTER=$(aiops agents global get | wc -l)

# Check result
if [ $AFTER -lt $BEFORE ]; then
  echo "🚨 ERROR: Content was deleted! Rollback immediately!"
  aiops agents global rollback PREVIOUS_VERSION
else
  echo "✅ OK: Content was appended"
fi
```

### Never:

- ❌ Overwrite AGC with a new file
- ❌ Use `set` with only new content
- ❌ Forget to include previous content
- ❌ Assume AGC is backed up (it is, but don't test it)
- ❌ Update without checking that content was appended

### Always:

- ✅ Get current AGC first
- ✅ Append to it
- ✅ Verify size increased
- ✅ Preserve all history
- ✅ Document what you added

**This rule applies to EVERYONE updating AGC - no exceptions.**
## Complete OpenBSD OS Upgrade Procedure

OpenBSD hosts (core.floads, monitor-10.floads, rtty.floads) should be upgraded 
using `sysupgrade` for major version releases.

### Pre-upgrade checklist

1. **Verify console access** — Ensure out-of-band access available if SSH fails
2. **Check running services** — Document what should restart after reboot
3. **Notify if needed** — For critical infrastructure like core.floads 
(WireGuard gateway)

### Complete 10-Step Upgrade Procedure

**1. Check current version and available upgrade:**
```bash
ssh syseng@HOST 'uname -a'
ssh syseng@HOST 'doas sysupgrade -n'  # Dry run to check availability
```

**2. Backup configuration:**
```bash
ssh syseng@HOST 'doas sh -c "cd / && tar czf /root/pre-upgrade-backup-$(date 
+%Y%m%d).tgz etc/pf.conf etc/hostname.* etc/rc.conf.local etc/hosts 
var/unbound/etc/unbound.conf 2>&1 | grep -v \"Removing leading\" ; ls -lh 
/root/pre-upgrade-backup-*.tgz"'
```

**3. Execute upgrade (downloads sets and schedules upgrade for next boot):**
```bash
ssh syseng@HOST 'doas sysupgrade'
# System will reboot automatically after download completes
```

**4. Wait for system to come back online:**
```bash
# Wait ~2 minutes, then test connectivity
for i in {1..20}; do
  echo "Attempt $i: Checking if HOST is back online..."
  ssh -o ConnectTimeout=5 syseng@HOST 'uname -r' 2>/dev/null && echo "SUCCESS!" 
&& break
  sleep 10
done
```

**5. Verify upgrade and services:**
```bash
# Check version
ssh syseng@HOST 'uname -a && uptime'

# Verify all services started
ssh syseng@HOST 'doas rcctl ls started'

# Check critical services (adjust per host)
ssh syseng@HOST 'doas ifconfig wg0 | head -5'  # WireGuard (core, monitor-10)
ssh syseng@HOST 'doas pfctl -sr | head -20'    # PF firewall
```

**6. Update packages:**
```bash
ssh syseng@HOST 'doas pkg_add -u'
# Review any warnings about modified config files (/etc/monitrc, /etc/sudoers, 
etc.)
```

**7. Install binary security patches:**

**IMPORTANT**: OpenBSD 7.8 has a known syspatch bug (Errata 001_syspatch) where 
syspatch fails with "Read-only filesystem, aborting" on systems where /usr is 
not a separate filesystem.

**Workaround for OpenBSD 7.8:**
```bash
# Step 1: Create modified syspatch script
ssh syseng@HOST 'doas sh -c "sed -e \"s/.checkfs/#checkfs/g\" /usr/sbin/syspatch
> /root/syspatch"'

# Step 2: Run modified script (installs 001_syspatch, updates syspatch itself)
ssh syseng@HOST 'doas ksh /root/syspatch'
# Expected output: "syspatch: updated itself, run it again to install missing 
patches"

# Step 3: Run updated syspatch to install remaining patches
ssh syseng@HOST 'doas syspatch'
# Expected output: "Relinking to create unique kernel... done; reboot to load 
the new kernel"

# Step 4: Cleanup and regenerate device database
ssh syseng@HOST 'doas rm /root/syspatch && doas dev_mkdb'

# Step 5: Verify all patches installed
ssh syseng@HOST 'doas syspatch -l'
# Should list: 001_syspatch through 011_nd6 (or latest available)
```

**For OpenBSD 7.9+** (if bug is fixed):
```bash
ssh syseng@HOST 'doas syspatch'
# Verify with: doas syspatch -l
```

**8. Run sysmerge (if needed):**
```bash
ssh syseng@HOST 'doas sysmerge'
# Choose 'd' to preserve current files, 'i' to accept new versions
# Pay special attention to /etc/login.conf if prompted
```

**9. Test reboot:**
```bash
# Reboot to verify everything comes back cleanly
ssh syseng@HOST 'doas reboot'

# Wait and verify
sleep 60
for i in {1..20}; do
  ssh -o ConnectTimeout=5 syseng@HOST 'uname -r' 2>/dev/null && break
  sleep 10
done

# Final verification
ssh syseng@HOST 'uname -a && doas rcctl ls started'
```

**10. Test connectivity (for gateway hosts like core.floads):**
```bash
# Verify WireGuard connectivity
ssh dev.floads 'ping -c 3 docker.floads'
ping -c 3 docker.floads
```

---

## OpenBSD 7.8 Syspatch Bug - Errata 001_syspatch

**Issue:** OpenBSD 7.8 syspatch fails with "Read-only filesystem, aborting" on 
systems where /usr is not a separate filesystem.

**Root Cause:** syspatch(8) is confused by aliased /dev/*rootdisk nodes in the 
database generated by dev_mkdb(8). The checkfs() function incorrectly detects 
the root filesystem as read-only.

**Affected Systems:** All OpenBSD 7.8 installations where /usr is on the root 
filesystem (not a separate partition). This affects most standard installations.

**Official Workaround (5-step procedure):**

1. **Create modified syspatch script** - Comment out the checkfs function:
   ```bash
   ssh syseng@HOST 'doas sh -c "sed -e \"s/.checkfs/#checkfs/g\" 
/usr/sbin/syspatch > /root/syspatch"'
   ```

2. **Run modified script** - This installs the 001_syspatch which updates 
syspatch itself:
   ```bash
   ssh syseng@HOST 'doas ksh /root/syspatch'
   ```
   Expected output: `syspatch: updated itself, run it again to install missing 
patches`

3. **Run updated syspatch** - Now use the fixed version to install remaining 
patches:
   ```bash
   ssh syseng@HOST 'doas syspatch'
   ```
   Expected output: `Relinking to create unique kernel... done; reboot to load 
the new kernel`

4. **Cleanup and regenerate device database**:
   ```bash
   ssh syseng@HOST 'doas rm /root/syspatch && doas dev_mkdb'
   ```

5. **Verify all patches installed**:
   ```bash
   ssh syseng@HOST 'doas syspatch -l'
   ```
   Should show all available patches (001_syspatch through 011_nd6 or later)

**Successfully Applied To:**
- core.floads (172.31.3.186 / 10.60.0.1) - 11 patches installed
- monitor-10.floads (172.31.3.10) - 11 patches installed

**Technical Details:**
- Bug appears when running `doas syspatch` immediately after upgrade to OpenBSD 
7.8
- Error message: "Read-only file system, aborting"
- Filesystem is actually writable; the bug is in syspatch's checkfs() function
- The 001_syspatch errata fixes this bug in syspatch itself
- After applying 001_syspatch, subsequent runs work normally

**References:**
- https://www.openbsd.org/errata78.html (Official OpenBSD 7.8 Errata)
- http://www.mail-archive.com/misc@openbsd.org/msg195688.html (Mailing list 
discussion)
- https://www.bsdforen.de/threads/openbsd-7-8-syspatch-read-only.37462/ (German 
BSD forum)
- https://obsd.solutions/en/blog/2025/11/16/openbsd-upgrade-77-to-78/ (Upgrade 
guide)

---

## Expected Download Times

With typical CloudBit network speeds:
- **Download phase**: 3-5 minutes (base set ~500MB, plus kernels and additional 
sets)
- **Upgrade/reboot phase**: 1-2 minutes
- **Total time**: ~5-7 minutes per host

---

## Post-Upgrade Notes

- **Configuration preservation**: Local modifications to `/etc/monitrc`, 
`/etc/sudoers`, and other config files are preserved
- **Firmware updates**: Intel firmware and other drivers are updated 
automatically
- **Service autostart**: All services configured with `rcctl enable` will start 
automatically
- **Package compatibility**: Run `pkg_add -u` after OS upgrade to ensure package
versions match new OS version
- **Kernel relinking**: After applying syspatches, reboot to load the new 
patched kernel

---

## Critical Infrastructure Considerations

**core.floads** (WireGuard gateway):
- Temporarily interrupts WireGuard connectivity to all remote peers during 
reboot
- Verify WireGuard interface (`wg0`) comes back UP after reboot
- Test connectivity from multiple peer networks
- Check PF rules loaded correctly: `doas pfctl -sr`

**monitor-10.floads** (M/Monit):
- Monitoring alerts will pause during upgrade
- Verify M/Monit web interface accessible after upgrade
- Check Monit is monitoring all configured services

---

## Troubleshooting

**Services not starting:**
```bash
# Check service status
doas rcctl check SERVICE_NAME

# Check logs
doas tail -50 /var/log/daemon

# Restart manually
doas rcctl restart SERVICE_NAME
```

**WireGuard not working:**
```bash
# Check interface
doas ifconfig wg0

# Reload hostname.wg0 config
doas sh /etc/netstart wg0
```

**PF rules not loaded:**
```bash
# Check PF status
doas pfctl -sr

# Reload PF rules
doas pfctl -f /etc/pf.conf
```

**Syspatch still failing after workaround:**
```bash
# Verify filesystem is writable
mount | grep "on / "
# Should NOT show "read-only" flag

# Check dev_mkdb was run
ls -l /var/run/dev.db
# Should show recent timestamp

# Re-run device database regeneration
doas dev_mkdb

# Try syspatch again
doas syspatch
```
# OpenBao Credentials - docker.floads (172.31.3.20:8200)
# Initialized: 2025-12-21

Unseal Key 1: AWmr139xkgX8i+0cdNZqVTDbKEOER9KkohosKTBif8np
Unseal Key 2: vh5RykaZuBmj9h96tQpLslIDMGSqRqtE6f2Z+zGn0jHW
Unseal Key 3: qzzJVZMP6hqE6hAdOJfklJjSk9y7GKiRrqdAscwnBOKm
Unseal Key 4: zGJMadODAEjE0lsUd8gZqqOebO+qp7UOnnY0NkevUy8/
Unseal Key 5: A2GgYAbap6kcOu4aIEjRwcHGAuUnZI+eZe64BTez8FGW

Initial Root Token: s.yUF3a8Nu0dFNd5TaHaP7g9wZ

Threshold: 3 of 5 keys required to unseal

---

## OpenBao Access Information

**Web UI**: http://172.31.3.20:8200/ui
**API**: http://172.31.3.20:8200/v1/

**Cluster Details**:
- Cluster Name: vault-cluster-34e3187a
- Cluster ID: 6596e638-2d66-61b4-46c0-19e10af441ac
- Storage Type: file
- HA Enabled: false

**Deployment**:
- Host: docker.floads (172.31.3.20)
- Container: openbao
- Version: 2.0.1
- Initialized: 2025-12-21

**Unseal Procedure** (required after container restart):
```bash
ssh syseng@docker.floads
docker exec openbao bao operator unseal  # Enter key 1
docker exec openbao bao operator unseal  # Enter key 2
docker exec openbao bao operator unseal  # Enter key 3
```

**Login to Web UI**:
1. Navigate to http://172.31.3.20:8200/ui
2. Select "Token" method
3. Enter root token: s.yUF3a8Nu0dFNd5TaHaP7g9wZ

**Login via CLI**:
```bash
ssh syseng@docker.floads
export VAULT_ADDR=http://127.0.0.1:8200
docker exec -e VAULT_TOKEN=s.yUF3a8Nu0dFNd5TaHaP7g9wZ openbao bao status
```

---

## Jira Issue Management with acli

**Use `acli` CLI for managing Jira Cloud work items**

### Searching for Issues

```bash
# Search for issues in a project ordered by most recently updated
acli jira workitem search --jql "project = PROJECTKEY ORDER BY updated DESC" 
--limit 10 --json

# Search with custom fields
acli jira workitem search --jql "project = PROJECTKEY ORDER BY updated DESC" 
--limit 10 --fields "key,summary,status,assignee,priority" --json

# Example: Search IWFCLOUD2 project
acli jira workitem search --jql "project = IWFCLOUD2 ORDER BY updated DESC" 
--limit 10 --json | jq '.[] | {key: .key, summary: .fields.summary, status: 
.fields.status.name, assignee: .fields.assignee.displayName, priority: 
.fields.priority.name}'
```

### Commenting on Issues

```bash
# Add a comment to a Jira issue
acli jira workitem comment add --key PROJECTKEY-123 --comment "Your comment text
here"

# Add comment from file
acli jira workitem comment add --key PROJECTKEY-123 --body "$(cat 
/path/to/summary.txt)"
```

### Transitioning Issues (Changing Status)

```bash
# Transition issue to a specific status
acli jira workitem transition --key PROJECTKEY-123 --status "Done" --yes

# Transition multiple issues using JQL
acli jira workitem transition --jql "project = PROJECTKEY AND status = 'To Do'" 
--status "In Progress" --yes

# Common status values: "To Do", "In Progress", "Done", "Closed"
# Note: Status names may vary per Jira instance (check your Jira workflows)
```

### Creating Issues

```bash
# Create a new Jira issue
acli jira workitem create --project PROJECTKEY \
  --type "Task" \
  --summary "Issue summary" \
  --description "Detailed description" \
  --assignee "user@example.com" \
  --priority "High"
```

### Getting Issue Details

```bash
# Get detailed information about a specific issue
acli jira workitem search --jql "key = PROJECTKEY-123" --json | jq '.[0]'
```

### Common acli Jira Commands

| Command | Purpose |
|---------|---------|
| `acli jira workitem search --jql "..."` | Search for issues using JQL |
| `acli jira workitem view PROJECTKEY-123` | View issue details (interactive) |
| `acli jira workitem comment add --key PROJECTKEY-123` | Add comment to issue |
| `acli jira workitem transition --key PROJECTKEY-123 --status "Done"` | Change 
issue status |
| `acli jira workitem create --project PROJECTKEY` | Create new issue |
| `acli jira project list --recent` | List recent projects |

### acli Installation & Authentication

```bash
# Verify acli is installed
acli --version

# Authenticate with Jira (if needed)
acli jira auth login
```

---

## Global Agents Context (AGC) Management & Usage

**CRITICAL: The Global Agents Context is institutional knowledge that ONLY GROWS
- Never overwrites, always accumulates**

### Key Principles

1. **Information Only Accumulates** - Every update should be a superset of all 
previous versions
2. **No Data Loss** - Previous findings and procedures must always be preserved
3. **Version History is Sacred** - Each version represents a point-in-time 
snapshot of knowledge
4. **Intelligent Updates** - Use proper update procedures to maintain knowledge 
integrity

### Proper Update Procedure (CORRECT ✅)

When adding new information to the global agents context:

```bash
# Step 1: Retrieve current context
aiops agents global get > /tmp/agc_backup.txt

# Step 2: Add new sections or information to the file
cat >> /tmp/agc_backup.txt << 'NEWCONTENT'

## Your New Section Title

Your new content, findings, procedures, configurations, etc.
NEWCONTENT

# Step 3: Update the global context with accumulated knowledge
aiops agents global set --file /tmp/agc_backup.txt

# Verification
aiops agents global get | tail -50  # Verify new content is there
```

### Incorrect Update Procedure (WRONG ❌)

**NEVER do this:**

```bash
# BAD: This replaces the entire context and loses all previous knowledge
aiops agents global set --file /path/to/AGENTS.md

# BAD: This only sets partial information
aiops agents global set --file /path/to/new/section.md
```

### Monitoring Context Growth

```bash
# View version history
aiops agents global history --limit 20

# Check current size
aiops agents global get | wc -l

# View specific version details
aiops agents global history --version 35

# Compare two versions (shows what was added/changed)
aiops agents global diff 35 36
```

### What Goes Into AGC?

**Examples of what SHOULD be added:**

- ✅ Infrastructure access procedures (cluster endpoints, VPN configs)
- ✅ Troubleshooting procedures and solutions
- ✅ Operational procedures and workflows
- ✅ System configurations and their rationale
- ✅ Security findings and remediation steps
- ✅ Performance tuning notes
- ✅ Emergency procedures
- ✅ CLI tool usage and best practices
- ✅ Credentials and authentication methods (safely stored)

**Examples of what SHOULD NOT be added:**

- ❌ Temporary debugging notes that won't be needed again
- ❌ Personal work-in-progress notes
- ❌ Project-specific code (use AGENTS.md in the project instead)
- ❌ Sensitive credentials in plain text (use vault/secrets)

### Benefits of Proper AGC Management

1. **Continuity** - Future agents have full context of past findings
2. **Efficiency** - No re-discovery of solutions or procedures
3. **Safety** - Emergency procedures are always available
4. **Learning** - Knowledge accumulates and evolves
5. **Auditing** - Version history shows what was learned when

---

---

## ⚠️ INTERNAL FLOADS ONLY: Customer Issue Tracking in Floads GitLab

**CRITICAL: This section contains INTERNAL FLOADS information. NEVER share these
URLs or processes with customers.**

This is how we track customer work internally in the floads GitLab instance 
(gitlab.com). Customers should only interact with their own repositories - they 
never see these internal issue tracking repositories.

### Overview

- **Internal Repository**: 
`https://gitlab.com/floads/syseng/customer-{customername}/`
- **Public Repository**: Customer's own repo (e.g., git.iwf.io for IWF)
- **Purpose**: Internal project management, progress tracking, and findings 
documentation
- **Visibility**: Floads-only, not shared with customers
- **All hosted on**: gitlab.com (not a separate instance)

### Creating Issues for Customers (glab CLI)

**glab is already configured for gitlab.com by default:**

```bash
# Verify glab is configured for gitlab.com
glab config get gitlab_host

# If needed, authenticate with your Floads account
glab auth login

# Verify authentication
glab auth status
```

**Create an issue in the customer's internal project:**

```bash
# Basic issue creation
glab issue create \
  -R floads/syseng/customer-iwf \
  -t "Feature: Brief description" \
  -d "Detailed description of what needs to be implemented" \
  -l feature,infrastructure \
  -a username

# With all options
glab issue create \
  -R floads/syseng/customer-{customername} \
  -t "Issue Title (include relevant ID)" \
  -d "Full description with context and acceptance criteria" \
  --due-date "2026-02-15" \
  -l bug,feature,enhancement,documentation,internal \
  -a assignee_username \
  -w 5 \
  -y  # Don't ask for confirmation

# Example: Create an issue for IWF customer
glab issue create \
  -R floads/syseng/customer-iwf \
  -t "K8s STAGE cluster: 2 Nodes hinzufügen" \
  -d "Add 2 additional nodes to the STAGE cluster to improve availability" \
  -l infrastructure,high-priority \
  -a ivo \
  -y
```

### Managing Customer Issues

**List issues in customer project:**

```bash
# List all open issues
glab issue list -R floads/syseng/customer-iwf

# List closed issues
glab issue list -R floads/syseng/customer-iwf --state closed

# Filter by assignee
glab issue list -R floads/syseng/customer-iwf --assignee ivo

# Get JSON output for parsing
glab issue list -R floads/syseng/customer-iwf -o json
```

**Comment on customer issue:**

```bash
# Add comment to issue #123
glab issue comment 123 -R floads/syseng/customer-iwf --message "Implementation 
complete, deployed to production"

# Comment with implementation summary
glab issue comment 123 -R floads/syseng/customer-iwf \
  --message "✅ Implementation Complete

## What was done
- Feature implemented
- Tests added
- Deployed to production

## Files changed
- src/feature.py
- tests/test_feature.py
"
```

**Close customer issue:**

```bash
# Close issue #123
glab issue close 123 -R floads/syseng/customer-iwf

# Close with comment
glab issue comment 123 -R floads/syseng/customer-iwf \
  --message "✅ Implemented and deployed in production" && \
glab issue close 123 -R floads/syseng/customer-iwf
```

**View issue details:**

```bash
# View issue #123
glab issue view 123 -R floads/syseng/customer-iwf

# View with web UI
glab issue view 123 -R floads/syseng/customer-iwf --web
```

### Customer-Specific Repositories (Internal Floads Tracking)

**IWF (Infrastructure With Flow):**
- **Internal Tracking**: `https://gitlab.com/floads/syseng/customer-iwf/`
- **Public Repo**: `git.iwf.io` (customer's infrastructure repository)
- **Process**: Track work internally → deploy to customer repo → reference in 
internal issue

**MDO (Example):**
- **Internal Tracking**: `https://gitlab.com/floads/syseng/customer-mdo/`
- **Public Repo**: Customer's own repository
- **Process**: Same workflow

**DCX (Example):**
- **Internal Tracking**: `https://gitlab.com/floads/syseng/customer-dcx/`
- **Public Repo**: Customer's own repository
- **Process**: Same workflow

### Important Workflow Notes

**CRITICAL: Separate the concerns**

1. **Internal Issues** (floads gitlab - gitlab.com):
   - Track progress internally
   - Document implementation details
   - Link to PRs and commits
   - Discuss technical decisions
   - Store temporary findings

2. **Public Repositories** (customer's own repos):
   - Configuration and infrastructure code
   - Clean commit history (no "AI generated" messages)
   - Professional, customer-facing documentation
   - Client can review without seeing internal discussions

**Best Practice:**

```bash
# 1. Create issue in internal floads repo (gitlab.com)
glab issue create -R floads/syseng/customer-iwf \
  -t "K8s cluster upgrade to 1.30" \
  -d "Upgrade staging cluster first, then production..."

# 2. Do the work (create branches, make changes)
git checkout -b feature/k8s-upgrade
# ... make changes to customer's repo ...
git push -u origin feature/k8s-upgrade

# 3. Create PR in customer's repo
glab mr create -R git.iwf.io:infrastructure/flamelet-iwf \
  -t "Upgrade K8s to 1.30" \
  --source feature/k8s-upgrade \
  --target main

# 4. Update the internal floads issue with progress
glab issue comment #123 -R floads/syseng/customer-iwf \
  --message "PR created in customer repo: 
Implementation in progress..."

# 5. After merge, close the internal issue
glab issue comment #123 -R floads/syseng/customer-iwf \
  --message "✅ Merged and deployed to production
Customer can see: https://git.iwf.io/infrastructure/flamelet-iwf/commits/main"

glab issue close 123 -R floads/syseng/customer-iwf
```

### Label Conventions for Customer Issues

**Use consistent labels:**

- `feature` - New feature request
- `bug` - Bug report/fix
- `enhancement` - Improvement to existing feature
- `infrastructure` - Infrastructure/ops work
- `documentation` - Documentation updates
- `internal` - Internal floads work only
- `high-priority` - Urgent/critical
- `blocked` - Waiting on something
- `ready-for-deployment` - Ready to push to production

### Security & Privacy Reminders

- ❌ NEVER share floads gitlab URLs with customers
- ❌ NEVER add customer users to internal floads projects
- ❌ NEVER commit secrets to customer repos (use vault/secrets)
- ✅ Reference customer issues by ID in public repos: "Fixes customer-issue 
#123"
- ✅ Keep internal findings in floads gitlab only
- ✅ Share only clean, documented code in public repos

### Multiple glab Configurations

If you need to work with both gitlab.com and other instances:

```bash
# View current config
glab config list

# glab defaults to gitlab.com (correct for our floads repos)
glab config set gitlab_host gitlab.com

# Verify you're using the right instance
glab auth status
```

---

## ⚠️ CRITICAL: Upstream vs Internal Issues - Separation of Concerns

**CRITICAL RULE: Upstream (customer-facing) issues MUST NEVER contain references
to internal infrastructure, internal repositories, or internal processes.**

### Principle

**Two-tier issue tracking:**
1. **Upstream Issues** (Jira, customer-visible systems): Customer-facing 
requirements, status, acceptance criteria ONLY
2. **Internal Issues** (floads GitLab): Implementation details, technical 
decisions, internal URLs, procedures

**The Golden Rule:**
- ❌ NEVER add links to internal floads repositories in customer-facing issues
- ❌ NEVER mention internal infrastructure URLs in Jira issues
- ❌ NEVER expose internal tool references (aiops, OpenBao, internal GitLab) to 
customers
- ✅ Link FROM internal issues TO upstream issues (one-way traffic from internal
→ customer)
- ✅ Keep upstream issues clean and professional
- ✅ Use upstream issues as the source of truth for requirements
- ✅ Use internal issues as the source of truth for implementation

### Why This Matters

1. **Customer Privacy**: Customers should not see your internal infrastructure 
details
2. **Security**: Internal URLs, server names, and tools are sensitive 
information
3. **Professionalism**: Clean, focused issues are easier for customers to 
understand
4. **Audit Trail**: Separating concerns makes it clear what's customer-facing vs
internal
5. **Flexibility**: Changing internal tools won't affect customer documentation

### Correct Workflow

```
Customer Request (Upstream Jira Issue #123)
    ↓
Create Internal Issue in floads GitLab
    ↓ (links back to Jira, but never vice versa)
Internal Implementation
    ↓
Deploy to Customer Repository
    ↓
Update Upstream Issue with Results Only (no internal details)
    ↓
Close Both Issues (internal and upstream)
```

### Example: WRONG vs CORRECT

**WRONG - What NOT to do:**

```
Jira Issue IWFCLOUD2-57: SSH-Verbindung zu Gitlab

Description: Configure SSH access

Comment added:
✅ Internal tracking issue created in floads GitLab
Work is now being tracked internally in: 
  https://gitlab.com/floads/syseng/customer-iwf/-/issues/7
```

❌ This exposes internal infrastructure to the customer!

**CORRECT - What TO do:**

```
Jira Issue IWFCLOUD2-57: SSH-Verbindung zu Gitlab

Description: Configure SSH access

Status: In Progress (no mention of internal tracking)

[Work happens internally in floads GitLab only]

When complete, Jira comment shows:
✅ SSH configuration complete and deployed to production
- All nodes can authenticate with GitLab
- Documentation updated
- Ready for testing
```

✅ Upstream stays clean and professional!

### Linking Direction (One-Way)

**Allowed:**

```
Internal floads/syseng/customer-iwf Issue #7
├─ References IWFCLOUD2-57 upstream
├─ Contains implementation details
└─ Never shared with customer
```

**NOT Allowed:**

```
Jira IWFCLOUD2-57 (CUSTOMER CAN SEE THIS)
├─ NEVER references internal floads repos
├─ NEVER mentions internal URLs
└─ NEVER exposes implementation details
```

### Common Mistakes to Avoid

| ❌ WRONG | ✅ CORRECT |
|---------|-----------|
| Link internal GitLab issues in Jira | Link FROM internal TO Jira (one-way) |
| Mention aiops, floads infrastructure in Jira | Keep Jira focused on 
requirements |
| Add internal URLs to customer issues | Keep URLs out of upstream issues |
| Expose OpenBao, vault URLs to customers | Use only in internal floads issues |
| Tag internal floads team in customer Jira | Link issues to internal tracking 
separately |
| Copy internal findings into Jira comments | Summarize results only, hide 
details |

### Information That Goes Where

**UPSTREAM (Customer Jira Issues) - PUBLIC SAFE INFORMATION:**
- Feature requirements
- Acceptance criteria
- Status updates ("In Progress", "Ready", "Done")
- Summary of results (not implementation)
- Deployment status
- Links to public documentation

**INTERNAL (Floads GitLab Issues) - INTERNAL ONLY:**
- Implementation details
- Technical decisions and rationale
- Infrastructure configurations
- Internal URLs and API endpoints
- Credentials and secrets (if must be tracked)
- Performance metrics and debugging info
- Internal procedures and workarounds
- Links to infrastructure repositories

### When Closing Issues

**Upstream (Jira) - Example closing comment:**
```
✅ Implementation Complete

SSH configuration has been deployed to production.
All nodes can authenticate with GitLab successfully.
Documentation has been updated in your repository.
```

✅ Clean, results-focused, no internal details

**Internal (floads GitLab) - Example closing comment:**
```
✅ Merged and deployed

PR: https://gitlab.com/floads/syseng/customer-iwf/merge_requests/5
Commits: a1b2c3d...

Key implementation details:
- Modified /etc/ssh/sshd_config on all nodes
- Updated OpenBao secrets
- Verified connectivity via internal Monit

Deployment log: 
```

✅ Detailed, internal-focused, full context

### Enforcement

**Before updating Jira issues:**
- [ ] Is this customer-visible?
- [ ] Does it contain internal URLs or infrastructure details?
- [ ] Would exposing this be a security risk?
- [ ] Is this information relevant to the customer's needs?

If any answer is NO, add the information to the internal floads GitLab issue 
instead.

### One-Way Linking Pattern (Required)

**INTERNAL issues MUST link to UPSTREAM issues:**

Every internal floads GitLab issue must contain a reference to the upstream 
customer issue it implements:

```bash
# Internal Issue: floads/syseng/customer-iwf #7

## Upstream Reference
Related upstream issue: **IWFCLOUD2-57** (SSH-Verbindung zu Gitlab)
Link: https://iwf-web-solutions.atlassian.net/browse/IWFCLOUD2-57

This internal issue tracks implementation details for the customer requirement.
```

✅ **Required in internal issues:**
- Upstream issue key (IWFCLOUD2-57)
- Upstream issue title
- Direct link to upstream issue
- Purpose statement connecting the two

**UPSTREAM issues MUST NOT link to INTERNAL issues:**

```bash
# Upstream Issue: IWFCLOUD2-57

Status: In Progress
Acceptance Criteria: [...]
[NO MENTION OF INTERNAL FLOADS REPOS OR PROCEDURES]
```

❌ **NEVER in upstream issues:**
- Internal GitLab URLs
- floads repository references
- Internal process descriptions
- Floads team information
- Internal infrastructure details

### Implementation Example

**Step 1: Create internal issue WITH upstream reference**
```bash
glab issue create -R floads/syseng/customer-iwf \
  -t "SSH ports configuration for GitLab access (IWFCLOUD2-57)" \
  -d "## Upstream Reference
Related upstream issue: **IWFCLOUD2-57** (SSH-Verbindung zu Gitlab)
Link: https://iwf-web-solutions.atlassian.net/browse/IWFCLOUD2-57
..."
```

**Step 2: Work internally on implementation**
- All technical details stay in internal floads issue
- No mention of this work in upstream Jira

**Step 3: When complete, update upstream with RESULTS ONLY**
```
Comment on IWFCLOUD2-57:
✅ SSH configuration complete
- All nodes configured
- Deployed to production
- Ready for testing
[NO mention of internal tracking]
```

**Step 3: Close both issues**
- Internal issue closed: "Merged and deployed to customer repo"
- Upstream issue closed: "Completed and ready"
---

## glab Host Override (GITLAB_HOST)

When `glab` needs to target a non-default GitLab host, set `GITLAB_HOST` for the
command.

Example:
```bash
GITLAB_HOST=gitlab.com glab issue note 9 -R floads/syseng/customer-iwf -m "..."
```

Use this when `glab` is configured for git.iwf.io but you need to act on 
gitlab.com (or any other host).
---

## glab Markdown Notes (safe formatting)

When posting GitLab issue comments that include backticks or Markdown, avoid shell interpolation by using a file and `glab api`:

```bash
cat <<'MSG' > /tmp/note.md
## Next steps
- Review MR 36: https://git.iwf.io/infrastructure/flamelet-iwf/-/merge_requests/36
- Apply to prod via Ansible (`copy` then `pf`) on `iwf-prod-fw-01/02`
- Verify admin SSH on `22022` and GitLab SSH on port `22`
- Merge MR once verified
MSG

# Use explicit host when needed
GITLAB_HOST=gitlab.com glab api \
  projects/<project-id>/issues/<iid>/notes \
  -F body=@/tmp/note.md
```

This preserves Markdown formatting and avoids backticks being executed by the shell.

---

## Current Issue Context
<!-- issue-context:start -->

_No issue context populated yet. Use the Populate AGENTS.override.md button to generate it._

<!-- issue-context:end -->
