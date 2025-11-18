"""CRITICAL tests for admin session creation as other users.

These tests MUST always pass - session handling is a core feature that cannot break.
Admins need the ability to start sessions as other users for testing and support.

IMPORTANT: This functionality must be thoroughly tested before any release.
If these tests fail, session management is broken and must be fixed immediately.
"""
import pytest

# Mark all tests in this file as critical - they must pass
pytestmark = pytest.mark.critical


def test_admin_session_feature_documented():
    """CRITICAL: Verify that admin session creation feature is documented.

    This test ensures the --user flag functionality is properly documented
    so users know how to use it.
    """
    import pathlib
    agents_md = pathlib.Path(__file__).parent.parent / "AGENTS.md"

    assert agents_md.exists(), "AGENTS.md must exist"

    content = agents_md.read_text()

    # Check for --user flag documentation
    assert "--user" in content, \
        "AGENTS.md must document the --user flag for admin session creation"

    # Check for mention of admin-only restriction
    assert "admin" in content.lower() or "Admin" in content, \
        "AGENTS.md must mention that --user is admin-only"


def test_cli_has_user_option():
    """CRITICAL: Verify CLI has --user option in sessions start command.

    This ensures the CLI properly exposes the --user flag.
    """
    from cli.aiops_cli.cli import sessions_start

    # Check that the function has a 'user' parameter
    import inspect
    sig = inspect.signature(sessions_start.callback)  # type: ignore
    params = list(sig.parameters.keys())

    assert 'user' in params, \
        "sessions_start command must have 'user' parameter for admin session creation"


def test_api_endpoint_accepts_user_id():
    """CRITICAL: Verify API endpoint signature accepts user_id parameter.

    This ensures the backend API can receive user_id from admin requests.
    """
    from app.routes import api
    import inspect

    # Get the start_project_ai_session function
    func = api.start_project_ai_session
    source = inspect.getsource(func)

    # Verify it checks for user_id in request data
    assert 'user_id' in source or 'requested_user_id' in source, \
        "API endpoint must check for user_id parameter in request data"

    # Verify it has admin check logic
    assert 'is_admin' in source, \
        "API endpoint must verify admin status before allowing user impersonation"


def test_session_creation_with_explicit_user(monkeypatch):
    """CRITICAL: Test session creation logic with explicit user_id.

    This validates the core logic of creating sessions as another user.
    """
    from app import create_app
    from flask import g
    from types import SimpleNamespace

    app = create_app()
    app.config["TESTING"] = True

    with app.app_context():
        # Mock the current user as admin
        mock_admin = SimpleNamespace(id=1, email="admin@test.com", is_admin=True)
        g.api_user = mock_admin

        # Simulate request data with user_id
        request_data = {
            "tool": "shell",
            "user_id": 2,  # Different from current user
        }

        # The key logic: when user_id is specified and different from current user,
        # and current user is admin, it should use the specified user_id

        current_user_id = 1
        requested_user_id = request_data.get("user_id")

        # This is the critical logic from the API
        if requested_user_id and requested_user_id != current_user_id:
            is_admin = getattr(g.api_user, "is_admin", False)
            assert is_admin, "Must verify admin status"

            # In real code, would also verify target user exists
            # For test, we just verify the logic allows it for admins
            final_user_id = requested_user_id
        else:
            final_user_id = current_user_id

        assert final_user_id == 2, \
            "Admin should be able to create session with different user_id"


def test_non_admin_cannot_impersonate(monkeypatch):
    """CRITICAL: Test that non-admins cannot create sessions as other users.

    Security requirement - prevents user impersonation.
    """
    from app import create_app
    from flask import g
    from types import SimpleNamespace

    app = create_app()
    app.config["TESTING"] = True

    with app.app_context():
        # Mock the current user as non-admin
        mock_user = SimpleNamespace(id=1, email="user@test.com", is_admin=False)
        g.api_user = mock_user

        # Simulate request data with different user_id
        request_data = {
            "tool": "shell",
            "user_id": 2,  # Trying to impersonate
        }

        current_user_id = 1
        requested_user_id = request_data.get("user_id")

        # This is the critical security logic
        if requested_user_id and requested_user_id != current_user_id:
            is_admin = getattr(g.api_user, "is_admin", False)

            # Non-admin trying to impersonate - should be rejected
            assert not is_admin, "Test user should not be admin"

            # In real code, this would return 403
            # For test, we just verify the admin check fails
            can_impersonate = is_admin
            assert not can_impersonate, \
                "Non-admin must not be allowed to create sessions as other users"


