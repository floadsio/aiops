from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from app.services.agent_context import (
    MISSING_ISSUE_DETAILS_MESSAGE,
    extract_issue_description,
    render_issue_context,
    write_tracked_issue_context,
)


class ProjectStub:
    def __init__(self, *, local_path: str | None = None):
        self.name = "Demo Project"
        self.repo_url = "https://example.com/demo.git"
        self.local_path = local_path or "/repos/demo"


def _make_issue(
    provider: str,
    *,
    raw_payload: dict | None = None,
    external_id: str = "ISSUE-1",
    issue_id: int = 1,
) -> SimpleNamespace:
    now = datetime(2024, 1, 1, tzinfo=timezone.utc)
    integration = SimpleNamespace(provider=provider, name=f"{provider}-integration")
    project_integration = SimpleNamespace(integration=integration)
    return SimpleNamespace(
        id=issue_id,
        external_id=external_id,
        title="Demo issue",
        status="open",
        assignee="alice",
        labels=["bug"],
        url=f"https://example.com/{external_id}",
        external_updated_at=now,
        updated_at=now,
        created_at=now,
        project_integration=project_integration,
        raw_payload=raw_payload or {},
    )


def test_render_issue_context_includes_github_body():
    project = ProjectStub()
    issue = _make_issue("github", raw_payload={"body": "Detailed body\nMore text"})

    content = render_issue_context(project, issue, [issue])

    assert "## Issue Description" in content
    assert "Detailed body" in content
    assert "More text" in content


def test_render_issue_context_includes_gitlab_description():
    project = ProjectStub()
    issue = _make_issue(
        "gitlab", raw_payload={"description": "GitLab flavored markdown"}
    )

    content = render_issue_context(project, issue, [issue])

    assert "GitLab flavored markdown" in content


def test_render_issue_context_renders_jira_description_document():
    project = ProjectStub()
    jira_description = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": "Investigate the regression"}],
            },
            {
                "type": "bulletList",
                "content": [
                    {
                        "type": "listItem",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "text": "Collect logs"}],
                            }
                        ],
                    },
                    {
                        "type": "listItem",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "text": "Add tests"}],
                            }
                        ],
                    },
                ],
            },
        ],
    }
    issue = _make_issue(
        "jira", raw_payload={"fields": {"description": jira_description}}
    )

    content = render_issue_context(project, issue, [issue])

    assert "Investigate the regression" in content
    assert "- Collect logs" in content
    assert "- Add tests" in content


def test_render_issue_context_handles_missing_issue_details():
    project = ProjectStub()
    issue = _make_issue("unknown", raw_payload={})

    content = render_issue_context(project, issue, [issue])

    assert "## Issue Description" in content
    assert MISSING_ISSUE_DETAILS_MESSAGE in content


def test_extract_issue_description_returns_body_text():
    issue = _make_issue("github", raw_payload={"body": "  Example body text  "})
    description = extract_issue_description(issue)
    assert description == "Example body text"


def test_extract_issue_description_handles_absent_text():
    issue = _make_issue("github", raw_payload={})
    assert extract_issue_description(issue) is None


def test_write_tracked_issue_context_includes_git_identity(tmp_path):
    project = ProjectStub(local_path=str(tmp_path / "repo"))
    Path(project.local_path).mkdir(parents=True, exist_ok=True)
    issue = _make_issue("github", external_id="123")
    identity = SimpleNamespace(name="Owner One", email="owner@example.com")

    path = write_tracked_issue_context(
        project,
        issue,
        [issue],
        identity_user=identity,
    )

    contents = path.read_text()
    assert "## Git Identity" in contents
    assert "Owner One" in contents
    assert "owner@example.com" in contents
    assert "git config user.name" in contents
    assert "export GIT_AUTHOR_EMAIL" in contents


def test_write_tracked_issue_context_omits_git_identity_without_user(tmp_path):
    project = ProjectStub(local_path=str(tmp_path / "repo"))
    Path(project.local_path).mkdir(parents=True, exist_ok=True)
    issue = _make_issue("gitlab", external_id="789")

    path = write_tracked_issue_context(
        project,
        issue,
        [issue],
    )

    contents = path.read_text()
    assert "## Git Identity" not in contents
