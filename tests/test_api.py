from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app import create_app, db
from app.config import Config
from app.constants import DEFAULT_TENANT_COLOR
from app.models import Project, Tenant, User
from app.security import hash_password


@pytest.fixture
def test_app(tmp_path):
    class TestConfig(Config):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'api.db'}"
        REPO_STORAGE_PATH = str(tmp_path / "repos")

    instance_dir = tmp_path / "instance"
    app = create_app(TestConfig, instance_path=instance_dir)

    with app.app_context():
        db.create_all()
        admin = User(
            email="admin@example.com",
            name="Admin",
            password_hash=hash_password("pass123"),
            is_admin=True,
        )
        db.session.add(admin)
        db.session.commit()

    yield app


def login(client):
    return client.post(
        "/login",
        data={"email": "admin@example.com", "password": "pass123"},
        follow_redirects=True,
    )


def test_api_requires_auth(test_app):
    client = test_app.test_client()
    response = client.get("/api/v1/tenants")
    assert response.status_code == 401


def test_create_tenant_and_project(test_app, monkeypatch):
    client = test_app.test_client()
    login(client)

    monkeypatch.setattr("app.routes.api.ensure_repo_checkout", lambda project: project)

    tenant_resp = client.post(
        "/api/v1/tenants", json={"name": "Alpha", "description": "Tenant Alpha"}
    )
    assert tenant_resp.status_code == 201
    tenant_payload = tenant_resp.get_json()["tenant"]
    tenant_id = tenant_payload["id"]
    assert tenant_payload["color"] == DEFAULT_TENANT_COLOR

    with test_app.app_context():
        owner_id = User.query.filter_by(email="admin@example.com").first().id  # type: ignore[union-attr]

    project_payload = {
        "name": "Alpha Project",
        "repo_url": "git@example.com/alpha.git",
        "default_branch": "main",
        "description": "Demo Project",
        "tenant_id": tenant_id,
        "owner_id": owner_id,
    }

    project_resp = client.post("/api/v1/projects", json=project_payload)
    assert project_resp.status_code == 201
    project_id = project_resp.get_json()["project"]["id"]

    tenant_detail = client.get(f"/api/v1/tenants/{tenant_id}")
    assert tenant_detail.status_code == 200
    tenant_data = tenant_detail.get_json()["tenant"]
    assert any(p["id"] == project_id for p in tenant_data["projects"])
    assert all(
        p["tenant_color"] == DEFAULT_TENANT_COLOR for p in tenant_data["projects"]
    )


def test_create_tenant_with_custom_color(test_app):
    client = test_app.test_client()
    login(client)

    resp = client.post(
        "/api/v1/tenants",
        json={"name": "Colorful", "description": "", "color": "#10b981"},
    )
    assert resp.status_code == 201
    payload = resp.get_json()["tenant"]
    assert payload["color"] == "#10b981"


def test_create_tenant_invalid_color_falls_back(test_app):
    client = test_app.test_client()
    login(client)

    resp = client.post(
        "/api/v1/tenants",
        json={"name": "Fallback", "color": "#123456"},
    )
    assert resp.status_code == 201
    payload = resp.get_json()["tenant"]
    assert payload["color"] == DEFAULT_TENANT_COLOR


def test_create_tenant_color_without_hash_is_normalized(test_app):
    client = test_app.test_client()
    login(client)

    resp = client.post(
        "/api/v1/tenants",
        json={"name": "Normalized", "color": "10b981"},
    )
    assert resp.status_code == 201
    payload = resp.get_json()["tenant"]
    assert payload["color"] == "#10b981"


def _create_seed_project(app, tenant_name="seed", project_name="seed-project"):
    with app.app_context():
        user = User.query.filter_by(email="admin@example.com").first()
        tenant = Tenant(name=tenant_name, description="Seed tenant")
        local_path = Path(app.config["REPO_STORAGE_PATH"]) / project_name
        local_path.mkdir(parents=True, exist_ok=True)
        project = Project(
            name=project_name,
            repo_url="git@example.com/demo.git",
            default_branch="main",
            local_path=str(local_path),
            tenant=tenant,
            owner=user,
        )
        db.session.add_all([tenant, project])
        db.session.commit()
        return SimpleNamespace(id=project.id)


