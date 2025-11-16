# AIops CLI

A powerful command-line interface for interacting with the AIops REST API.

## Installation

```bash
pip install aiops-cli
```

Or install from source:

```bash
cd cli
pip install -e .
```

## Quick Start

1. **Configure your AIops server and API key:**

```bash
aiops config set url http://localhost:5000
aiops config set api_key aiops_your_api_key_here
```

2. **Test connection:**

```bash
aiops auth whoami
```

3. **List issues:**

```bash
aiops issues list
```

## Configuration

The CLI stores configuration in `~/.aiops/config.yaml`:

```yaml
url: http://localhost:5000
api_key: aiops_your_key_here
output_format: table  # or json, yaml
```

You can also set configuration via environment variables:
- `AIOPS_URL` - API base URL
- `AIOPS_API_KEY` - API key for authentication

## Commands

### Authentication

```bash
# Show current user
aiops auth whoami

# List your API keys
aiops auth keys list

# Create a new API key
aiops auth keys create --name "My Key" --scopes read write

# Revoke an API key
aiops auth keys delete <key-id>
```

### Issues

```bash
# List all issues
aiops issues list

# Filter issues
aiops issues list --status open --provider github --project 1

# Get issue details
aiops issues get 42

# Create an issue
aiops issues create --project 1 --integration 1 \\
  --title "Bug fix" --description "Fix authentication bug"

# Update issue
aiops issues update 42 --title "New title"

# Add comment
aiops issues comment 42 "Working on this"

# Close issue
aiops issues close 42

# Assign issue
aiops issues assign 42 --user 1
```

### Projects

```bash
# List projects
aiops projects list

# Get project details
aiops projects get 1

# Create project
aiops projects create --name "My Project" \\
  --tenant 1 --repo-url git@github.com:org/repo.git

# Get project status
aiops projects status 1
```

### Git Operations

```bash
# Get git status
aiops git status 1

# Pull changes
aiops git pull 1

# Push changes
aiops git push 1

# List branches
aiops git branches 1

# Create branch
aiops git branch create 1 feature-xyz

# Checkout branch
aiops git checkout 1 main

# Commit changes
aiops git commit 1 "Fix bug" --files app/auth.py

# List files
aiops git files 1

# Read file
aiops git cat 1 app/models.py
```

### Workflows (AI Agent Commands)

```bash
# Claim an issue for work
aiops workflow claim 42

# Update progress
aiops workflow progress 42 "in progress" --comment "Working on it"

# Submit changes
aiops workflow submit 42 --project 1 \\
  --message "Fix bug" --comment "Bug fixed"

# Request approval
aiops workflow approve 42 --message "Ready for review"

# Complete issue
aiops workflow complete 42 --summary "Bug fixed successfully"
```

### Tenants

```bash
# List tenants
aiops tenants list

# Get tenant details
aiops tenants get 1

# Create tenant
aiops tenants create --name "My Tenant" --description "Description"
```

### Configuration

```bash
# Show current configuration
aiops config show

# Set configuration values
aiops config set url http://localhost:5000
aiops config set api_key aiops_your_key

# Get configuration value
aiops config get url
```

## Output Formats

The CLI supports multiple output formats:

```bash
# Table format (default)
aiops issues list

# JSON format
aiops issues list --output json

# YAML format
aiops issues list --output yaml

# Set default format
aiops config set output_format json
```

## Examples

### Automated Workflow

```bash
#!/bin/bash
# Claim issue, fix bug, and submit

ISSUE_ID=42
PROJECT_ID=1

# Claim the issue
aiops workflow claim $ISSUE_ID

# Update status
aiops workflow progress $ISSUE_ID "in progress" \\
  --comment "Starting work on authentication bug"

# Make your code changes here...
# ...

# Commit changes
aiops git commit $PROJECT_ID "Fix authentication bug" \\
  --files app/auth.py app/models.py

# Submit changes
aiops workflow submit $ISSUE_ID --project $PROJECT_ID \\
  --message "Fix authentication bug" \\
  --comment "Fixed by updating token validation logic"

# Request review
aiops workflow approve $ISSUE_ID \\
  --message "Changes ready for review. All tests passing."

# After approval, complete the issue
aiops workflow complete $ISSUE_ID \\
  --summary "Authentication bug fixed and deployed"
```

### Batch Operations

```bash
# List all open issues and process them
aiops issues list --status open --output json | \\
  jq -r '.[].id' | \\
  while read issue_id; do
    echo "Processing issue $issue_id"
    aiops issues get $issue_id
  done
```

## Development

```bash
# Install in development mode
pip install -e ".[dev]"

# Run tests
pytest

# Format code
black aiops_cli/
ruff check --fix aiops_cli/
```

## License

MIT License - see LICENSE file for details.
