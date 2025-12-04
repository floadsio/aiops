"""Service for managing global agents context versions.

This service handles versioning, rollback, and diff operations for the global
agents context that appears in all AGENTS.override.md files.
"""

import difflib
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import desc

from .. import db
from ..models import GlobalAgentContext, GlobalAgentsHistory, User

logger = logging.getLogger(__name__)


def get_next_version_number() -> int:
    """Get the next version number for a new history entry.

    Returns:
        Next version number (max existing version + 1, or 1 if no versions exist)
    """
    latest = (
        GlobalAgentsHistory.query.order_by(desc(GlobalAgentsHistory.version_number))
        .first()
    )
    return (latest.version_number + 1) if latest else 1


def save_version_before_update(
    current_content: str,
    user_id: Optional[int],
    description: Optional[str] = None
) -> GlobalAgentsHistory:
    """Save the current global agents content as a new version before updating.

    This function should be called before modifying the global agents content
    to preserve version history.

    Args:
        current_content: The current content to save
        user_id: ID of user making the change (None for system)
        description: Optional description of the change

    Returns:
        The created history entry

    Raises:
        ValueError: If current_content is empty
    """
    if not current_content or not current_content.strip():
        raise ValueError("Cannot save empty content as a version")

    version_number = get_next_version_number()

    history = GlobalAgentsHistory(
        version_number=version_number,
        content=current_content,
        change_description=description,
        created_by_user_id=user_id
    )

    db.session.add(history)
    db.session.commit()

    logger.info(
        f"Saved global agents version {version_number} "
        f"by user {user_id or 'system'}"
    )

    return history


def get_version_history(limit: int = 50, offset: int = 0) -> list[GlobalAgentsHistory]:
    """Get version history ordered by version number (newest first).

    Args:
        limit: Maximum number of versions to return
        offset: Number of versions to skip

    Returns:
        List of history entries
    """
    return (
        GlobalAgentsHistory.query
        .order_by(desc(GlobalAgentsHistory.version_number))
        .limit(limit)
        .offset(offset)
        .all()
    )


def get_version_by_number(version_number: int) -> Optional[GlobalAgentsHistory]:
    """Get a specific version by its version number.

    Args:
        version_number: The version number to retrieve

    Returns:
        History entry or None if not found
    """
    return GlobalAgentsHistory.query.filter_by(version_number=version_number).first()


def get_latest_version() -> Optional[GlobalAgentsHistory]:
    """Get the most recent version from history.

    Returns:
        Latest history entry or None if no history exists
    """
    return (
        GlobalAgentsHistory.query
        .order_by(desc(GlobalAgentsHistory.version_number))
        .first()
    )


def rollback_to_version(
    version_number: int,
    user_id: Optional[int],
    description: Optional[str] = None
) -> GlobalAgentContext:
    """Rollback global agents content to a previous version.

    This creates a new version with the content from the specified historical version,
    then updates the current global_agent_context table.

    Args:
        version_number: Version number to rollback to
        user_id: ID of user performing the rollback
        description: Optional description (defaults to auto-generated)

    Returns:
        Updated GlobalAgentContext entry

    Raises:
        ValueError: If version doesn't exist or rollback fails
    """
    # Get the version to rollback to
    target_version = get_version_by_number(version_number)
    if not target_version:
        raise ValueError(f"Version {version_number} not found")

    # Get current content to save as a version
    current_context = GlobalAgentContext.query.first()
    if current_context and current_context.content:
        # Save current content as a new version before rollback
        save_version_before_update(
            current_context.content,
            user_id,
            f"Before rollback to version {version_number}"
        )

    # Generate description if not provided
    if not description:
        description = f"Rolled back to version {version_number}"

    # Update the current global context
    if current_context:
        current_context.content = target_version.content
        current_context.updated_by_user_id = user_id
        current_context.updated_at = datetime.utcnow()
    else:
        # Create new entry if it doesn't exist
        current_context = GlobalAgentContext(
            content=target_version.content,
            updated_by_user_id=user_id
        )
        db.session.add(current_context)

    # Save the rollback as a new version
    save_version_before_update(
        target_version.content,
        user_id,
        description
    )

    db.session.commit()

    logger.info(
        f"Rolled back global agents to version {version_number} "
        f"by user {user_id or 'system'}"
    )

    return current_context


def get_version_diff(from_version: int, to_version: int) -> dict:
    """Generate a unified diff between two versions.

    Args:
        from_version: Source version number
        to_version: Target version number

    Returns:
        Dictionary with diff information:
        {
            "from_version": int,
            "to_version": int,
            "diff": str (unified diff format),
            "added_lines": int,
            "removed_lines": int
        }

    Raises:
        ValueError: If either version doesn't exist
    """
    from_entry = get_version_by_number(from_version)
    if not from_entry:
        raise ValueError(f"Version {from_version} not found")

    to_entry = get_version_by_number(to_version)
    if not to_entry:
        raise ValueError(f"Version {to_version} not found")

    from_lines = from_entry.content.splitlines(keepends=True)
    to_lines = to_entry.content.splitlines(keepends=True)

    diff = difflib.unified_diff(
        from_lines,
        to_lines,
        fromfile=f"Version {from_version}",
        tofile=f"Version {to_version}",
        lineterm=""
    )

    diff_text = "\n".join(diff)

    # Count added and removed lines
    added_lines = sum(1 for line in diff_text.split("\n") if line.startswith("+") and not line.startswith("+++"))
    removed_lines = sum(1 for line in diff_text.split("\n") if line.startswith("-") and not line.startswith("---"))

    return {
        "from_version": from_version,
        "to_version": to_version,
        "diff": diff_text,
        "added_lines": added_lines,
        "removed_lines": removed_lines
    }


def get_version_count() -> int:
    """Get total number of versions in history.

    Returns:
        Total count of history entries
    """
    return GlobalAgentsHistory.query.count()


def update_global_context_with_versioning(
    new_content: str,
    user_id: Optional[int],
    description: Optional[str] = None
) -> GlobalAgentContext:
    """Update global agents context and automatically save version.

    This is the main function to use when updating the global agents context.
    It automatically saves the current content as a version before updating.

    Args:
        new_content: The new content to set
        user_id: ID of user making the change
        description: Optional description of the change

    Returns:
        Updated GlobalAgentContext entry

    Raises:
        ValueError: If new_content is empty
    """
    if not new_content or not new_content.strip():
        raise ValueError("Cannot set empty content")

    # Get current content
    current_context = GlobalAgentContext.query.first()

    # Save current content as a version before updating
    if current_context and current_context.content:
        save_version_before_update(
            current_context.content,
            user_id,
            description or "Update global agents context"
        )

    # Update or create the current context
    if current_context:
        current_context.content = new_content
        current_context.updated_by_user_id = user_id
        current_context.updated_at = datetime.utcnow()
    else:
        current_context = GlobalAgentContext(
            content=new_content,
            updated_by_user_id=user_id
        )
        db.session.add(current_context)

    db.session.commit()

    logger.info(f"Updated global agents context by user {user_id or 'system'}")

    return current_context