def test_project_git_action(test_app, monkeypatch):
    client = test_app.test_client()
    login(client)

    project = _create_seed_project(test_app, project_name="git-project")

    def fake_git_action(proj, action, ref=None, *, clean=False):
        assert proj.id == project.id
        assert action == "status"
        assert clean is False
        return "On branch main\nnothing to commit"

    monkeypatch.setattr("app.routes.api.run_git_action", fake_git_action)

    response = client.post(
        f"/api/v1/projects/{project.id}/git",
        json={"action": "status"},
    )

    assert response.status_code == 200
    assert "nothing to commit" in response.get_json()["result"]


def test_project_git_action_clean_pull(test_app, monkeypatch):
    client = test_app.test_client()
    login(client)

    project = _create_seed_project(test_app, project_name="clean-project")

    calls = {}

    def fake_git_action(proj, action, ref=None, *, clean=False):
        calls.update(
            {
                "proj_id": proj.id,
                "action": action,
                "ref": ref,
                "clean": clean,
            }
        )
        return "pulled"

    monkeypatch.setattr("app.routes.api.run_git_action", fake_git_action)

    response = client.post(
        f"/api/v1/projects/{project.id}/git",
        json={"action": "pull", "clean": True},
    )

    assert response.status_code == 200
    assert response.get_json()["result"] == "pulled"
    assert calls == {
        "proj_id": project.id,
        "action": "pull",
        "ref": None,
        "clean": True,
    }


def test_project_ai_session_lifecycle(test_app, monkeypatch):
    client = test_app.test_client()
    login(client)

    project = _create_seed_project(test_app, project_name="ai-project")

    sent_data: list[str] = []
    captured: dict[str, str | None] = {}

    def fake_create_session(project_obj, user_id, **kwargs):
        assert project_obj.id == project.id
        captured["tmux_target"] = kwargs.get("tmux_target")
        return SimpleNamespace(id="session-123", project_id=project.id)

    def fake_get_session(session_id):
        if session_id == "session-123":
            return SimpleNamespace(id=session_id, project_id=project.id)
        return None

    def fake_write_to_session(session_obj, data):
        sent_data.append(data)

    closed: list[str] = []

    def fake_close_session(session_obj):
        closed.append(session_obj.id)

    monkeypatch.setattr("app.routes.api.create_session", fake_create_session)
    monkeypatch.setattr("app.routes.api.get_session", fake_get_session)
    monkeypatch.setattr("app.routes.api.write_to_session", fake_write_to_session)
    monkeypatch.setattr("app.routes.api.close_session", fake_close_session)

    start_resp = client.post(
        f"/api/v1/projects/{project.id}/ai/sessions",
        json={"prompt": "print('hello')"},
    )
    assert start_resp.status_code == 201
    session_id = start_resp.get_json()["session_id"]
    assert session_id == "session-123"
    assert sent_data == ["print('hello')\n"]
    assert captured["tmux_target"] is None

    input_resp = client.post(
        f"/api/v1/projects/{project.id}/ai/sessions/{session_id}/input",
        json={"data": "continue\\n"},
    )
    assert input_resp.status_code == 200
    assert "status" in input_resp.get_json()
    assert sent_data[-1] == "continue\\n"

    stop_resp = client.delete(f"/api/v1/projects/{project.id}/ai/sessions/{session_id}")
    assert stop_resp.status_code == 204
    assert closed == ["session-123"]


def test_project_ai_session_resize(test_app, monkeypatch):
    client = test_app.test_client()
    login(client)

    project = _create_seed_project(test_app, project_name="resize-project")

    def fake_get_session(session_id):
        if session_id == "session-resize":
            return SimpleNamespace(id=session_id, project_id=project.id)
        return None

    resize_calls: list[tuple[str, int, int]] = []

    def fake_resize_session(session_obj, rows, cols):
        resize_calls.append((session_obj.id, rows, cols))

    monkeypatch.setattr("app.routes.api.get_session", fake_get_session)
    monkeypatch.setattr("app.routes.api.resize_session", fake_resize_session)

    ok_resp = client.post(
        f"/api/v1/projects/{project.id}/ai/sessions/session-resize/resize",
        json={"rows": 42, "cols": 120},
    )
    assert ok_resp.status_code == 204
    assert resize_calls == [("session-resize", 42, 120)]

    bad_resp = client.post(
        f"/api/v1/projects/{project.id}/ai/sessions/session-resize/resize",
        json={"rows": "bad", "cols": 10},
    )
    assert bad_resp.status_code == 400
    assert resize_calls == [("session-resize", 42, 120)]


