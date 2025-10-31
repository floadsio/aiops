from __future__ import annotations

import base64
import hashlib


def compute_fingerprint(public_key: str) -> str:
    """Compute MD5 fingerprint for an SSH public key."""
    parts = public_key.strip().split()
    if len(parts) < 2:
        raise ValueError("Invalid SSH public key format.")
    key_body = parts[1]
    key_bytes = base64.b64decode(key_body.encode())
    digest = hashlib.md5(key_bytes, usedforsecurity=False).hexdigest()  # noqa: S324
    return ":".join(digest[i : i + 2] for i in range(0, len(digest), 2))
