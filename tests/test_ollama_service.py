"""Tests for Ollama service integration."""

from __future__ import annotations

import json
import types
from pathlib import Path
from typing import Any

import pytest

from app import create_app
from app.config import Config


# Fake Ollama module for testing without actual ollama-python dependency
class FakeClient:
    """Fake Ollama client for testing."""

    def __init__(self, host: str = "http://localhost:11434"):
        self.host = host
        self.models = ["qwen2.5:7b", "llama2"]

    def generate(
        self,
        model: str,
        prompt: str,
        stream: bool = False,
    ) -> dict[str, Any]:
        """Generate a fake response."""
        if model not in self.models:
            raise Exception(f"Model {model} not found")

        # Generate a fake JSON response
        response_data = {
            "title": "Test Issue Title",
            "description": "## Overview\nTest description\n\n## Requirements\n- Test requirement\n\n## Acceptance Criteria\n- [ ] Test criterion",
            "labels": ["test", "feature"],
            "branch_prefix": "feature",
        }
        return {
            "response": json.dumps(response_data),
            "done": True,
        }

    def list(self) -> dict[str, Any]:
        """List available models."""
        return {
            "models": [{"name": model} for model in self.models],
        }


def _install_fake_ollama(monkeypatch):
    """Install fake ollama module in sys.modules."""
    ollama_module = types.ModuleType("ollama")
    ollama_module.Client = FakeClient
    monkeypatch.setitem(__import__("sys").modules, "ollama", ollama_module)


def _build_app(tmp_path: Path):
    """Build app with Ollama config."""
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


@pytest.fixture()
def app_with_ollama(tmp_path, monkeypatch):
    """Create app with mocked Ollama."""
    _install_fake_ollama(monkeypatch)
    app = _build_app(tmp_path)
    with app.app_context():
        yield app


class TestGenerateIssueWithOllama:
    """Tests for generate_issue_with_ollama function."""

    def test_generates_valid_issue(self, app_with_ollama, monkeypatch):
        """Test successful issue generation with valid JSON response."""
        from app.services.ollama_service import generate_issue_with_ollama

        result = generate_issue_with_ollama("Test feature description", "feature")

        assert "title" in result
        assert "description" in result
        assert "labels" in result
        assert "branch_prefix" in result
        assert result["title"] == "Test Issue Title"
        assert isinstance(result["labels"], list)
        assert result["branch_prefix"] in ["feature", "fix"]

    def test_handles_missing_library(self, tmp_path, monkeypatch):
        """Test error handling when ollama library is not installed."""
        from app.services.ollama_service import (
            OllamaServiceError,
            generate_issue_with_ollama,
        )

        # Don't install fake ollama - let import fail
        app = _build_app(tmp_path)
        with app.app_context():
            with pytest.raises(OllamaServiceError) as exc_info:
                generate_issue_with_ollama("Test")

            assert "ollama-python library is not installed" in str(exc_info.value)
            assert "uv pip install ollama" in str(exc_info.value)

    def test_handles_unavailable_service(self, app_with_ollama, monkeypatch):
        """Test error handling when Ollama service is not running."""
        from app.services.ollama_service import OllamaUnavailableError

        def fake_get_client():
            raise OllamaUnavailableError("Connection refused at http://localhost:11434")

        monkeypatch.setattr(
            "app.services.ollama_service._get_ollama_client",
            fake_get_client,
        )

        with app_with_ollama.app_context():
            from app.services.ai_issue_generator import (
                AIIssueGenerationError,
                generate_issue_from_description,
            )

            with pytest.raises(AIIssueGenerationError) as exc_info:
                generate_issue_from_description("Test")

            assert "Ollama is not available" in str(exc_info.value)

    def test_handles_markdown_wrapped_json(self, app_with_ollama, monkeypatch):
        """Test parsing JSON wrapped in markdown code blocks."""
        from app.services.ollama_service import generate_issue_with_ollama

        def fake_generate(model, prompt, stream=False):
            response_data = {
                "title": "Markdown Wrapped Title",
                "description": "Test",
                "labels": ["test"],
                "branch_prefix": "feature",
            }
            return {
                "response": f"```json\n{json.dumps(response_data)}\n```",
                "done": True,
            }

        client = FakeClient()
        client.generate = fake_generate
        monkeypatch.setattr(
            "app.services.ollama_service._get_ollama_client",
            lambda: client,
        )

        result = generate_issue_with_ollama("Test")
        assert result["title"] == "Markdown Wrapped Title"

    def test_validates_required_fields(self, app_with_ollama, monkeypatch):
        """Test validation of required fields in response."""
        from app.services.ollama_service import OllamaServiceError, generate_issue_with_ollama

        def fake_generate(model, prompt, stream=False):
            # Missing branch_prefix field
            response_data = {
                "title": "Test",
                "description": "Test",
                "labels": ["test"],
            }
            return {
                "response": json.dumps(response_data),
                "done": True,
            }

        client = FakeClient()
        client.generate = fake_generate
        monkeypatch.setattr(
            "app.services.ollama_service._get_ollama_client",
            lambda: client,
        )

        with pytest.raises(OllamaServiceError) as exc_info:
            generate_issue_with_ollama("Test")

        assert "missing required fields" in str(exc_info.value)

    def test_defaults_invalid_branch_prefix(self, app_with_ollama, monkeypatch):
        """Test that invalid branch_prefix defaults to 'feature'."""
        from app.services.ollama_service import generate_issue_with_ollama

        def fake_generate(model, prompt, stream=False):
            response_data = {
                "title": "Test",
                "description": "Test",
                "labels": ["test"],
                "branch_prefix": "invalid",
            }
            return {
                "response": json.dumps(response_data),
                "done": True,
            }

        client = FakeClient()
        client.generate = fake_generate
        monkeypatch.setattr(
            "app.services.ollama_service._get_ollama_client",
            lambda: client,
        )

        result = generate_issue_with_ollama("Test")
        assert result["branch_prefix"] == "feature"

    def test_converts_string_labels_to_list(self, app_with_ollama, monkeypatch):
        """Test that comma-separated labels are converted to list."""
        from app.services.ollama_service import generate_issue_with_ollama

        def fake_generate(model, prompt, stream=False):
            response_data = {
                "title": "Test",
                "description": "Test",
                "labels": "feature, bug, enhancement",
                "branch_prefix": "feature",
            }
            return {
                "response": json.dumps(response_data),
                "done": True,
            }

        client = FakeClient()
        client.generate = fake_generate
        monkeypatch.setattr(
            "app.services.ollama_service._get_ollama_client",
            lambda: client,
        )

        result = generate_issue_with_ollama("Test")
        assert isinstance(result["labels"], list)
        assert len(result["labels"]) == 3
        assert "feature" in result["labels"]

    def test_respects_issue_type_hint(self, app_with_ollama, monkeypatch):
        """Test that issue_type hint is passed to Ollama."""
        from app.services.ollama_service import generate_issue_with_ollama

        captured_prompt = {}

        def fake_generate(model, prompt, stream=False):
            captured_prompt["prompt"] = prompt
            response_data = {
                "title": "Test",
                "description": "Test",
                "labels": ["test"],
                "branch_prefix": "fix",  # Should match issue_type hint
            }
            return {
                "response": json.dumps(response_data),
                "done": True,
            }

        client = FakeClient()
        client.generate = fake_generate
        monkeypatch.setattr(
            "app.services.ollama_service._get_ollama_client",
            lambda: client,
        )

        result = generate_issue_with_ollama("Test bug", "bug")
        assert "This is a bug" in captured_prompt["prompt"]
        assert result["branch_prefix"] == "fix"


