# Sudo Configuration for aiops

This document explains how to configure sudo permissions for aiops to enable per-user workspace operations.

## Overview

aiops requires sudo access to:
- Execute git operations in user-owned workspaces
- Create and manage directories as different Linux users
- Check workspace status across restrictive file permissions
- Initialize new user workspaces

The Flask application runs as the `syseng` user but needs to execute commands as individual Linux users (e.g., `linuxuser1`, `linuxuser2`).

## Requirements

### 1. Passwordless Sudo Configuration

The Flask app user (`syseng`) needs passwordless sudo access. Create a sudoers file:

```bash
sudo visudo -f /etc/sudoers.d/aiops
```

Add one of the following configurations:

#### Option A: Full Access (Development/Trusted Environments)

```bash
# Allow syseng to run any command as any user without password
syseng ALL=(ALL) NOPASSWD: ALL
```

**Pros:** Simple, works for all operations
**Cons:** Grants broad sudo access
**Use for:** Development, single-user environments, trusted team setups

#### Option B: Restricted Commands (Production)

```bash
# Allow syseng to run specific commands as specific users
syseng ALL=(linuxuser1,linuxuser2) NOPASSWD: /usr/bin/test, /bin/mkdir, /usr/bin/git, /bin/rm
syseng ALL=(ALL) NOPASSWD: /bin/chmod, /bin/chgrp, /usr/bin/chown
```

**Pros:** Minimal privilege escalation
**Cons:** Must update when adding users or commands
**Use for:** Production environments with security requirements

### 2. File Permissions

Set correct ownership on sudoers file:

```bash
sudo chown root:root /etc/sudoers.d/aiops
sudo chmod 0440 /etc/sudoers.d/aiops
```

### 3. Verify Configuration

Test that sudo works without password:

```bash
# As syseng user
sudo -n -u linuxuser1 test -e /home/linuxuser1
echo $?  # Should be 0 (success)
```

Use the aiops CLI test command:

```bash
.venv/bin/flask test-sudo --user-email user@example.com
```

## Git Safe Directory Configuration

When the Flask app reads git repositories owned by other users, git's security checks may block access with "dubious ownership" errors.

### Solution 1: Wildcard Safe Directory (Recommended for Development)

```bash
# As syseng user
sudo -u syseng git config --global --add safe.directory '*'
```

This allows git to access any repository regardless of ownership.

### Solution 2: Explicit Safe Directories (Production)

```bash
# As syseng user
sudo -u syseng git config --global --add safe.directory '/home/linuxuser1/workspace/example/aiops'
sudo -u syseng git config --global --add safe.directory '/home/linuxuser2/workspace/example/aiops'
```

Add each user's workspace explicitly.

### Verify Git Configuration

```bash
git config --global --get-all safe.directory
```

## Workspace Directory Permissions

For the Flask app to check workspace status, parent directories need execute (`o+x`) permissions:

```bash
# Allow directory traversal for /home/username
chmod o+rx /home/linuxuser1
chmod o+rx /home/linuxuser1/workspace

# Workspace directories can remain user-owned
ls -la /home/linuxuser1/workspace/example/aiops
# drwxrwxr-x 10 linuxuser1 linuxuser1 4096 Jan 01 00:00 aiops
```

**Important:** The `o+x` permission allows traversal but does NOT expose file contents. Files remain protected by their own permissions.

## Security Considerations

### What Sudo Access Allows

With the recommended configuration, `syseng` can:
- ✅ Run git commands in user workspaces
- ✅ Create directories in user home directories
- ✅ Check if paths exist
- ✅ Manage file permissions on shared resources

### What Sudo Access Does NOT Allow

- ❌ Read or modify files outside permitted operations
- ❌ Impersonate users for authentication
- ❌ Access user passwords or credentials
- ❌ Bypass application-level access controls

### Best Practices

1. **Use Restricted Commands in Production:** Limit sudo to specific commands needed
2. **Audit Sudo Logs:** Monitor `/var/log/auth.log` for sudo usage
3. **Regular Reviews:** Periodically review sudoers configuration
4. **Least Privilege:** Only grant access to users who need workspace operations
5. **Test Thoroughly:** Use `flask test-sudo` to verify configuration

