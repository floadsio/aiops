# aiops Deployment Guide

This directory contains production deployment files for the aiops Flask application.

## Overview

The production deployment uses:
- **Gunicorn** as the production WSGI server (instead of Flask's development server)
- **Systemd** for process management and automatic restarts
- **Security hardening** via systemd directives

## Files

- `aiops.service` - Systemd service template (configured for user `syseng`)
- `install-service.sh` - Installation script to deploy the service with custom settings

## Quick Start

### 1. Install Dependencies

Ensure gunicorn is installed in your virtual environment:

```bash
cd /home/syseng/aiops
make sync  # or: uv pip sync requirements.txt
```

### 2. Install the Service

#### Option A: Use the installation script (recommended)

```bash
cd /home/syseng/aiops/deployment
sudo ./install-service.sh syseng /home/syseng/aiops
```

The script will:
- Verify the user and installation directory exist
- Check that the virtual environment is set up
- Create the logs directory if needed
- Generate and install the service file
- Enable the service

#### Option B: Manual installation

```bash
# Copy the service file
sudo cp aiops.service /etc/systemd/system/

# Edit paths if needed (only if not using default syseng user)
sudo nano /etc/systemd/system/aiops.service

# Reload systemd
sudo systemctl daemon-reload

# Enable the service
sudo systemctl enable aiops.service
```

### 3. Start the Service

```bash
sudo systemctl start aiops
```

### 4. Verify It's Running

```bash
# Check status
sudo systemctl status aiops

# View logs
sudo journalctl -u aiops -f
# or
tail -f /home/syseng/aiops/logs/aiops.log
```

## Customization

### Changing the User/Installation Directory

If you're not using the default `syseng` user or `/home/syseng/aiops` directory:

```bash
# Use the installation script with custom parameters
sudo ./install-service.sh <username> <install_dir>

# Example:
sudo ./install-service.sh webadmin /opt/aiops
```

### Adjusting Worker Count

Edit the service file to change the number of gunicorn workers:

```bash
sudo nano /etc/systemd/system/aiops.service

# Find this line:
#   --workers 4 \

# Change to match your CPU cores (recommended: 2-4 x num_cores)
#   --workers 8 \

# Reload and restart
sudo systemctl daemon-reload
sudo systemctl restart aiops
```

### Changing the Port

Edit the service file and change the bind address:

```bash
sudo nano /etc/systemd/system/aiops.service

# Find this line:
#   --bind 0.0.0.0:8060 \

# Change to your desired port:
#   --bind 0.0.0.0:8080 \

# Reload and restart
sudo systemctl daemon-reload
sudo systemctl restart aiops
```

### Request Timeout

For deployments with long-running operations (large git repos, slow AI responses), increase the timeout:

```bash
# Edit service file
sudo nano /etc/systemd/system/aiops.service

# Find this line:
#   --timeout 30 \

# Increase to 60 or 120 seconds:
#   --timeout 60 \

# Reload and restart
sudo systemctl daemon-reload
sudo systemctl restart aiops
```

## Management Commands

```bash
# Start the service
sudo systemctl start aiops

# Stop the service
sudo systemctl stop aiops

# Restart the service
sudo systemctl restart aiops

# Check status
sudo systemctl status aiops

# Enable auto-start on boot
sudo systemctl enable aiops

# Disable auto-start on boot
sudo systemctl disable aiops

# View logs (real-time)
sudo journalctl -u aiops -f

# View logs (last 100 lines)
sudo journalctl -u aiops -n 100

# View logs from file
tail -f /home/syseng/aiops/logs/aiops.log
```

## Updating the Application

When you deploy new code:

```bash
# Pull latest changes
cd /home/syseng/aiops
git pull

# Update dependencies if needed
make sync

# Run database migrations
.venv/bin/flask db upgrade

# Restart the service
sudo systemctl restart aiops
```

## Security Considerations

The systemd service includes security hardening:

- **NoNewPrivileges**: Prevents privilege escalation
- **PrivateTmp**: Isolates /tmp directory
- **ProtectSystem=strict**: Makes most of the filesystem read-only
- **ProtectHome=read-only**: Protects home directories
- **ReadWritePaths**: Explicitly allows writes to instance/ and logs/

These settings improve security but may need adjustment based on your deployment requirements.

### Required Permissions

The aiops user needs:

1. **Read/write access** to:
   - `instance/` - Database, uploaded keys, configuration
   - `logs/` - Log files

2. **Read-only access** to:
   - Application code
   - Virtual environment

3. **Sudo access** for launching tmux sessions as other users (see AGENTS.md)

## Troubleshooting

### Service won't start

```bash
# Check the service status for error messages
sudo systemctl status aiops

# View detailed logs
sudo journalctl -u aiops -n 50 --no-pager

# Check if port is already in use
sudo lsof -i :8060
```

### Database errors

```bash
# Run migrations
cd /home/syseng/aiops
.venv/bin/flask db upgrade

# Check database permissions
ls -la instance/app.db
```

### Permission errors

```bash
# Ensure logs directory exists and has correct ownership
sudo mkdir -p /home/syseng/aiops/logs
sudo chown syseng:syseng /home/syseng/aiops/logs

# Ensure instance directory has correct ownership
sudo chown -R syseng:syseng /home/syseng/aiops/instance
```

### Gunicorn not found

```bash
# Reinstall dependencies
cd /home/syseng/aiops
make sync

# Verify gunicorn is installed
.venv/bin/gunicorn --version
```

## Migrating from Flask Development Server

If you're currently running with `flask run` or `make start`:

1. Stop the old process:
   ```bash
   make stop
   # or
   pkill -f "flask.*run"
   ```

2. Install the systemd service (see Quick Start above)

3. Start the new service:
   ```bash
   sudo systemctl start aiops
   ```

4. Update any automation that uses `make start` to use `systemctl start aiops` instead

## Performance Tuning

### Worker Count

The default configuration uses 4 workers. Adjust based on:
- **CPU cores**: 2-4 workers per core
- **Memory**: Each worker uses ~100-200MB
- **Workload**: More workers for I/O-bound operations (git, API calls)

```bash
# For a 4-core system:
--workers 8  # Conservative
--workers 16 # Aggressive
```

### Timeout Settings

The default timeout is 30 seconds. Increase for:
- Large git operations
- Slow external API calls (Jira, GitHub, GitLab)
- Long-running AI sessions

```bash
--timeout 60  # For most deployments
--timeout 120 # For large repos or slow networks
```

## Development vs Production

| Feature | Development (`make start-dev`) | Production (`systemd`) |
|---------|-------------------------------|------------------------|
| Server | Flask development server | Gunicorn WSGI server |
| Workers | Single-threaded | Multi-process (4+) |
| Auto-reload | Yes | No |
| Security | Minimal | Hardened |
| Logging | Console | File + journald |
| Process management | Manual | Systemd |

Use `make start-dev` for development and the systemd service for production deployments.

## Claude Code Auto-Update Timer

The system includes a systemd timer that automatically updates Claude Code CLI daily using the `aiops system update-ai-tool` command.

### Installation

From the deployment directory:

```bash
cd /home/syseng/aiops/deployment
sudo ./install-claude-update-timer.sh
```

### Management

**Check timer status:**
```bash
sudo systemctl status aiops-claude-update.timer
sudo systemctl list-timers aiops-claude-update.timer
```

**View update logs:**
```bash
sudo journalctl -u aiops-claude-update -f
sudo journalctl -u aiops-claude-update --since today
```

**Trigger manual update:**
```bash
sudo systemctl start aiops-claude-update.service
```

**Disable auto-updates:**
```bash
sudo systemctl stop aiops-claude-update.timer
sudo systemctl disable aiops-claude-update.timer
```

### Configuration

The timer runs daily at 2 AM. To change the schedule, edit:
```
/etc/systemd/system/aiops-claude-update.timer
```

Then reload systemd:
```bash
sudo systemctl daemon-reload
sudo systemctl restart aiops-claude-update.timer
```

### Disabling Claude Code's Built-in Auto-Update

To prevent "Auto-update failed" error messages in Claude Code, users can disable its built-in auto-updater by setting an environment variable in their shell profile:

```bash
# Add to ~/.zshrc or ~/.bashrc
export DISABLE_AUTOUPDATER=1
```

Or add to Claude Code settings file (`~/.claude/settings.json`):

```json
{
  "env": {
    "DISABLE_AUTOUPDATER": "1"
  }
}
```