class TestCheckOllamaHealth:
    """Tests for check_ollama_health function."""

    def test_health_check_success(self, app_with_ollama):
        """Test successful health check."""
        from app.services.ollama_service import check_ollama_health

        with app_with_ollama.app_context():
            is_healthy, error = check_ollama_health()
            assert is_healthy is True
            assert error is None

    def test_health_check_connection_failure(self, app_with_ollama, monkeypatch):
        """Test health check with connection failure."""
        from app.services.ollama_service import check_ollama_health

        def fake_get_client():
            from app.services.ollama_service import OllamaUnavailableError
            raise OllamaUnavailableError("Connection refused")

        monkeypatch.setattr(
            "app.services.ollama_service._get_ollama_client",
            fake_get_client,
        )

        with app_with_ollama.app_context():
            is_healthy, error = check_ollama_health()
            assert is_healthy is False
            assert "Ollama unavailable" in error

    def test_health_check_no_models(self, app_with_ollama, monkeypatch):
        """Test health check when list() raises an error."""
        from app.services.ollama_service import check_ollama_health

        # Create a client whose list() method raises an error
        def fake_client():
            client = FakeClient()

            def raise_error(*args, **kwargs):
                raise Exception("No models available")

            client.list = raise_error
            return client

        monkeypatch.setattr(
            "app.services.ollama_service._get_ollama_client",
            fake_client,
        )

        is_healthy, error = check_ollama_health()
        assert is_healthy is False
        # The error should be caught and returned
        assert error is not None

    def test_health_check_never_raises(self, app_with_ollama, monkeypatch):
        """Test that health check catches all exceptions."""
        from app.services.ollama_service import check_ollama_health

        # Make _get_ollama_client raise an exception
        def fake_get_client():
            raise RuntimeError("Unexpected error")

        monkeypatch.setattr(
            "app.services.ollama_service._get_ollama_client",
            fake_get_client,
        )

        # Should not raise and should return False with error message
        is_healthy, error = check_ollama_health()
        assert is_healthy is False
        assert error is not None


class TestAIIssueGeneratorIntegration:
    """Integration tests for AI issue generator with Ollama."""

    def test_generate_issue_from_description(self, app_with_ollama):
        """Test the AI issue generator with Ollama."""
        from app.services.ai_issue_generator import generate_issue_from_description

        with app_with_ollama.app_context():
            result = generate_issue_from_description(
                "Add dark mode support to UI",
                "feature",
            )

            assert result["title"]
            assert "overview" in result["description"].lower() or "## Overview" in result["description"]
            assert isinstance(result["labels"], list)
            assert result["branch_prefix"] in ["feature", "fix"]

    def test_generate_issue_without_issue_type(self, app_with_ollama):
        """Test issue generation without explicit issue type."""
        from app.services.ai_issue_generator import generate_issue_from_description

        with app_with_ollama.app_context():
            result = generate_issue_from_description(
                "Fix critical bug in authentication",
            )

            assert result["title"]
            assert isinstance(result["labels"], list)

    def test_generate_issue_error_propagates(self, app_with_ollama, monkeypatch):
        """Test that Ollama errors are wrapped properly."""
        from app.services.ai_issue_generator import (
            AIIssueGenerationError,
            generate_issue_from_description,
        )

        def fake_get_client():
            from app.services.ollama_service import OllamaUnavailableError
            raise OllamaUnavailableError("Service down")

        monkeypatch.setattr(
            "app.services.ollama_service._get_ollama_client",
            fake_get_client,
        )

        with app_with_ollama.app_context():
            with pytest.raises(AIIssueGenerationError):
                generate_issue_from_description("Test")