## Troubleshooting

### Error: "sudo: no tty present and no askpass program specified"

**Cause:** Sudo is requesting a password but can't prompt (no TTY)

**Solution:** Ensure NOPASSWD is set in sudoers configuration

```bash
sudo visudo -f /etc/sudoers.d/aiops
# Verify NOPASSWD is present
```

### Error: "dubious ownership in repository"

**Cause:** Git security check blocking access to repository owned by different user

**Solution:** Add repository to git safe directories

```bash
sudo -u syseng git config --global --add safe.directory '/path/to/repo'
```

### Error: "Permission denied" when checking workspace

**Cause:** Parent directory lacks execute permission

**Solution:** Add o+x permission to parent directories

```bash
chmod o+rx /home/username
chmod o+rx /home/username/workspace
```

### Workspace Status Shows "Status unavailable"

**Causes and Solutions:**

1. **Missing sudo configuration**
   ```bash
   .venv/bin/flask test-sudo --user-email user@example.com
   ```

2. **Missing directory permissions**
   ```bash
   chmod o+rx /home/username
   chmod o+rx /home/username/workspace
   ```

3. **Git safe directory not configured**
   ```bash
   sudo -u syseng git config --global --add safe.directory '*'
   ```

## Testing Your Configuration

### 1. Test Basic Sudo Access

```bash
# As syseng user
sudo -n -u linuxuser1 whoami
# Should output: linuxuser1
```

### 2. Test Workspace Operations

```bash
# As syseng user
sudo -n -u linuxuser1 test -e /home/linuxuser1/workspace/example/aiops
echo $?  # Should be 0 if workspace exists
```

### 3. Test Git Access

```bash
# As syseng user
sudo -n -u linuxuser1 git -C /home/linuxuser1/workspace/example/aiops status
# Should show git status without errors
```

### 4. Use aiops CLI Test Command

```bash
# Run comprehensive test
.venv/bin/flask test-sudo --user-email user@example.com
```

This command checks:
- ✓ Passwordless sudo access
- ✓ Ability to run commands as target user
- ✓ Directory permissions
- ✓ Git safe directory configuration
- ✓ Workspace accessibility

## Example: Complete Setup for New User

```bash
## Example: Complete setup for a new Linux user

# 1. Create Linux user
sudo useradd -m -s /bin/bash linuxuser2
sudo usermod -aG syseng linuxuser2

# 2. Add to sudoers (if using restricted mode)
sudo visudo -f /etc/sudoers.d/aiops
# Add: syseng ALL=(linuxuser2) NOPASSWD: /usr/bin/test, /bin/mkdir, /usr/bin/git, /bin/rm

# 3. Set directory permissions
sudo chmod o+rx /home/linuxuser2
sudo -u linuxuser2 mkdir -p /home/linuxuser2/workspace
sudo chmod o+rx /home/linuxuser2/workspace

# 4. Add git safe directory
sudo -u syseng git config --global --add safe.directory '/home/linuxuser2/workspace/*'

# 5. Test configuration
.venv/bin/flask test-sudo --user-email other@example.com

# 6. Initialize workspace
.venv/bin/flask init-workspace --user-email other@example.com --project-id 1
```

## Reference: sudo_service.py Functions

The `app/services/sudo_service.py` module provides these functions:

- `run_as_user(username, command, *, timeout, env, check, capture_output)` - Execute any command
- `test_path(username, path)` - Check if path exists
- `mkdir(username, path, *, parents, timeout)` - Create directories
- `chown(path, owner, group)` - Change ownership
- `chmod(path, mode)` - Change permissions
- `chgrp(path, group)` - Change group
- `rm_rf(username, path)` - Recursive removal

All functions raise `SudoError` on failure and respect the `-n` (non-interactive) flag.

## Support

For issues or questions:
1. Run `flask test-sudo --user-email <your-email>` to diagnose
2. Check `/var/log/auth.log` for sudo errors
3. Review Flask logs in `/tmp/aiops.log`
4. Consult AGENTS.md for implementation details
