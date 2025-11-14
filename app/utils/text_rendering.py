"""Helpers for rendering user provided issue content safely."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Iterable
from urllib.parse import urlsplit

from markupsafe import Markup, escape

# Tags typically returned by providers such as Jira when rendering descriptions.
_ALLOWED_TAGS: set[str] = {
    "a",
    "b",
    "blockquote",
    "br",
    "code",
    "div",
    "em",
    "hr",
    "i",
    "li",
    "ol",
    "p",
    "pre",
    "span",
    "strong",
    "table",
    "tbody",
    "td",
    "th",
    "thead",
    "tr",
    "u",
    "ul",
}
_SELF_CLOSING_TAGS = {"br", "hr"}
_ALLOWED_ATTRS: dict[str, set[str]] = {
    "a": {"href", "rel", "target", "title"},
    "code": {"class"},
    "div": {"class"},
    "span": {"class"},
    "table": {"class"},
    "td": {"colspan"},
    "th": {"colspan"},
}
_SAFE_URL_SCHEMES = {"http", "https", "mailto", "tel"}
_HTML_DETECTION_RE = re.compile(r"<\/?\w+[^>]*>")
_STRIP_CONTENT_TAGS = {"script", "style"}


def _is_safe_url(value: str) -> bool:
    stripped = value.strip()
    if not stripped:
        return False
    split = urlsplit(stripped)
    if split.scheme:
        return split.scheme.lower() in _SAFE_URL_SCHEMES
    # Permit fragment or relative links within the tracker detail context.
    return stripped.startswith(("/", "#"))


def _sanitize_attribute(name: str, value: str) -> str | None:
    if name == "href":
        return value if _is_safe_url(value) else None
    if name == "target":
        return value if value in {"_blank", "_self"} else None
    return value


class _IssueHTMLSanitizer(HTMLParser):
    """Basic HTML sanitizer that preserves a limited set of markup."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._strip_content_depth = 0

    def _serialize_attrs(
        self, tag: str, attrs: Iterable[tuple[str, str | None]]
    ) -> str:
        allowed = _ALLOWED_ATTRS.get(tag)
        if not allowed:
            return ""

        serialized: list[str] = []
        for name, raw_value in attrs:
            if raw_value is None or name not in allowed:
                continue
            sanitized = _sanitize_attribute(name, raw_value)
            if sanitized is None:
                continue
            serialized.append(f' {name}="{escape(sanitized)}"')
        return "".join(serialized)

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[override]
        tag_lower = tag.lower()
        if tag_lower in _STRIP_CONTENT_TAGS:
            self._strip_content_depth += 1
            return
        if tag_lower not in _ALLOWED_TAGS:
            return
        attr_string = self._serialize_attrs(tag_lower, attrs)
        self._parts.append(f"<{tag_lower}{attr_string}>")

    def handle_startendtag(self, tag: str, attrs) -> None:  # type: ignore[override]
        tag_lower = tag.lower()
        if tag_lower in _STRIP_CONTENT_TAGS:
            return
        if tag_lower not in _ALLOWED_TAGS:
            return
        attr_string = self._serialize_attrs(tag_lower, attrs)
        if tag_lower in _SELF_CLOSING_TAGS:
            self._parts.append(f"<{tag_lower}{attr_string}>")
            return
        self._parts.append(f"<{tag_lower}{attr_string}></{tag_lower}>")

    def handle_endtag(self, tag: str) -> None:  # type: ignore[override]
        tag_lower = tag.lower()
        if tag_lower in _STRIP_CONTENT_TAGS:
            if self._strip_content_depth:
                self._strip_content_depth -= 1
            return
        if tag_lower not in _ALLOWED_TAGS or tag_lower in _SELF_CLOSING_TAGS:
            return
        self._parts.append(f"</{tag_lower}>")

    def handle_data(self, data: str) -> None:  # type: ignore[override]
        if self._strip_content_depth:
            return
        self._parts.append(str(escape(data)))

    def get_html(self) -> str:
        return "".join(self._parts)


def _sanitize_html(html: str) -> str:
    parser = _IssueHTMLSanitizer()
    parser.feed(html)
    parser.close()
    return parser.get_html()


def _looks_like_html(text: str) -> bool:
    return bool(_HTML_DETECTION_RE.search(text))


def render_issue_rich_text(value: str | None) -> Markup:
    """Render stored issue content (plain text or HTML) safely for templates."""
    if not value:
        return Markup("")

    stripped = value.strip()
    if not stripped:
        return Markup("")

    if _looks_like_html(stripped):
        sanitized = _sanitize_html(stripped)
        if sanitized:
            return Markup(sanitized)

    # Fall back to treating the text as plain content and preserve newlines.
    escaped = str(escape(stripped))
    return Markup(escaped.replace("\n", "<br>"))
