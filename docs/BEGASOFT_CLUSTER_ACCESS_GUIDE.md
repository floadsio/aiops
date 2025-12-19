# Begasoft Test Cluster Access Guide

**Cluster:** lernetz-test-begasoft-k8s
**API Server:** https://193.5.124.83:6443
**Authentication:** OIDC via Keycloak (Begasoft SSO)
**User:** mturko
**Password:** 8G26laIySSqzfD

---

## Quick Access Method (RECOMMENDED)

Use Python with curl to get token and execute kubectl commands. This is the most reliable method.

### Basic Template

```python
import subprocess
import json

# Get OIDC token
result = subprocess.run([
    'curl', '-s', '-X', 'POST',
    '-H', 'Content-Type: application/x-www-form-urlencoded',
    '-d', 'grant_type=password&client_id=kubernetes&username=mturko&password=8G26laIySSqzfD',
    'https://auth.sso.paas.begasoft.ch/realms/b82ud9/protocol/openid-connect/token'
], capture_output=True, text=True, timeout=10)

data = json.loads(result.stdout)
token = data['access_token']

# Execute kubectl command
result = subprocess.run([
    'kubectl', '--token=' + token, '--server=https://193.5.124.83:6443',
    '--insecure-skip-tls-verify', 'get', 'nodes'
], capture_output=True, text=True, timeout=30)

print(result.stdout)
```

### Why This Works

- ✅ Gets fresh OIDC token every time
- ✅ Doesn't depend on kubeconfig or kubectl-oidc-login
- ✅ Works reliably even when OIDC plugin is slow
- ✅ Timeout handling prevents hanging
- ✅ JSON parsing ensures clean token extraction

---

## Common Operations

### Get Cluster Status

```python
import subprocess
import json

# Token function (reusable)
def get_token():
    result = subprocess.run([
        'curl', '-s', '-X', 'POST',
        '-H', 'Content-Type: application/x-www-form-urlencoded',
        '-d', 'grant_type=password&client_id=kubernetes&username=mturko&password=8G26laIySSqzfD',
        'https://auth.sso.paas.begasoft.ch/realms/b82ud9/protocol/openid-connect/token'
    ], capture_output=True, text=True, timeout=10)
    return json.loads(result.stdout)['access_token']

def kubectl_cmd(token, cmd):
    result = subprocess.run([
        'kubectl', '--token=' + token, '--server=https://193.5.124.83:6443',
        '--insecure-skip-tls-verify'
    ] + cmd, capture_output=True, text=True, timeout=30)
    return result.stdout

# Usage
token = get_token()

# Get nodes
print(kubectl_cmd(token, ['get', 'nodes']))

# Get backups
print(kubectl_cmd(token, ['get', 'backups', '-n', 'velero']))

# Get pods in namespace
print(kubectl_cmd(token, ['get', 'pods', '-n', 'velero']))
```

### Delete Resources (Cleanup)

```python
import subprocess
import json

def get_token():
    result = subprocess.run([
        'curl', '-s', '-X', 'POST',
        '-H', 'Content-Type: application/x-www-form-urlencoded',
        '-d', 'grant_type=password&client_id=kubernetes&username=mturko&password=8G26laIySSqzfD',
        'https://auth.sso.paas.begasoft.ch/realms/b82ud9/protocol/openid-connect/token'
    ], capture_output=True, text=True, timeout=10)
    return json.loads(result.stdout)['access_token']

def kubectl_cmd(token, cmd):
    result = subprocess.run([
        'kubectl', '--token=' + token, '--server=https://193.5.124.83:6443',
        '--insecure-skip-tls-verify'
    ] + cmd, capture_output=True, text=True, timeout=30)
    return result.stdout

token = get_token()

# Delete all backups
print("=== Deleting backups ===")
print(kubectl_cmd(token, ['delete', 'backups', '-n', 'velero', '--all', '--grace-period=0', '--force']))

# Delete all DataUploads
print("\n=== Deleting DataUploads ===")
print(kubectl_cmd(token, ['delete', 'datauploads', '-n', 'velero', '--all', '--grace-period=0', '--force']))

# Delete succeeded pods
print("\n=== Deleting succeeded pods ===")
print(kubectl_cmd(token, ['delete', 'pods', '-n', 'velero', '--field-selector=status.phase=Succeeded']))

# Verify
print("\n=== Verification ===")
print(kubectl_cmd(token, ['get', 'backups,datauploads', '-n', 'velero']))
```

---

## Environment Details

### OIDC Configuration

- **Issuer:** https://auth.sso.paas.begasoft.ch/realms/b82ud9
- **Client ID:** kubernetes
- **Grant Type:** password
- **Scope:** profile email

### Kubernetes API

- **Server:** https://193.5.124.83:6443
- **TLS Verify:** Disabled (--insecure-skip-tls-verify)
- **Token Header:** Authorization: Bearer {token}

### Velero Namespace

- **Namespace:** velero
- **Deployment:** velero (main Velero server)
- **DaemonSet:** node-agent (per-node agent for CSI snapshots)
- **Custom Resources:** Backup, DataUpload, VolumeSnapshot

---

## Troubleshooting

### Issue: Token Expired

**Error:** `invalid_token` or similar JWT errors

**Solution:** Get a fresh token using the get_token() function