def test_project_ai_session_attach_existing(test_app, monkeypatch):
    client = test_app.test_client()
    login(client)

    project = _create_seed_project(test_app, project_name="attach-project")

    captured: dict[str, str | None] = {}

    def fake_create_session(project_obj, user_id, **kwargs):
        captured["tmux_target"] = kwargs.get("tmux_target")
        return SimpleNamespace(id="session-attach", project_id=project.id)

    monkeypatch.setattr("app.routes.api.create_session", fake_create_session)

    response = client.post(
        f"/api/v1/projects/{project.id}/ai/sessions",
        json={"tmux_target": "aiops:tenant-shell"},
    )
    assert response.status_code == 201
    assert captured["tmux_target"] == "aiops:tenant-shell"


def test_project_ai_session_reuse_respects_tool(test_app, monkeypatch):
    client = test_app.test_client()
    login(client)

    project = _create_seed_project(test_app, project_name="reuse-project")
    test_app.config["ENABLE_PERSISTENT_SESSIONS"] = False

    find_calls: list[tuple] = []
    existing = SimpleNamespace(
        id="existing-claude",
        project_id=project.id,
        user_id=1,
        issue_id=123,
        tmux_target="aiops:existing",
    )

    def fake_find_session(issue_id, user_id, project_id, *, expected_tool=None, expected_command=None):
        find_calls.append((issue_id, user_id, project_id, expected_tool, expected_command))
        if expected_tool == "claude":
            return existing
        return None

    create_calls: list[dict] = []

    def fake_create_session(project_obj, user_id, **kwargs):
        create_calls.append(kwargs)
        return SimpleNamespace(
            id="new-codex",
            project_id=project.id,
            tmux_target="aiops:new",
        )

    monkeypatch.setattr("app.routes.api.find_session_for_issue", fake_find_session)
    monkeypatch.setattr("app.routes.api.create_session", fake_create_session)

    reuse_resp = client.post(
        f"/api/v1/projects/{project.id}/ai/sessions",
        json={"issue_id": 123, "tool": "claude"},
    )
    assert reuse_resp.status_code == 201
    reuse_payload = reuse_resp.get_json()
    assert reuse_payload["session_id"] == "existing-claude"
    assert reuse_payload["existing"] is True
    assert create_calls == []

    fresh_resp = client.post(
        f"/api/v1/projects/{project.id}/ai/sessions",
        json={"issue_id": 123, "tool": "codex"},
    )
    assert fresh_resp.status_code == 201
    fresh_payload = fresh_resp.get_json()
    assert fresh_payload["session_id"] == "new-codex"
    assert fresh_payload["existing"] is False
    assert len(create_calls) == 1

    assert len(find_calls) == 2
    # Ensure we resolved and compared the commands so tool changes trigger a new session
    first_expected_command = find_calls[0][4]
    second_expected_command = find_calls[1][4]
    assert first_expected_command != second_expected_command


