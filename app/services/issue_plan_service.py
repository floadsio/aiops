"""Service for managing issue implementation plans.

This module provides functions for storing, retrieving, and managing
AI-generated implementation plans associated with issues.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from ..extensions import db
from ..models import ExternalIssue, IssuePlan, User


def get_plan(issue_id: int) -> Optional[IssuePlan]:
    """Get the implementation plan for an issue.

    Args:
        issue_id: The database ID of the issue

    Returns:
        IssuePlan if one exists for this issue, None otherwise
    """
    return IssuePlan.query.filter_by(issue_id=issue_id).first()


def create_or_update_plan(
    issue_id: int, content: str, user_id: int, status: str = "draft"
) -> IssuePlan:
    """Create or update an implementation plan for an issue.

    Args:
        issue_id: The database ID of the issue
        content: The markdown content of the plan
        user_id: The ID of the user creating/updating the plan
        status: Status of the plan (draft, approved, in_progress, completed)

    Returns:
        The created or updated IssuePlan

    Raises:
        ValueError: If content is empty or issue doesn't exist
    """
    if not content or not content.strip():
        raise ValueError("Plan content cannot be empty")

    # Verify issue exists
    issue = ExternalIssue.query.get(issue_id)
    if not issue:
        raise ValueError(f"Issue {issue_id} not found")

    # Check if plan already exists
    plan = get_plan(issue_id)

    if plan:
        # Update existing plan
        plan.content = content.strip()
        plan.status = status
        plan.updated_at = datetime.utcnow()
    else:
        # Create new plan
        plan = IssuePlan(
            issue_id=issue_id,
            content=content.strip(),
            status=status,
            created_by_user_id=user_id,
        )
        db.session.add(plan)

    db.session.commit()
    return plan


def delete_plan(issue_id: int) -> bool:
    """Delete the implementation plan for an issue.

    Args:
        issue_id: The database ID of the issue

    Returns:
        True if plan was deleted, False if no plan existed
    """
    plan = get_plan(issue_id)
    if not plan:
        return False

    db.session.delete(plan)
    db.session.commit()
    return True


def read_plan_from_workspace(
    project, user: User, filename: str = "PLAN.md"
) -> Optional[str]:
    """Read a plan file from user's workspace.

    Args:
        project: The Project model instance
        user: The User model instance
        filename: Name of the plan file (default: PLAN.md)

    Returns:
        Content of the plan file if it exists, None otherwise
    """
    from .workspace_service import get_workspace_path

    workspace_path = get_workspace_path(project, user)
    if not workspace_path:
        return None

    plan_path = Path(workspace_path) / filename
    if not plan_path.exists():
        return None

    try:
        return plan_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def update_plan_status(issue_id: int, status: str) -> Optional[IssuePlan]:
    """Update the status of an issue plan.

    Args:
        issue_id: The database ID of the issue
        status: New status (draft, approved, in_progress, completed)

    Returns:
        Updated IssuePlan if it exists, None otherwise
    """
    plan = get_plan(issue_id)
    if not plan:
        return None

    plan.status = status
    plan.updated_at = datetime.utcnow()
    db.session.commit()
    return plan


def get_plan_summary(plan: IssuePlan) -> dict:
    """Get a summary of a plan for API responses.

    Args:
        plan: The IssuePlan instance

    Returns:
        Dictionary with plan details
    """
    created_by_name = None
    if plan.created_by:
        created_by_name = plan.created_by.name

    return {
        "id": plan.id,
        "issue_id": plan.issue_id,
        "content": plan.content,
        "status": plan.status,
        "created_by": created_by_name,
        "created_at": plan.created_at.isoformat() if plan.created_at else None,
        "updated_at": plan.updated_at.isoformat() if plan.updated_at else None,
    }
