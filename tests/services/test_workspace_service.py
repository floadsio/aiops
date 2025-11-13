"""Tests for the workspace service helpers."""

from __future__ import annotations

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
