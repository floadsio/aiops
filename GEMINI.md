@AGENTS.md

## Gemini-Specific Instructions

### CRITICAL: Use aiops CLI for All Operations

The `aiops` CLI is **pre-installed** at `./.venv/bin/aiops` and **pre-configured** with your API credentials.
You MUST use it for all issue management, git operations, and project management. Never call external APIs directly.

### Quick Reference

```bash
# Issue workflow
aiops issues sync --project <project>
aiops issues get <id> --output json
aiops issues comment <id> "Starting work..."
# ... make changes ...
aiops issues close <id>

# Git operations
aiops git status <project>
aiops git commit <project> "Fix bug" --files "app/auth.py"
aiops git push <project>
```

### Important Notes

- **Always read AGENTS files first**: Before starting any task, read both `AGENTS.md` and `AGENTS.override.md` (if present) to understand the current issue context and project guidelines
- **Issue IDs**: Use database ID from `aiops issues list`, NOT external issue number
- **Never commit AGENTS.override.md** to version control - it's auto-generated
- **Work in your workspace**: `/home/{username}/workspace/{tenant_slug}/{project}/`
- **Never modify `/home/syseng/aiops`** - that's the running Flask instance

See full CLI documentation in `AGENTS.md`.
