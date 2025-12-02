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


def test_render_issue_rich_text_strips_broken_images():
    """Test that images with broken paths are filtered out."""
    # Test /uploads/ pattern - should strip the img tag entirely
    html = '<p>Text before <img src="/uploads/broken.png" alt="broken"> text after</p>'
    result = str(render_issue_rich_text(html))
    assert 'src="/uploads/' not in result
    assert '/uploads/' not in result
    assert '<img' not in result
    assert 'Text before' in result
    assert 'text after' in result

    # Test /rest/api/ pattern in proper HTML context
    html = '<p>See attachment: <img src="/rest/api/3/attachment/content/12345" alt="attachment"></p>'
    result = str(render_issue_rich_text(html))
    assert '/rest/api/' not in result
    assert '<img' not in result
    assert 'See attachment:' in result

    # Test mixed content with valid and broken images
    html = '<p><img src="/uploads/broken.png">Valid: <img src="https://example.com/valid.png"></p>'
    result = str(render_issue_rich_text(html))
    assert '/uploads/' not in result
    assert 'https://example.com/valid.png' in result
    # Should have exactly one img tag (the valid one)
    assert result.count('<img') == 1
