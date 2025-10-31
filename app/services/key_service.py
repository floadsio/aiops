from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path
from typing import Optional

from flask import current_app


def compute_fingerprint(public_key: str) -> str:
    """Compute MD5 fingerprint for an SSH public key."""
    parts = public_key.strip().split()
    if len(parts) < 2:
        raise ValueError("Invalid SSH public key format.")
    key_body = parts[1]
    key_bytes = base64.b64decode(key_body.encode())
    digest = hashlib.md5(key_bytes, usedforsecurity=False).hexdigest()  # noqa: S324
    return ":".join(digest[i : i + 2] for i in range(0, len(digest), 2))


def resolve_private_key_path(raw_path: Optional[str]) -> Optional[Path]:
    """Return a filesystem path for stored private key material.

    Handles legacy absolute paths that referenced a different instance directory by
    rebasing them onto the active Flask instance path. Falls back to returning the
    original candidate even if the file does not exist so callers can surface a clear
    error.
    """
    if not raw_path:
        return None

    instance_path = Path(current_app.instance_path)
    expanded = os.path.expandvars(raw_path)
    candidate = Path(expanded).expanduser()

    candidates: list[Path] = []

    if candidate.is_absolute():
        candidates.append(candidate)
        try:
            relative = candidate.relative_to(instance_path)
        except ValueError:
            parts = candidate.parts
            if "instance" in parts:
                idx = parts.index("instance")
                suffix = Path(*parts[idx + 1 :])
                if suffix.parts:
                    candidates.append(instance_path / suffix)
        else:
            candidates.insert(0, instance_path / relative)
    else:
        candidates.append(instance_path / candidate)
        candidates.append(candidate)

    seen: set[Path] = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        if path.exists():
            return path

    return candidates[0] if candidates else None


def format_private_key_path(path: Path) -> str:
    """Store private key references relative to the instance directory when possible."""
    instance_path = Path(current_app.instance_path)
    try:
        relative = path.relative_to(instance_path)
        return str(relative)
    except ValueError:
        return str(path)
