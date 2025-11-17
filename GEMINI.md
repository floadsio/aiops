@AGENTS.md

## Gemini-specific reminder

- Rely on the already-configured `./.venv/bin/aiops` CLI in this workspace to keep Jira issues in sync and comment directly from the terminal.
- Start with `aiops issues sync --project example-project`, explore the latest comments via `aiops issues get <issue-id> --output json`, and reply with `aiops issues comment <issue-id> "message"`.
- Close work items as needed through `aiops issues close <issue-id>` and consult `AGENTS.md` whenever you need command references for git, workflows, or project administration.
