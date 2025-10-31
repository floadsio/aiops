# Architecture Notes

## Overview
The control panel exposes a Flask monolith that wraps Git automation, AI assistants, and Ansible execution within a single tenant-aware dashboard.

## Components
- **Flask Blueprints**  
  - `auth` manages session-based login.  
  - `admin` offers CRUD flows for tenants, projects, and SSH keys.  
  - `projects` enables repository automation per project.
- **SQLAlchemy Models**  
  - `User` – identity and role metadata.  
  - `SSHKey` – stores OpenSSH public keys with MD5 fingerprint.  
  - `Tenant` – logical grouping of projects.  
  - `Project` – Git repository metadata plus owner linkage.  
  - `AutomationTask` – placeholder for asynchronous executions.
- **Services & Sockets**  
  - `git_service` wraps GitPython actions for clone/pull/push/status.  
  - `/ws/projects/<id>/ai` exposes a PTY-backed interactive session that runs configured AI tools inside the project checkout.  
  - `ansible_runner` executes `ansible-playbook` commands.  
  - `key_service` computes predictable SSH fingerprints.

## Data Flow
1. Admin configures tenants/projects via forms backed by SQLAlchemy.  
2. Project registration clones the repository into `REPO_STORAGE_PATH`.  
3. Project page exposes Git, AI, and Ansible forms that immediately execute through service helpers.  
4. Outputs surface synchronously in the UI; long-running tasks should transition to a queue (Celery/RQ) in future iterations.

## Security Considerations
- Enforce HTTPS termination in production.  
- Restrict AI/Ansible commands to trusted allowlists.  
- Store secrets (database URLs, repo paths) in environment variables.  
- For production, move SSH key storage to a secure vault or HSM-enabled service; current implementation keeps keys in plaintext.

## Next Steps
- Swap synchronous subprocess calls for queued workers and websockets for progress updates.  
- Implement role-based access and audit logs.  
- Add repository-level permissions and service account SSH key injection.  
- Integrate commit/push automation with signed commits and protected branches.