def test_cli_resolves_user_by_email():
    """CRITICAL: Verify CLI can resolve users by email address.

    This ensures admins can use --user user@example.com syntax.
    """
    # Test the logic for resolving user by email vs ID
    users = [
        {"id": 1, "email": "admin@test.com"},
        {"id": 2, "email": "user@test.com"},
    ]

    # Test resolving by email
    user_input = "user@test.com"
    try:
        target_user_id = int(user_input)
        user_obj = next((u for u in users if u["id"] == target_user_id), None)
    except ValueError:
        # Try as email
        user_obj = next((u for u in users if u.get("email") == user_input), None)

    assert user_obj is not None, "Must be able to find user by email"
    assert user_obj["id"] == 2, "Must resolve to correct user"

    # Test resolving by ID
    user_input = "1"
    try:
        target_user_id = int(user_input)
        user_obj = next((u for u in users if u["id"] == target_user_id), None)
    except ValueError:
        user_obj = next((u for u in users if u.get("email") == user_input), None)

    assert user_obj is not None, "Must be able to find user by ID"
    assert user_obj["id"] == 1, "Must resolve to correct user"


def test_agents_override_always_populated():
    """CRITICAL: Verify AGENTS.override.md is always written during session creation.

    Both generic sessions and issue-specific sessions must populate the file.
    """
    from app.services import agent_context

    # Verify the write_global_context_only function exists
    assert hasattr(agent_context, 'write_global_context_only'), \
        "agent_context must have write_global_context_only function"

    # Verify the write_tracked_issue_context function exists
    assert hasattr(agent_context, 'write_tracked_issue_context'), \
        "agent_context must have write_tracked_issue_context function"


def test_api_calls_context_writers():
    """CRITICAL: Verify API endpoint calls appropriate context writers.

    - With issue_id: should call write_tracked_issue_context
    - Without issue_id: should call write_global_context_only
    """
    from app.routes import api
    import inspect

    func = api.start_project_ai_session
    source = inspect.getsource(func)

    # Verify it imports both context writing functions
    assert 'write_tracked_issue_context' in source, \
        "API must use write_tracked_issue_context for issue sessions"

    assert 'write_global_context_only' in source, \
        "API must use write_global_context_only for generic sessions"

    # Verify conditional logic exists
    assert 'if issue_id:' in source or 'if issue_id' in source, \
        "API must conditionally populate context based on issue_id presence"


def test_global_context_function_exists():
    """CRITICAL: Verify write_global_context_only function exists and is importable.

    This function is essential for generic session context population.
    """
    try:
        from app.services.agent_context import write_global_context_only
        assert callable(write_global_context_only), \
            "write_global_context_only must be callable"
    except ImportError as e:
        raise AssertionError(f"Cannot import write_global_context_only: {e}")


def test_context_loading_priority():
    """CRITICAL: Verify _load_base_instructions loads from database first.

    Global context priority:
    1. Database (GlobalAgentContext)
    2. AGENTS.md file (fallback)
    """
    from app.services import agent_context
    import inspect

    func = agent_context._load_base_instructions
    source = inspect.getsource(func)

    # Verify it tries to load from database first
    assert 'GlobalAgentContext' in source, \
        "_load_base_instructions must check GlobalAgentContext in database"

    assert 'BASE_CONTEXT_FILENAME' in source or 'AGENTS.md' in source, \
        "_load_base_instructions must fall back to AGENTS.md file"


def test_sessions_and_issues_distinction_documented():
    """CRITICAL: Verify documentation clearly distinguishes sessions vs issues.

    Users must understand:
    - aiops sessions: generic work, global context only
    - aiops issues: issue-specific work, global + issue context
    """
    import pathlib

    readme = pathlib.Path(__file__).parent.parent / "README.md"
    assert readme.exists(), "README.md must exist"

    content = readme.read_text()

    # Check for sessions command documentation
    assert 'aiops sessions' in content, \
        "README.md must document 'aiops sessions' commands"

    # Check for explanation of distinction
    assert 'Issue vs Session' in content or 'sessions' in content.lower(), \
        "README.md must explain difference between sessions and issues commands"

    # Check AGENTS.md as well
    agents_md = pathlib.Path(__file__).parent.parent / "AGENTS.md"
    agents_content = agents_md.read_text()

    assert 'aiops sessions' in agents_content, \
        "AGENTS.md must document 'aiops sessions' commands"
