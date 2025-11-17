#!/usr/bin/env bash
# Update the aiops application from the upstream Git repository while preserving
# local (ignored) runtime assets such as instance data and dotenv files.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

REMOTE="${AIOPS_UPDATE_REMOTE:-origin}"
BRANCH="${AIOPS_UPDATE_BRANCH:-main}"

if ! command -v git >/dev/null 2>&1; then
  echo "git is required to run this script." >&2
  exit 1
fi

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "This script must run from within the aiops git repository." >&2
  exit 1
fi

if ! git remote get-url "${REMOTE}" >/dev/null 2>&1; then
  cat <<EOF >&2
Remote "${REMOTE}" is not configured. Add it first, e.g.:
  git remote add ${REMOTE} https://github.com/exampleorg/aiops.git
EOF
  exit 1
fi

# Ensure remote uses HTTPS instead of SSH (no SSH keys required)
current_url="$(git remote get-url "${REMOTE}")"
if [[ "$current_url" =~ ^git@github\.com:(.+)$ ]]; then
  https_url="https://github.com/${BASH_REMATCH[1]}"
  echo "Converting ${REMOTE} from SSH to HTTPS: ${https_url}"
  git remote set-url "${REMOTE}" "${https_url}"
fi

echo "Fetching updates from ${REMOTE} ..."
git fetch --prune "${REMOTE}"

stash_ref=""
if git rev-parse --verify HEAD >/dev/null 2>&1; then
  if [ -n "$(git status --porcelain)" ]; then
    timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
    label="update.sh auto-stash ${timestamp}"
    echo "Stashing local changes (${label}) ..."
    git stash push --include-untracked -m "${label}" >/dev/null
    stash_ref="$(git stash list | head -n1 | cut -d: -f1)"
  fi
fi

echo "Rebasing onto ${REMOTE}/${BRANCH} ..."
git pull --rebase "${REMOTE}" "${BRANCH}"

if [ -n "${stash_ref}" ]; then
  if git stash list | grep -q "^${stash_ref}"; then
    echo "Restoring local changes from ${stash_ref} ..."
    if ! git stash pop "${stash_ref}"; then
      echo "Warning: Unable to automatically reapply stashed changes. They remain in the stash list." >&2
    fi
  else
    echo "Note: No matching stash entry found to restore (was ${stash_ref})." >&2
  fi
fi

echo "Update complete."
