@AGENTS.md

## Claude-specific Instructions for Issue Management

### CRITICAL: Always Use aiops CLI for Issue Operations

You MUST use the `aiops` CLI for all issue management. Never attempt to call GitHub/GitLab/Jira APIs directly.

### Quick Start

The `aiops` CLI is pre-installed at `./.venv/bin/aiops` and pre-configured with your API credentials.

```bash
# Sync issues before starting work
aiops issues sync --project <project-name>

# Get issue details
aiops issues get <issue-id>

# Add comments
aiops issues comment <issue-id> "Your update here"

# Close when done
aiops issues close <issue-id>
```

### Required Workflow for Every Issue

1. **Start**: Sync issues → `aiops issues sync --project <project>`
2. **Read**: Get full context → `aiops issues get <issue-id> --output json`
3. **Update**: Comment on progress → `aiops issues comment <issue-id> "Starting work..."`
4. **Complete**: Document changes → `aiops issues comment <issue-id> "Completed: ..."`
5. **Close**: Mark as done → `aiops issues close <issue-id>`

### Important Notes

- **Issue IDs**: Use the database ID from `aiops issues list`, NOT the external issue number
- **JSON output**: Use `--output json` when you need to parse issue data programmatically
- **Sync first**: Always run `aiops issues sync --project <project>` before starting work
- **Comment often**: Add updates at major milestones - stakeholders appreciate visibility
- **Be detailed**: Include file paths, specific changes, and verification steps in comments
- **Create follow-ups**: If you find additional work, create new issues rather than expanding scope

### Full Documentation

See the "AI Agent Issue Management Workflow" section in `AGENTS.md` for:
- Complete workflow examples
- Best practices for AI agents
- Finding integration IDs for creating issues
- Error handling and troubleshooting

### Example: Working on Issue #502

```bash
# 1. Sync to get latest
aiops issues sync --project aiops

# 2. Read the issue
aiops issues get 502 --output json

# 3. Start work comment
aiops issues comment 502 "Starting work on package preparation"

# 4. ... do the work ...

# 5. Completion comment
aiops issues comment 502 "Completed! Updated setup.py, added LICENSE, created docs"

# 6. Close it
aiops issues close 502
```
