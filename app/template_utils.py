"""Template helpers for aiops."""

from flask import Flask
from markupsafe import Markup

from .utils.text_rendering import _sanitize_html, render_issue_rich_text


def sanitize_html(value: str | None) -> Markup:
    """Sanitize HTML content for safe display in templates.

    This filter removes potentially dangerous HTML while preserving
    safe formatting tags like headers, lists, code blocks, etc.
    """
    if not value:
        return Markup("")
    return Markup(_sanitize_html(value))


def register_template_filters(app: Flask) -> None:
    """Expose custom template filters to Jinja."""
    app.add_template_filter(render_issue_rich_text, "render_issue_content")
    app.add_template_filter(sanitize_html, "sanitize_html")
