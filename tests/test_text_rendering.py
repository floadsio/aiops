from app.utils.text_rendering import render_issue_rich_text


def test_render_issue_rich_text_preserves_plain_text_newlines():
    rendered = render_issue_rich_text("first line\nsecond line")
    assert str(rendered) == "first line<br>second line"


def test_render_issue_rich_text_allows_basic_html():
    html = "<p>Hello<br><strong>World</strong></p>"
    assert str(render_issue_rich_text(html)) == html


def test_render_issue_rich_text_strips_disallowed_tags():
    html = "<script>alert('x')</script><p>safe</p>"
    assert str(render_issue_rich_text(html)) == "<p>safe</p>"


def test_render_issue_rich_text_rejects_unsafe_links():
    html = '<a href="javascript:alert(1)">Click me</a>'
    assert str(render_issue_rich_text(html)) == "<a>Click me</a>"


def test_render_issue_rich_text_keeps_safe_links():
    html = '<a href="https://example.com/path">Example</a>'
    assert 'href="https://example.com/path"' in str(render_issue_rich_text(html))
