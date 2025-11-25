from __future__ import annotations

import json
import types
from pathlib import Path

import pytest

from app import create_app
from app.config import Config
from app.services.ai_issue_generator import generate_issue_from_description


class FakeOllamaClient:
    """Fake Ollama client for testing."""

    def __init__(self, host: str = "http://localhost:11434"):
        self.host = host
        self.models = ["qwen2.5:7b"]

    def generate(self, model: str, prompt: str, stream: bool = False) -> dict:
        """Generate a fake response."""
        response_data = {
            "title": "Test Issue Title",
            "description": "## Overview\nTest description\n\n## Requirements\n- Test\n\n## Acceptance Criteria\n- [ ] Test",
            "labels": ["test", "feature"],
            "branch_prefix": "feature",
        }
        return {
            "response": json.dumps(response_data),
            "done": True,
        }

    def list(self) -> dict:
        """List available models."""
        return {
            "models": [{"name": model} for model in self.models],
        }


def _build_app(tmp_path: Path):
    class _Config(Config):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SQLALCHEMY_DATABASE_URI = "sqlite://"
        REPO_STORAGE_PATH = str(tmp_path / "repos")
        OLLAMA_API_URL = "http://localhost:11434"
        OLLAMA_MODEL = "qwen2.5:7b"
        OLLAMA_TIMEOUT = 60.0

    instance_dir = tmp_path / "instance"
    instance_dir.mkdir(parents=True, exist_ok=True)
    return create_app(_Config, instance_path=instance_dir)


def test_generate_issue_from_description_with_ollama(monkeypatch, tmp_path):
    """Test issue generation using Ollama."""
    # Install fake Ollama module
    ollama_module = types.ModuleType("ollama")
    ollama_module.Client = FakeOllamaClient
    monkeypatch.setitem(__import__("sys").modules, "ollama", ollama_module)

    app = _build_app(tmp_path)
    with app.app_context():
        issue_data = generate_issue_from_description(
            "broken markdown rendering",
            issue_type="bug",
        )

    assert issue_data["title"] == "Test Issue Title"
    assert "Overview" in issue_data["description"]
    assert issue_data["branch_prefix"] == "feature"
    assert isinstance(issue_data["labels"], list)
    assert "feature" in issue_data["labels"]


def test_generate_issue_requires_ollama_available(monkeypatch, tmp_path):
    """Test that issue generation fails clearly when Ollama is unavailable."""
    from app.services.ai_issue_generator import AIIssueGenerationError

    # Don't install fake Ollama - let it fail
    app = _build_app(tmp_path)
    with app.app_context():
        with pytest.raises(AIIssueGenerationError) as exc_info:
            generate_issue_from_description("Test feature")

        assert "Ollama is not available" in str(exc_info.value) or "ollama-python" in str(exc_info.value)


def test_slugify_title():
    """Test branch name slugification."""
    from app.services.ai_issue_generator import slugify_title

    assert slugify_title("Add Dark Mode Support") == "add-dark-mode-support"
    assert slugify_title("Fix: Critical Bug in Auth") == "fix-critical-bug-in-auth"
    assert slugify_title("Testing @special #chars!") == "testing-special-chars"
    assert slugify_title("Very Long Title That Should Be Truncated", 20) == "very-long-title"


def test_generate_branch_name():
    """Test branch name generation."""
    from app.services.ai_issue_generator import generate_branch_name

    branch = generate_branch_name("42", "Add user authentication", "feature")
    assert branch == "feature/42-add-user-authentication"

    branch = generate_branch_name("99", "Fix login bug", "fix")
    assert branch == "fix/99-fix-login-bug"
