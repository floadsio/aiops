"""Template helpers for aiops."""

from flask import Flask

from .utils.text_rendering import render_issue_rich_text


def register_template_filters(app: Flask) -> None:
    """Expose custom template filters to Jinja."""
    app.add_template_filter(render_issue_rich_text, "render_issue_content")

