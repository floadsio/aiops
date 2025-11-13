"""Tests for the workspace service helpers."""

from __future__ import annotations

from types import SimpleNamespace

from app.services import workspace_service


def test_git_clone_adds_accept_new(monkeypatch):
    """Workspace git clone should accept new host keys automatically."""
    captured = {}

    def fake_run_as_user(username, command, *, env=None, timeout=None):
        captured["username"] = username
        captured["command"] = command
        captured["env"] = env
        captured["timeout"] = timeout

    monkeypatch.setattr(workspace_service, "run_as_user", fake_run_as_user)

    workspace_service._git_clone_via_sudo(
        "ivo",
        "git@example.com:repo.git",
        "/tmp/workspace",
        "main",
        env=None,
    )

    ssh_command = captured["env"]["GIT_SSH_COMMAND"]
    assert "StrictHostKeyChecking=accept-new" in ssh_command
    assert "BatchMode=yes" in ssh_command


def test_git_clone_preserves_custom_git_command(monkeypatch):
    """Custom git env should override the default StrictHostKeyChecking setting."""
    captured = {}

    def fake_run_as_user(username, command, *, env=None, timeout=None):
        captured["env"] = env

    monkeypatch.setattr(workspace_service, "run_as_user", fake_run_as_user)

    custom_env = {"GIT_SSH_COMMAND": "ssh -o StrictHostKeyChecking=yes", "FOO": "bar"}

    workspace_service._git_clone_via_sudo(
        "ivo",
        "git@example.com:repo.git",
        "/tmp/workspace",
        "main",
        env=custom_env,
    )

    assert captured["env"]["GIT_SSH_COMMAND"] == custom_env["GIT_SSH_COMMAND"]
    assert captured["env"]["FOO"] == "bar"
    # Original dict should not be mutated
    assert custom_env == {
        "GIT_SSH_COMMAND": "ssh -o StrictHostKeyChecking=yes",
        "FOO": "bar",
    }


def test_git_clone_adds_project_key(monkeypatch):
    captured = {}

    def fake_run_as_user(username, command, *, env=None, timeout=None):
        captured["env"] = env

    monkeypatch.setattr(workspace_service, "run_as_user", fake_run_as_user)

    workspace_service._git_clone_via_sudo(
        "ivo",
        "git@example.com:repo.git",
        "/tmp/workspace",
        "main",
        env=None,
        ssh_key_path="/instance/keys/syseng-iwf",
    )

    ssh_command = captured["env"]["GIT_SSH_COMMAND"]
    assert "-i /instance/keys/syseng-iwf" in ssh_command
    assert "IdentitiesOnly=yes" in ssh_command


def test_initialize_workspace_uses_project_key(monkeypatch, tmp_path):
    project = SimpleNamespace(
        id=1,
        name="Flamelet",
        repo_url="git@git.example.com:demo/flamelet.git",
        default_branch="main",
    )
    user = SimpleNamespace(email="ivo@example.com", id=99)

    workspace_dir = tmp_path / "workspace" / "flamelet"

    monkeypatch.setattr(
        workspace_service,
        "get_workspace_path",
        lambda *_: workspace_dir,
    )
    monkeypatch.setattr(
        workspace_service,
        "workspace_exists",
        lambda *_: False,
    )
    monkeypatch.setattr(
        workspace_service,
        "resolve_linux_username",
        lambda *_: "ivo",
    )
    monkeypatch.setattr(workspace_service, "mkdir", lambda *_, **__: None)

    key_path = str(tmp_path / "instance" / "keys" / "syseng-iwf")
    monkeypatch.setattr(
        workspace_service,
        "resolve_project_ssh_key_path",
        lambda *_: key_path,
    )

    captured = {}

    def fake_clone(*args, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(workspace_service, "_git_clone_via_sudo", fake_clone)

    result = workspace_service.initialize_workspace(project, user)

    assert result == workspace_dir
    assert captured["ssh_key_path"] == key_path
