"""API authentication and authorization service.

Provides token-based authentication for the AIops REST API.
"""

from __future__ import annotations

import time
from datetime import datetime
from functools import wraps
from typing import Any, Callable, Optional

from flask import current_app, g, jsonify, request
from flask_login import current_user  # type: ignore

from ..extensions import db
from ..models import APIAuditLog, APIKey, User


def get_api_key_from_request() -> Optional[str]:
    """Extract API key from request headers.

    Looks for the key in:
    1. Authorization: Bearer <key>
    2. X-API-Key: <key>

    Returns:
        Optional[str]: The API key if found, None otherwise
    """
    # Try Authorization header
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:].strip()

    # Try X-API-Key header
    api_key_header = request.headers.get("X-API-Key", "")
    if api_key_header:
        return api_key_header.strip()

    return None


def authenticate_request() -> tuple[Optional[User], Optional[APIKey]]:
    """Authenticate the current request.

    Supports both session-based (Flask-Login) and token-based (API key) auth.

    Returns:
        tuple: (user, api_key) where user is the authenticated user
               and api_key is the API key if token auth was used
    """
    # Check if user is authenticated via session (Flask-Login)
    if current_user.is_authenticated:
        user_obj = getattr(current_user, "model", None)
        if user_obj is None:
            user_obj = current_user
        return user_obj, None

    # Try API key authentication
    api_key_str = get_api_key_from_request()
    if not api_key_str or not api_key_str.startswith("aiops_"):
        return None, None

    # Extract the key prefix for quick lookup
    key_prefix = api_key_str[:12]  # "aiops_" + first 6 hex chars

    # Find API key by prefix
    api_key = APIKey.query.filter_by(key_prefix=key_prefix, is_active=True).first()
    if not api_key:
        return None, None

    # Verify the full key
    if not api_key.verify_key(api_key_str):
        return None, None

    # Check if key is expired
    if api_key.expires_at and datetime.utcnow() > api_key.expires_at:
        return None, None

    # Update last_used_at
    api_key.last_used_at = datetime.utcnow()
    db.session.commit()

    return api_key.user, api_key


def require_api_auth(scopes: Optional[list[str]] = None):
    """Decorator to require API authentication.

    Args:
        scopes: Optional list of required scopes (e.g., ['read', 'write'])
                If None, any authenticated user is allowed

    Example:
        @api_bp.get('/protected')
        @require_api_auth(scopes=['read'])
        def protected_endpoint():
            user = g.api_user
            return jsonify({'message': f'Hello {user.name}'})
    """
    scopes = scopes or []

    def decorator(f: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(f)
        def decorated_function(*args: Any, **kwargs: Any) -> Any:
            user, api_key = authenticate_request()

            if not user:
                return (
                    jsonify(
                        {
                            "error": "Authentication required",
                            "message": "Provide a valid API key in Authorization header",
                        }
                    ),
                    401,
                )

            # Store user and api_key in g for access in the route
            g.api_user = user
            g.api_key = api_key

            # Check scopes if API key auth was used
            if api_key and scopes:
                missing_scopes = [s for s in scopes if not api_key.has_scope(s)]
                if missing_scopes:
                    return (
                        jsonify(
                            {
                                "error": "Insufficient permissions",
                                "message": f"Missing required scopes: {', '.join(missing_scopes)}",
                            }
                        ),
                        403,
                    )

            return f(*args, **kwargs)

        return decorated_function

    return decorator


def log_api_request(
    user_id: Optional[int],
    api_key_id: Optional[int],
    method: str,
    path: str,
    response_status: int,
    response_time_ms: Optional[float] = None,
    error_message: Optional[str] = None,
) -> None:
    """Log an API request to the audit log.

    Args:
        user_id: ID of the authenticated user
        api_key_id: ID of the API key used (if token auth)
        method: HTTP method
        path: Request path
        response_status: HTTP response status code
        response_time_ms: Response time in milliseconds
        error_message: Error message if request failed
    """
    try:
        # Get query params
        query_params = dict(request.args) if request.args else None

        # Get request body (limit size to avoid storing huge payloads)
        request_body = None
        if request.is_json:
            try:
                body = request.get_json(silent=True)
                if body:
                    # Redact sensitive fields
                    if isinstance(body, dict):
                        body = {
                            k: "***REDACTED***" if k in {"password", "token", "api_token", "secret"} else v
                            for k, v in body.items()
                        }
                    request_body = body
            except Exception:  # noqa: BLE001, S110
                pass

        # Create audit log entry
        log_entry = APIAuditLog(
            user_id=user_id,
            api_key_id=api_key_id,
            method=method,
            path=path,
            query_params=query_params,
            request_body=request_body,
            response_status=response_status,
            response_time_ms=response_time_ms,
            ip_address=request.remote_addr,
            user_agent=request.headers.get("User-Agent"),
            error_message=error_message,
        )
        db.session.add(log_entry)
        db.session.commit()
    except Exception as exc:  # noqa: BLE001
        # Don't fail the request if audit logging fails
        current_app.logger.error("Failed to log API request: %s", exc)
        db.session.rollback()


def audit_api_request(f: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator to automatically audit API requests.

    Example:
        @api_bp.post('/resource')
        @require_api_auth()
        @audit_api_request
        def create_resource():
            return jsonify({'id': 1})
    """

    @wraps(f)
    def decorated_function(*args: Any, **kwargs: Any) -> Any:
        start_time = time.time()
        response = None
        status_code = 200
        error_msg = None

        try:
            response = f(*args, **kwargs)

            # Extract status code from response
            if isinstance(response, tuple):
                if len(response) > 1:
                    status_code = response[1]
            elif hasattr(response, "status_code"):
                status_code = response.status_code

            return response
        except Exception as exc:
            status_code = 500
            error_msg = str(exc)
            raise
        finally:
            # Calculate response time
            response_time_ms = (time.time() - start_time) * 1000

            # Get user and API key from g
            user_id = getattr(g, "api_user", None)
            if user_id and hasattr(user_id, "id"):
                user_id = user_id.id

            api_key_id = getattr(g, "api_key", None)
            if api_key_id and hasattr(api_key_id, "id"):
                api_key_id = api_key_id.id

            # Log the request
            log_api_request(
                user_id=user_id,
                api_key_id=api_key_id,
                method=request.method,
                path=request.path,
                response_status=status_code,
                response_time_ms=response_time_ms,
                error_message=error_msg,
            )

    return decorated_function