def test_project_ai_session_uses_new_tmux_target_when_tool_differs(test_app, monkeypatch):
    client = test_app.test_client()
    login(client)

    project = _create_seed_project(test_app, project_name="multi-session")
    test_app.config["ENABLE_PERSISTENT_SESSIONS"] = False

    monkeypatch.setattr("app.routes.api.find_session_for_issue", lambda *a, **k: None)

    created: list[dict] = []

    def fake_create_session(project_obj, user_id, **kwargs):
        created.append(kwargs)
        return SimpleNamespace(
            id=f"session-{len(created)}",
            tmux_target=kwargs.get("tmux_target"),
            project_id=project_obj.id,
        )

    monkeypatch.setattr("app.routes.api.create_session", fake_create_session)

    first = client.post(
        f"/api/v1/projects/{project.id}/ai/sessions",
        json={"issue_id": 123, "tool": "claude"},
    )
    second = client.post(
        f"/api/v1/projects/{project.id}/ai/sessions",
        json={"issue_id": 123, "tool": "codex"},
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert len(created) == 2
    first_target = created[0]["tmux_target"]
    second_target = created[1]["tmux_target"]
    assert first_target
    assert second_target
    assert first_target != second_target
    assert first.get_json()["tmux_target"] == first_target
    assert second.get_json()["tmux_target"] == second_target


def test_project_ai_session_without_issue_gets_unique_tmux_target(test_app, monkeypatch):
    client = test_app.test_client()
    login(client)

    project = _create_seed_project(test_app, project_name="project-only-sessions")
    test_app.config["ENABLE_PERSISTENT_SESSIONS"] = False

    created: list[dict] = []

    def fake_create_session(project_obj, user_id, **kwargs):
        created.append(kwargs)
        return SimpleNamespace(
            id=f"session-{len(created)}",
            tmux_target=kwargs.get("tmux_target"),
            project_id=project_obj.id,
        )

    monkeypatch.setattr("app.routes.api.create_session", fake_create_session)

    first = client.post(
        f"/api/v1/projects/{project.id}/ai/sessions",
        json={"tool": "claude"},
    )
    second = client.post(
        f"/api/v1/projects/{project.id}/ai/sessions",
        json={"tool": "codex"},
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert len(created) == 2
    first_target = created[0]["tmux_target"]
    second_target = created[1]["tmux_target"]
    assert first_target
    assert second_target
    assert first_target != second_target


def test_issue_work_respects_tool_parameter(test_app):
    """Test that aiops issues work respects the --tool parameter.

    This test verifies that the tool parameter flows correctly through the API,
    creating different tmux targets for different tools and using the default when not specified.
    """
    client = test_app.test_client()
    login(client)

    project = _create_seed_project(test_app, project_name="issue-work-project")
    test_app.config["ENABLE_PERSISTENT_SESSIONS"] = False

    # Test 1: Start session with tool=claude
    claude_resp = client.post(
        f"/api/v1/projects/{project.id}/ai/sessions",
        json={"issue_id": 100, "tool": "claude"},
    )

    # Test 2: Start session with tool=codex
    codex_resp = client.post(
        f"/api/v1/projects/{project.id}/ai/sessions",
        json={"issue_id": 100, "tool": "codex"},
    )

    # Test 3: Start session without tool (should use default)
    default_resp = client.post(
        f"/api/v1/projects/{project.id}/ai/sessions",
        json={"issue_id": 100},
    )

    # All should succeed
    assert claude_resp.status_code == 201, f"Claude session creation failed: {claude_resp.get_json()}"
    assert codex_resp.status_code == 201, f"Codex session creation failed: {codex_resp.get_json()}"
    assert default_resp.status_code == 201, f"Default session creation failed: {default_resp.get_json()}"

    # Verify tmux targets are different (tool parameter affects target name)
    claude_target = claude_resp.get_json().get("tmux_target")
    codex_target = codex_resp.get_json().get("tmux_target")
    default_target = default_resp.get_json().get("tmux_target")

    assert claude_target, "Claude session should have tmux_target"
    assert codex_target, "Codex session should have tmux_target"
    assert default_target, "Default session should have tmux_target"

    # Different tools should create different targets
    # (the tool name is included in the target name)
    assert claude_target != codex_target, f"Claude and Codex should get different targets: {claude_target} vs {codex_target}"
    assert codex_target != default_target, f"Codex and default should get different targets: {codex_target} vs {default_target}"


def test_issue_work_reattach_without_tool_returns_most_recent(test_app):
    """Test that reattaching without --tool returns the most recent session with correct tool info."""
    client = test_app.test_client()
    login(client)

    project = _create_seed_project(test_app, project_name="reattach-test-project")
    test_app.config["ENABLE_PERSISTENT_SESSIONS"] = False

    # Create a Claude session for issue 200
    response1 = client.post(
        f"/api/v1/projects/{project.id}/ai/sessions",
        json={
            "issue_id": 200,
            "tool": "claude",
        },
    )
    assert response1.status_code == 201, f"Claude session creation failed: {response1.get_json()}"
    result1 = response1.get_json()
    claude_session_id = result1["session_id"]
    claude_tool = result1.get("tool")
    assert claude_tool == "claude", f"Expected tool=claude, got {claude_tool}"

    # Reattach without specifying --tool
    # This should return the most recent session (the Claude one)
    response2 = client.post(
        f"/api/v1/projects/{project.id}/ai/sessions",
        json={
            "issue_id": 200,
            # Note: no tool parameter - this is the critical test case
        },
    )
    assert response2.status_code == 201, f"Reattach failed: {response2.get_json()}"
    result2 = response2.get_json()
    reattached_session_id = result2["session_id"]
    reattached_tool = result2.get("tool")

    # Verify we got back the same session
    assert reattached_session_id == claude_session_id, (
        f"Should reattach to existing Claude session, "
        f"got {reattached_session_id} instead of {claude_session_id}"
    )

    # Verify the tool information is returned
    assert reattached_tool == "claude", (
        f"Reattached session should be using claude tool, got {reattached_tool}"
    )

    # Verify it's marked as existing
    assert result2.get("existing") is True, "Should be marked as existing session"


def test_get_project_integrations_endpoint(test_app, monkeypatch):
    """Test the GET /api/v1/projects/<id>/integrations endpoint for integration selector."""
    from app.models import ProjectIntegration, TenantIntegration

    client = test_app.test_client()
    login(client)

    # Create a project using the existing helper
    project_ns = _create_seed_project(test_app, project_name="integration-selector-test")
    project_id = project_ns.id

    # Get the actual project object to access tenant_id
    with test_app.app_context():
        project = Project.query.get(project_id)
        tenant_id = project.tenant_id

    # Test 1: Get integrations for project with no integrations
    resp = client.get(f"/api/v1/projects/{project_id}/integrations")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["integrations"] == []

    # Test 2: Create a tenant integration and link it to the project
    with test_app.app_context():
        tenant_int = TenantIntegration(
            tenant_id=tenant_id,
            provider="github",
            name="my-org/my-repo",
            api_token="test-token",
        )
        db.session.add(tenant_int)
        db.session.flush()

        # Link the integration to the project
        proj_int = ProjectIntegration(
            project_id=project_id,
            integration_id=tenant_int.id,
            external_identifier="repo1",
        )
        db.session.add(proj_int)
        db.session.commit()

        proj_int_id = proj_int.id

    # Test 3: Get integrations for project with one integration
    resp = client.get(f"/api/v1/projects/{project_id}/integrations")
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data["integrations"]) == 1
    integration = data["integrations"][0]
    assert integration["provider"] == "github"
    assert integration["name"] == "my-org/my-repo"
    assert integration["display_name"] == "GITHUB - my-org/my-repo"
    assert integration["project_integration_id"] == proj_int_id

    # Test 4: Create another integration and verify both are returned
    with test_app.app_context():
        tenant_int2 = TenantIntegration(
            tenant_id=tenant_id,
            provider="gitlab",
            name="my-group/my-project",
            api_token="test-token-2",
        )
        db.session.add(tenant_int2)
        db.session.flush()

        proj_int2 = ProjectIntegration(
            project_id=project_id,
            integration_id=tenant_int2.id,
            external_identifier="repo2",
        )
        db.session.add(proj_int2)
        db.session.commit()

    resp = client.get(f"/api/v1/projects/{project_id}/integrations")
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data["integrations"]) == 2

    # Verify both integrations are in the response
    providers = [int["provider"] for int in data["integrations"]]
    assert "github" in providers
    assert "gitlab" in providers

    display_names = [int["display_name"] for int in data["integrations"]]
    assert "GITHUB - my-org/my-repo" in display_names
    assert "GITLAB - my-group/my-project" in display_names

    # Test 5: Test access control - non-existent project returns 404
    resp = client.get("/api/v1/projects/99999/integrations")
    assert resp.status_code == 404
