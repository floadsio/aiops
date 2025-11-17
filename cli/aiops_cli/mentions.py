"""Helper module for resolving user mentions in issue comments."""

import re
from typing import Optional


def extract_jira_users_from_comments(comments: list[dict]) -> dict[str, str]:
    """Extract Jira user information from issue comments.

    Builds a mapping of display names to account IDs from comment authors.

    Args:
        comments: List of comment dictionaries with 'author' and 'body' fields

    Returns:
        dict: Mapping of lowercase display names to account IDs
              e.g., {"jens hassler": "557058:5010d224-..."}
    """
    users = {}

    for comment in comments:
        author = comment.get("author", "")
        body = comment.get("body", "")

        if not author or not body:
            continue

        # Extract account ID from mentions in the comment body
        # Format: [~accountid:557058:uuid]
        mention_pattern = r'\[~accountid:([\d:a-f\-]+)\]'
        matches = re.findall(mention_pattern, body)

        if matches:
            # Use the first account ID found and associate it with this author
            account_id = matches[0]
            # Store both the full name and potential variations
            users[author.lower()] = account_id

            # Also store first name only for convenience
            first_name = author.split()[0].lower()
            if first_name not in users:
                users[first_name] = account_id

    return users


def resolve_mentions(text: str, user_map: dict[str, str]) -> str:
    """Replace @mentions with Jira account ID syntax.

    Supports multiple mention formats:
    - @"Full Name" -> [~accountid:...]
    - @FirstName -> [~accountid:...]
    - @full.name -> [~accountid:...]

    Args:
        text: Comment text with @mentions
        user_map: Mapping of lowercase names to account IDs

    Returns:
        str: Text with @mentions replaced by Jira account ID syntax
    """
    # Pattern 1: @"Full Name" with quotes
    def replace_quoted(match):
        name = match.group(1).lower()
        if name in user_map:
            return f"[~accountid:{user_map[name]}]"
        return match.group(0)  # Leave unchanged if not found

    text = re.sub(r'@"([^"]+)"', replace_quoted, text)

    # Pattern 2: @FirstName or @full.name (single word/dotted)
    def replace_simple(match):
        name = match.group(1).lower()
        # Try exact match first
        if name in user_map:
            return f"[~accountid:{user_map[name]}]"
        # Try with spaces (e.g., "jens.hassler" -> "jens hassler")
        name_with_spaces = name.replace(".", " ").replace("_", " ")
        if name_with_spaces in user_map:
            return f"[~accountid:{user_map[name_with_spaces]}]"
        return match.group(0)  # Leave unchanged if not found

    text = re.sub(r'@([\w.]+)', replace_simple, text)

    return text


def find_user_account_id(
    display_name: str,
    comments: list[dict],
) -> Optional[str]:
    """Find a Jira account ID by display name from issue comments.

    Args:
        display_name: User's display name (e.g., "Jens Hassler")
        comments: List of comment dictionaries

    Returns:
        str: Account ID if found, None otherwise
    """
    user_map = extract_jira_users_from_comments(comments)
    return user_map.get(display_name.lower())
