from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from app.services.agent_context import (
    MISSING_ISSUE_DETAILS_MESSAGE,
    render_issue_context,
)


class ProjectStub:
    name = "Demo Project"
    repo_url = "https://example.com/demo.git"
    local_path = "/repos/demo"


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

    assert "## Issue Details" in content
    assert "Detailed body" in content
    assert "More text" in content


def test_render_issue_context_includes_gitlab_description():
    project = ProjectStub()
    issue = _make_issue("gitlab", raw_payload={"description": "GitLab flavored markdown"})

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
    issue = _make_issue("jira", raw_payload={"fields": {"description": jira_description}})

    content = render_issue_context(project, issue, [issue])

    assert "Investigate the regression" in content
    assert "- Collect logs" in content
    assert "- Add tests" in content


def test_render_issue_context_handles_missing_issue_details():
    project = ProjectStub()
    issue = _make_issue("unknown", raw_payload={})

    content = render_issue_context(project, issue, [issue])

    assert MISSING_ISSUE_DETAILS_MESSAGE in content
