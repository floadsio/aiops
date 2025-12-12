"""AIops REST API v1.

This module provides a versioned, fully documented REST API for programmatic
access to AIops functionality.
"""

from flask import Blueprint

api_v1_bp = Blueprint("api_v1", __name__, url_prefix="/api/v1")

# Import all route modules to register their endpoints
from . import (  # noqa: E402, F401
    activities,
    agents,
    auth,
    communications,
    git,
    issues,
    jira_proxy,
    notifications,
    projects,
    semaphore,
    sessions,
    slack,
    system,
    tenants,
    users,
    workflows,
)
