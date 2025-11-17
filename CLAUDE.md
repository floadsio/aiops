@AGENTS.md

## Claude-specific reminder

- Use the pre-installed `./.venv/bin/aiops` CLI in this workspace to sync issues, read comments, and post updates; the command is configured per user so you can call it without extra setup.
- To refresh Jira data start with `aiops issues sync --project example-project` (or the tenant/project you work on), then inspect `aiops issues get <issue-id> --output json` to view comments and threads.
- Leave comments with `aiops issues comment <issue-id> "Your note"` and close the loop with `aiops issues close <issue-id>` when done. Refer to `AGENTS.md` for the full issue flow and additional git/tenant commands.
