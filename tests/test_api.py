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
        f"/api/projects/{project.id}/ai/sessions",
        json={"issue_id": 123, "tool": "claude"},
    )
    assert reuse_resp.status_code == 201
    reuse_payload = reuse_resp.get_json()
    assert reuse_payload["session_id"] == "existing-claude"
    assert reuse_payload["existing"] is True
    assert create_calls == []

    fresh_resp = client.post(
        f"/api/projects/{project.id}/ai/sessions",
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