```python
token = get_token()  # Always get fresh token
```

### Issue: Connection Timeout

**Error:** `dial tcp: i/o timeout` or `connection refused`

**Solution:** Increase timeout or retry

```python
result = subprocess.run(cmd, timeout=60)  # Increase timeout to 60 seconds
```

### Issue: DNS Resolution Failure

**Error:** `lookup auth.sso.paas.begasoft.ch: no such host`

**Cause:** Network connectivity issue from Claude Code environment

**Solution:** Contact infrastructure team or wait for connectivity to be restored

### Issue: kubectl Not Found

**Solution:** kubectl should be in PATH. If not, use full path:

```python
result = subprocess.run([
    '/usr/bin/kubectl',  # Full path
    '--token=' + token,
    ...
], ...)
```

---

## Testing Connectivity

### Verify You Can Access Cluster

```bash
python3 << 'EOF'
import subprocess
import json

# Get token
result = subprocess.run([
    'curl', '-s', '-X', 'POST',
    '-H', 'Content-Type: application/x-www-form-urlencoded',
    '-d', 'grant_type=password&client_id=kubernetes&username=mturko&password=8G26laIySSqzfD',
    'https://auth.sso.paas.begasoft.ch/realms/b82ud9/protocol/openid-connect/token'
], capture_output=True, text=True, timeout=10)

try:
    data = json.loads(result.stdout)
    token = data['access_token']
    print("✅ Token obtained successfully")

    # Try to get nodes
    result = subprocess.run([
        'kubectl', '--token=' + token, '--server=https://193.5.124.83:6443',
        '--insecure-skip-tls-verify', 'get', 'nodes'
    ], capture_output=True, text=True, timeout=30)

    if result.returncode == 0:
        print("✅ Cluster access verified")
        print("\nNodes:")
        print(result.stdout)
    else:
        print("❌ Cluster access failed")
        print(result.stderr)
except Exception as e:
    print(f"❌ Error: {e}")
EOF
```

---

## Common Commands Reference

### Monitor Velero

```python
token = get_token()

# Get all backups
kubectl_cmd(token, ['get', 'backups', '-n', 'velero'])

# Get backup details
kubectl_cmd(token, ['describe', 'backup', '<BACKUP_NAME>', '-n', 'velero'])

# Get DataUploads
kubectl_cmd(token, ['get', 'datauploads', '-n', 'velero', '-l', 'velero.io/backup-name=<BACKUP_NAME>'])

# Get Velero logs
kubectl_cmd(token, ['logs', '-n', 'velero', 'deployment/velero', '--tail=100'])

# Get Velero pod status
kubectl_cmd(token, ['get', 'pods', '-n', 'velero', '-l', 'app.kubernetes.io/name=velero'])
```

### Manage Resources

```python
token = get_token()

# Apply YAML
kubectl_cmd(token, ['apply', '-f', '/path/to/file.yaml'])

# Delete resource
kubectl_cmd(token, ['delete', 'backup', '<NAME>', '-n', 'velero'])

# Patch resource
kubectl_cmd(token, ['patch', 'backup', '<NAME>', '-n', 'velero',
           '-p', '{"metadata":{"labels":{"velero.io/abort-request":"true"}}}', '--type', 'merge'])
```

---

## Important Notes

1. **Credentials:** Keep credentials safe - don't commit to git or share
2. **Timeouts:** Cluster operations may be slow; use sufficient timeouts (30-60 seconds)
3. **Retries:** Network issues are common; implement retry logic for critical operations
4. **Error Handling:** Always check result.returncode and result.stderr
5. **Token Reuse:** Get fresh token for each session or before it expires (usually 5 minutes)

---

## Quick Copy-Paste: Clean Velero Namespace

```python
import subprocess
import json

def get_token():
    result = subprocess.run([
        'curl', '-s', '-X', 'POST',
        '-H', 'Content-Type: application/x-www-form-urlencoded',
        '-d', 'grant_type=password&client_id=kubernetes&username=mturko&password=8G26laIySSqzfD',
        'https://auth.sso.paas.begasoft.ch/realms/b82ud9/protocol/openid-connect/token'
    ], capture_output=True, text=True, timeout=10)
    return json.loads(result.stdout)['access_token']

def kubectl_cmd(token, cmd):
    result = subprocess.run([
        'kubectl', '--token=' + token, '--server=https://193.5.124.83:6443',
        '--insecure-skip-tls-verify'
    ] + cmd, capture_output=True, text=True, timeout=30)
    return result.stdout

token = get_token()

print("=== Deleting all backups ===")
print(kubectl_cmd(token, ['delete', 'backups', '-n', 'velero', '--all', '--grace-period=0', '--force']))

print("\n=== Deleting all DataUploads ===")
print(kubectl_cmd(token, ['delete', 'datauploads', '-n', 'velero', '--all', '--grace-period=0', '--force']))

print("\n=== Deleting succeeded pods ===")
print(kubectl_cmd(token, ['delete', 'pods', '-n', 'velero', '--field-selector=status.phase=Succeeded']))

print("\n=== Verification ===")
print(kubectl_cmd(token, ['get', 'backups,datauploads', '-n', 'velero']))
```

---

**Last Updated:** 2025-12-19
**Method:** Python + curl (most reliable)
**Status:** Verified working
