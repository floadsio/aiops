"""Slack integration service for polling-based issue creation and notifications.

This service handles:
- Polling Slack channels for messages with trigger emoji reactions or bot commands
- Creating issues from flagged Slack messages
- Posting updates to Slack threads when issue status changes
- Managing Slack user to aiops user mappings
- Bot commands: list, close, delete, help
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from ..extensions import db
from ..models import (
    ExternalIssue,
    Project,
    ProjectIntegration,
    SlackPendingIssue,
    SlackProcessedMessage,
    SlackUserMapping,
    TenantIntegration,
    User,
)

logger = logging.getLogger(__name__)

# Default trigger emoji (ticket emoji)
DEFAULT_TRIGGER_EMOJI = "ticket"

# Default polling interval in minutes
DEFAULT_POLL_INTERVAL = 5


class SlackServiceError(Exception):
    """Base exception for Slack service errors."""


class SlackAuthError(SlackServiceError):
    """Authentication error with Slack API."""


class SlackChannelError(SlackServiceError):
    """Error accessing a Slack channel."""


@dataclass
class SlackMessage:
    """Represents a Slack message that triggered issue creation."""

    channel_id: str
    message_ts: str
    user_id: str
    text: str
    thread_ts: Optional[str] = None
    permalink: Optional[str] = None


@dataclass
class SlackIntegrationConfig:
    """Configuration for a Slack integration."""

    tenant_id: int
    integration_id: int
    bot_token: str
    channels: list[str]
    trigger_emoji: str = DEFAULT_TRIGGER_EMOJI
    trigger_keyword: Optional[str] = None  # e.g., "@aiops" or "!issue"
    bot_user_id: Optional[str] = None  # Bot's Slack user ID for mention detection
    default_project_id: Optional[int] = None
    notify_on_status_change: bool = True
    notify_on_close: bool = True
    sync_comments: bool = False
    poll_interval_minutes: int = DEFAULT_POLL_INTERVAL


class SlackCommandType(Enum):
    """Types of bot commands."""

    CREATE = "create"  # @aiops <message> or @aiops in <project> <message>
    LIST = "list"  # @aiops list [project|all]
    CLOSE = "close"  # @aiops close <id>
    DELETE = "delete"  # @aiops delete <id>
    HELP = "help"  # @aiops help
    CONFIRM_PENDING = "confirm_pending"  # ok, yes, confirm - accept pending issue
    CANCEL_PENDING = "cancel_pending"  # cancel, no, reject - cancel pending issue


@dataclass
class SlackCommand:
    """Parsed bot command from a Slack message."""

    command_type: SlackCommandType
    project_name: Optional[str] = None  # For create/list with specific project
    issue_id: Optional[int] = None  # For close/delete
    message_text: Optional[str] = None  # For create - the issue title/description
    list_all: bool = False  # For list all tenant issues


def parse_slack_command(text: str) -> SlackCommand:
    """Parse a bot command from message text.

    Supported formats:
        <message>                    -> CREATE issue with message
        in <project> <message>       -> CREATE issue in specific project
        list                         -> LIST issues (default project)
        list <project>               -> LIST issues for project
        list all                     -> LIST all tenant issues
        close <id>                   -> CLOSE issue
        delete <id>                  -> DELETE issue
        help                         -> HELP
        ok/yes/confirm               -> CONFIRM_PENDING (accept pending issue)
        cancel/no/reject             -> CANCEL_PENDING (reject pending issue)

    Args:
        text: Message text (already stripped of bot mention)

    Returns:
        SlackCommand with parsed details
    """
    text = text.strip()
    text_lower = text.lower()

    # Confirm pending issue
    if text_lower in ("ok", "yes", "confirm", "approve", "y"):
        return SlackCommand(command_type=SlackCommandType.CONFIRM_PENDING)

    # Cancel pending issue
    if text_lower in ("cancel", "no", "reject", "n"):
        return SlackCommand(command_type=SlackCommandType.CANCEL_PENDING)

    # Help command
    if text_lower == "help" or text_lower == "?":
        return SlackCommand(command_type=SlackCommandType.HELP)

    # List command
    if text_lower.startswith("list"):
        remainder = text[4:].strip()
        if not remainder:
            return SlackCommand(command_type=SlackCommandType.LIST)
        if remainder.lower() == "all":
            return SlackCommand(command_type=SlackCommandType.LIST, list_all=True)
        return SlackCommand(command_type=SlackCommandType.LIST, project_name=remainder)

    # Close command
    match = re.match(r"^close\s+(\d+)$", text_lower)
    if match:
        return SlackCommand(
            command_type=SlackCommandType.CLOSE, issue_id=int(match.group(1))
        )

    # Delete command
    match = re.match(r"^delete\s+(\d+)$", text_lower)
    if match:
        return SlackCommand(
            command_type=SlackCommandType.DELETE, issue_id=int(match.group(1))
        )

    # Create with project: "in <project> <message>"
    match = re.match(r"^in\s+(\S+)\s+(.+)$", text, re.IGNORECASE | re.DOTALL)
    if match:
        return SlackCommand(
            command_type=SlackCommandType.CREATE,
            project_name=match.group(1),
            message_text=match.group(2).strip(),
        )

    # Default: create issue with the message
    if text:
        return SlackCommand(
            command_type=SlackCommandType.CREATE, message_text=text
        )

    # Empty message - show help
    return SlackCommand(command_type=SlackCommandType.HELP)


def get_slack_client(bot_token: str) -> WebClient:
    """Create a Slack WebClient with the given bot token.

    Args:
        bot_token: Slack Bot OAuth token (xoxb-...)

    Returns:
        Configured WebClient instance
    """
    return WebClient(token=bot_token)


def get_slack_integrations() -> list[SlackIntegrationConfig]:
    """Get all enabled Slack integrations across all tenants.

    Returns:
        List of SlackIntegrationConfig for each enabled Slack integration
    """
    integrations = TenantIntegration.query.filter_by(
        provider="slack", enabled=True
    ).all()

    configs = []
    for integration in integrations:
        settings = integration.settings or {}
        channels = settings.get("channels", [])

        if not channels:
            logger.warning(
                "Slack integration %s has no channels configured, skipping",
                integration.name,
            )
            continue

        configs.append(
            SlackIntegrationConfig(
                tenant_id=integration.tenant_id,
                integration_id=integration.id,
                bot_token=integration.api_token,
                channels=channels,
                trigger_emoji=settings.get("trigger_emoji", DEFAULT_TRIGGER_EMOJI),
                trigger_keyword=settings.get("trigger_keyword"),
                bot_user_id=settings.get("bot_user_id"),
                default_project_id=settings.get("default_project_id"),
                notify_on_status_change=settings.get("notify_on_status_change", True),
                notify_on_close=settings.get("notify_on_close", True),
                sync_comments=settings.get("sync_comments", False),
                poll_interval_minutes=settings.get(
                    "poll_interval_minutes", DEFAULT_POLL_INTERVAL
                ),
            )
        )

    return configs


def get_thread_replies(
    client: WebClient,
    channel_id: str,
    thread_ts: str,
    oldest: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Fetch replies in a thread.

    Args:
        client: Slack WebClient
        channel_id: Channel ID
        thread_ts: Thread parent timestamp
        oldest: Only messages after this timestamp

    Returns:
        List of reply message objects (excluding parent)
    """
    try:
        response = client.conversations_replies(
            channel=channel_id,
            ts=thread_ts,
            oldest=oldest,
            limit=100,
        )
        messages = response.get("messages", [])
        # First message is the parent, skip it
        return messages[1:] if len(messages) > 1 else []
    except SlackApiError as e:
        logger.warning("Failed to fetch thread replies: %s", e)
        return []


def get_channel_history(
    client: WebClient,
    channel_id: str,
    oldest: Optional[str] = None,
    limit: int = 20,  # Reduced from 100 to avoid rate limits on reactions.get
) -> list[dict[str, Any]]:
    """Fetch message history from a Slack channel.

    Args:
        client: Slack WebClient
        channel_id: Channel ID to fetch from
        oldest: Only messages after this timestamp
        limit: Maximum messages to fetch

    Returns:
        List of message objects

    Raises:
        SlackChannelError: If channel access fails
    """
    try:
        response = client.conversations_history(
            channel=channel_id,
            oldest=oldest,
            limit=limit,
        )
        return response.get("messages", [])
    except SlackApiError as e:
        if e.response.get("error") == "channel_not_found":
            raise SlackChannelError(f"Channel {channel_id} not found")
        if e.response.get("error") == "not_in_channel":
            raise SlackChannelError(
                f"Bot is not a member of channel {channel_id}. "
                "Use /invite @botname to add it."
            )
        raise SlackServiceError(f"Failed to fetch channel history: {e}")


def get_message_reactions(
    client: WebClient,
    channel_id: str,
    message_ts: str,
) -> list[dict[str, Any]]:
    """Get reactions on a specific message.

    Args:
        client: Slack WebClient
        channel_id: Channel containing the message
        message_ts: Message timestamp

    Returns:
        List of reaction objects with 'name' and 'users' keys
    """
    import time

    try:
        response = client.reactions_get(
            channel=channel_id,
            timestamp=message_ts,
        )
        message = response.get("message", {})
        return message.get("reactions", [])
    except SlackApiError as e:
        if e.response.get("error") == "ratelimited":
            retry_after = int(e.response.headers.get("Retry-After", 5))
            logger.warning("Rate limited on reactions.get, waiting %ds", retry_after)
            time.sleep(retry_after)
            # Retry once after waiting
            try:
                response = client.reactions_get(
                    channel=channel_id,
                    timestamp=message_ts,
                )
                message = response.get("message", {})
                return message.get("reactions", [])
            except SlackApiError:
                return []
        logger.warning(
            "Failed to get reactions for message %s in %s: %s",
            message_ts,
            channel_id,
            e,
        )
        return []


def has_trigger_reaction(reactions: list[dict[str, Any]], trigger_emoji: str) -> bool:
    """Check if reactions include the trigger emoji.

    Args:
        reactions: List of reaction objects
        trigger_emoji: Emoji name to look for (without colons)

    Returns:
        True if trigger emoji found
    """
    for reaction in reactions:
        if reaction.get("name") == trigger_emoji:
            return True
    return False


def get_trigger_user(
    reactions: list[dict[str, Any]], trigger_emoji: str
) -> Optional[str]:
    """Get the user who added the trigger reaction.

    Args:
        reactions: List of reaction objects
        trigger_emoji: Emoji name to look for

    Returns:
        User ID of first user who reacted, or None
    """
    for reaction in reactions:
        if reaction.get("name") == trigger_emoji:
            users = reaction.get("users", [])
            if users:
                return users[0]
    return None


def get_user_info(client: WebClient, user_id: str) -> dict[str, Any]:
    """Fetch user information from Slack.

    Args:
        client: Slack WebClient
        user_id: Slack user ID

    Returns:
        User profile information
    """
    try:
        response = client.users_info(user=user_id)
        return response.get("user", {})
    except SlackApiError as e:
        logger.warning("Failed to get user info for %s: %s", user_id, e)
        return {}


def ensure_user_mapping(
    tenant_id: int, slack_user_id: str, client: WebClient
) -> SlackUserMapping:
    """Ensure a Slack user mapping exists, creating one if needed.

    If the mapping doesn't exist, fetches user info from Slack and
    attempts to auto-match by email.

    Args:
        tenant_id: Tenant ID
        slack_user_id: Slack user ID
        client: Slack WebClient for fetching user info

    Returns:
        SlackUserMapping instance (existing or newly created)
    """
    mapping = SlackUserMapping.query.filter_by(
        tenant_id=tenant_id, slack_user_id=slack_user_id
    ).first()

    if mapping:
        return mapping

    # Fetch user info from Slack
    user_info = get_user_info(client, slack_user_id)
    profile = user_info.get("profile", {})

    display_name = (
        user_info.get("real_name")
        or profile.get("display_name")
        or profile.get("real_name")
        or slack_user_id
    )
    email = profile.get("email")

    # Create new mapping
    mapping = SlackUserMapping(
        tenant_id=tenant_id,
        slack_user_id=slack_user_id,
        slack_display_name=display_name,
        slack_email=email,
    )

    # Try auto-match by email
    if email:
        aiops_user = User.query.filter_by(email=email).first()
        if aiops_user:
            mapping.aiops_user_id = aiops_user.id
            logger.info(
                "Auto-matched Slack user %s to aiops user %s via email",
                slack_user_id,
                aiops_user.email,
            )

    db.session.add(mapping)
    db.session.commit()

    logger.info(
        "Created Slack user mapping for %s (%s)",
        slack_user_id,
        display_name,
    )

    return mapping


def get_message_permalink(
    client: WebClient, channel_id: str, message_ts: str
) -> Optional[str]:
    """Get the permanent link to a Slack message.

    Args:
        client: Slack WebClient
        channel_id: Channel containing the message
        message_ts: Message timestamp

    Returns:
        Permalink URL or None if failed
    """
    try:
        response = client.chat_getPermalink(
            channel=channel_id,
            message_ts=message_ts,
        )
        return response.get("permalink")
    except SlackApiError as e:
        logger.warning(
            "Failed to get permalink for message %s in %s: %s",
            message_ts,
            channel_id,
            e,
        )
        return None


def is_message_processed(channel_id: str, message_ts: str) -> bool:
    """Check if a message has already been processed (as issue or command).

    Args:
        channel_id: Slack channel ID
        message_ts: Message timestamp

    Returns:
        True if message has been processed
    """
    # Check if an issue was created from this message
    existing_issue = ExternalIssue.query.filter_by(
        slack_channel_id=channel_id,
        slack_message_ts=message_ts,
    ).first()
    if existing_issue:
        return True

    # Check if this message was processed as a command
    existing_command = SlackProcessedMessage.query.filter_by(
        channel_id=channel_id,
        message_ts=message_ts,
    ).first()
    return existing_command is not None


def mark_message_processed(channel_id: str, message_ts: str, command_type: str) -> None:
    """Mark a message as processed (for non-issue commands).

    Args:
        channel_id: Slack channel ID
        message_ts: Message timestamp
        command_type: Type of command that was processed
    """
    processed = SlackProcessedMessage(
        channel_id=channel_id,
        message_ts=message_ts,
        command_type=command_type,
    )
    db.session.add(processed)
    db.session.commit()


def message_has_keyword_trigger(
    text: str,
    trigger_keyword: Optional[str],
    bot_user_id: Optional[str] = None,
) -> tuple[bool, str]:
    """Check if message starts with trigger keyword or bot mention.

    Args:
        text: Message text
        trigger_keyword: Keyword to look for (e.g., "@aiops", "!issue")
        bot_user_id: Bot's Slack user ID for mention detection (e.g., "U0A38CEBSNN")

    Returns:
        Tuple of (is_triggered, cleaned_text with trigger removed)
    """
    text = text.strip()

    # Check for bot mention first (e.g., "<@U0A38CEBSNN> create issue")
    if bot_user_id:
        mention_pattern = f"<@{bot_user_id}>"
        if text.startswith(mention_pattern):
            cleaned = text[len(mention_pattern):].strip()
            return True, cleaned

    # Check for keyword trigger (e.g., "@aiops create issue" or "!issue create issue")
    if trigger_keyword and text.lower().startswith(trigger_keyword.lower()):
        cleaned = text[len(trigger_keyword):].strip()
        return True, cleaned

    return False, text


def find_messages_with_trigger(
    client: WebClient,
    channel_id: str,
    trigger_emoji: str,
    trigger_keyword: Optional[str] = None,
    bot_user_id: Optional[str] = None,
    oldest: Optional[str] = None,
) -> list[SlackMessage]:
    """Find all messages in a channel with the trigger emoji, keyword, or bot mention.

    Also checks thread replies for bot mentions (commands in threads).

    Args:
        client: Slack WebClient
        channel_id: Channel to search
        trigger_emoji: Emoji name that triggers issue creation
        trigger_keyword: Optional keyword prefix (e.g., "@aiops", "!issue")
        bot_user_id: Bot's Slack user ID for mention detection
        oldest: Only check messages after this timestamp

    Returns:
        List of SlackMessage objects for triggered messages
    """
    messages = get_channel_history(client, channel_id, oldest=oldest)
    triggered = []

    # Collect all messages to check (top-level + thread replies)
    all_messages = []
    for msg in messages:
        all_messages.append(msg)
        # If message has replies, fetch them too
        reply_count = msg.get("reply_count", 0)
        if reply_count > 0:
            thread_ts = msg.get("ts")
            replies = get_thread_replies(client, channel_id, thread_ts, oldest=oldest)
            all_messages.extend(replies)

    for msg in all_messages:
        message_ts = msg.get("ts")
        if not message_ts:
            continue

        # Skip if already processed
        if is_message_processed(channel_id, message_ts):
            continue

        user_id = msg.get("user", "")
        text = msg.get("text", "")
        thread_ts = msg.get("thread_ts")
        requester_id = user_id

        # Skip bot's own messages and system messages (subtypes like channel_join)
        if bot_user_id and user_id == bot_user_id:
            continue
        if msg.get("subtype"):  # Skip system messages (channel_join, bot_message, etc.)
            continue

        # Check for bot mention or keyword trigger first
        is_triggered, cleaned_text = message_has_keyword_trigger(
            text, trigger_keyword, bot_user_id
        )

        if is_triggered:
            text = cleaned_text
        else:
            # Fall back to emoji reaction trigger
            reactions = get_message_reactions(client, channel_id, message_ts)
            if has_trigger_reaction(reactions, trigger_emoji):
                is_triggered = True
                # Get the user who added the reaction (requester)
                requester_id = get_trigger_user(reactions, trigger_emoji) or user_id

        if is_triggered:
            permalink = get_message_permalink(client, channel_id, message_ts)

            triggered.append(
                SlackMessage(
                    channel_id=channel_id,
                    message_ts=message_ts,
                    user_id=requester_id,
                    text=text,
                    thread_ts=thread_ts,
                    permalink=permalink,
                )
            )

    return triggered


def create_issue_from_slack(
    slack_msg: SlackMessage,
    project_integration: ProjectIntegration,
    config: SlackIntegrationConfig,
    client: WebClient,
) -> ExternalIssue:
    """Create an aiops issue from a Slack message.

    Args:
        slack_msg: The Slack message to create issue from
        project_integration: Project integration to create issue under
        config: Slack integration configuration
        client: Slack WebClient

    Returns:
        Created ExternalIssue
    """
    # Ensure user mapping exists
    user_mapping = ensure_user_mapping(
        config.tenant_id, slack_msg.user_id, client
    )

    # Generate issue title from message (truncate if needed)
    title = slack_msg.text[:100].replace("\n", " ").strip()
    if len(slack_msg.text) > 100:
        title += "..."
    if not title:
        title = "Issue from Slack"

    # Create external issue
    issue = ExternalIssue(
        project_integration_id=project_integration.id,
        external_id=f"slack-{slack_msg.message_ts}",
        title=title,
        status="open",
        url=slack_msg.permalink,
        slack_channel_id=slack_msg.channel_id,
        slack_message_ts=slack_msg.message_ts,
        slack_requester_id=slack_msg.user_id,
        raw_payload={
            "source": "slack",
            "text": slack_msg.text,
            "thread_ts": slack_msg.thread_ts,
            "requester_display_name": user_mapping.slack_display_name,
        },
    )

    # Auto-assign if user is mapped
    if user_mapping.aiops_user_id:
        aiops_user = User.query.get(user_mapping.aiops_user_id)
        if aiops_user:
            issue.assignee = aiops_user.name

    db.session.add(issue)
    db.session.commit()

    logger.info(
        "Created issue %s from Slack message %s",
        issue.id,
        slack_msg.message_ts,
    )

    return issue


def post_thread_reply(
    client: WebClient,
    channel_id: str,
    thread_ts: str,
    message: str,
    mention_user_id: Optional[str] = None,
) -> bool:
    """Post a reply to a Slack thread.

    Args:
        client: Slack WebClient
        channel_id: Channel containing the thread
        thread_ts: Thread timestamp (original message ts)
        message: Message text to post
        mention_user_id: Optional user ID to @mention

    Returns:
        True if successful
    """
    try:
        if mention_user_id:
            message = f"<@{mention_user_id}> {message}"

        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=message,
        )
        return True
    except SlackApiError as e:
        logger.error(
            "Failed to post thread reply to %s/%s: %s",
            channel_id,
            thread_ts,
            e,
        )
        return False


def notify_issue_created(
    client: WebClient, issue: ExternalIssue, config: SlackIntegrationConfig
) -> bool:
    """Notify Slack thread that an issue was created.

    Args:
        client: Slack WebClient
        issue: The created issue
        config: Slack integration configuration

    Returns:
        True if notification sent successfully
    """
    if not issue.slack_channel_id or not issue.slack_message_ts:
        return False

    from flask import current_app

    base_url = current_app.config.get("AIOPS_BASE_URL", "").rstrip("/")
    if base_url:
        issue_url = f"{base_url}/admin/issues?highlight={issue.id}"
        message = f"Created issue <{issue_url}|#{issue.id}>: {issue.title}"
    else:
        message = f"Created issue #{issue.id}: {issue.title}"

    return post_thread_reply(
        client,
        issue.slack_channel_id,
        issue.slack_message_ts,
        message,
        mention_user_id=issue.slack_requester_id,
    )


def notify_issue_status_change(
    client: WebClient,
    issue: ExternalIssue,
    old_status: str,
    new_status: str,
) -> bool:
    """Notify Slack thread of an issue status change.

    Args:
        client: Slack WebClient
        issue: The issue that changed
        old_status: Previous status
        new_status: New status

    Returns:
        True if notification sent successfully
    """
    if not issue.slack_channel_id or not issue.slack_message_ts:
        return False

    message = f"Issue #{issue.id} status changed: {old_status} → {new_status}"

    return post_thread_reply(
        client,
        issue.slack_channel_id,
        issue.slack_message_ts,
        message,
        mention_user_id=issue.slack_requester_id,
    )


def notify_issue_closed(
    client: WebClient,
    issue: ExternalIssue,
    summary: Optional[str] = None,
) -> bool:
    """Notify Slack thread that an issue was closed.

    Args:
        client: Slack WebClient
        issue: The closed issue
        summary: Optional resolution summary

    Returns:
        True if notification sent successfully
    """
    if not issue.slack_channel_id or not issue.slack_message_ts:
        return False

    message = f"Issue #{issue.id} has been resolved"
    if summary:
        message += f"\n\n{summary}"

    return post_thread_reply(
        client,
        issue.slack_channel_id,
        issue.slack_message_ts,
        message,
        mention_user_id=issue.slack_requester_id,
    )


# ---------------------------------------------------------------------------
# Bot Command Handlers
# ---------------------------------------------------------------------------


def handle_help_command(
    client: WebClient,
    channel_id: str,
    thread_ts: str,
) -> None:
    """Send help message listing available commands.

    Args:
        client: Slack WebClient
        channel_id: Channel to post to
        thread_ts: Thread timestamp to reply to
    """
    help_text = """*Available Commands:*
• `@aiops <message>` - Create issue with message
• `@aiops in <project> <message>` - Create issue in specific project
• `@aiops list` - List open issues (default project)
• `@aiops list <project>` - List open issues for a project
• `@aiops list all` - List all open issues
• `@aiops close <id>` - Close an issue
• `@aiops delete <id>` - Delete an issue
• `@aiops help` - Show this help

*Issue Creation:*
You can also add a :ticket: reaction to any message to create an issue from it.

When Ollama preview is enabled, you'll see a preview before the issue is created. Confirm with :white_check_mark: or cancel with :x: reactions. You can also reply with `ok` or `cancel` instead of using reactions."""

    post_thread_reply(client, channel_id, thread_ts, help_text)


def handle_list_command(
    client: WebClient,
    channel_id: str,
    thread_ts: str,
    tenant_id: int,
    project_name: Optional[str],
    list_all: bool,
    default_project_id: Optional[int],
) -> None:
    """List issues and post results to Slack.

    Args:
        client: Slack WebClient
        channel_id: Channel to post to
        thread_ts: Thread timestamp to reply to
        tenant_id: Tenant ID to filter issues
        project_name: Optional project name to filter by
        list_all: If True, list all tenant issues
        default_project_id: Default project ID if no project specified
    """
    from ..models import Tenant

    # ExternalIssue -> ProjectIntegration -> Project, so we need to join
    query = (
        ExternalIssue.query
        .join(ProjectIntegration)
        .filter(ExternalIssue.status.in_(["open", "opened", "in_progress"]))
    )

    # Determine which project(s) to list
    if list_all:
        # All tenant issues - filter by tenant via project
        tenant = Tenant.query.get(tenant_id)
        if tenant:
            project_ids = [p.id for p in tenant.projects]
            query = query.filter(ProjectIntegration.project_id.in_(project_ids))
        project_label = "all projects"
    elif project_name:
        # Specific project by name
        project = Project.query.filter(
            Project.name.ilike(f"%{project_name}%")
        ).first()
        if not project:
            post_thread_reply(
                client, channel_id, thread_ts,
                f":warning: Project `{project_name}` not found."
            )
            return
        query = query.filter(ProjectIntegration.project_id == project.id)
        project_label = project.name
    elif default_project_id:
        # Default project
        project = Project.query.get(default_project_id)
        query = query.filter(ProjectIntegration.project_id == default_project_id)
        project_label = project.name if project else "default project"
    else:
        post_thread_reply(
            client, channel_id, thread_ts,
            ":warning: No default project configured. Use `list <project>` or `list all`."
        )
        return

    issues = query.order_by(ExternalIssue.created_at.desc()).limit(20).all()

    if not issues:
        post_thread_reply(
            client, channel_id, thread_ts,
            f":white_check_mark: No open issues in {project_label}."
        )
        return

    # Format issue list with clickable links
    from flask import current_app

    base_url = current_app.config.get("AIOPS_BASE_URL", "").rstrip("/")
    lines = [f"*Open Issues in {project_label}:* ({len(issues)} shown)"]
    for issue in issues:
        assignee = ""
        if issue.assignee:
            assignee = f" → {issue.assignee}"  # assignee is a string field
        title = issue.title[:50] + "..." if len(issue.title) > 50 else issue.title
        if base_url:
            issue_url = f"{base_url}/admin/issues?highlight={issue.id}"
            lines.append(f"• <{issue_url}|#{issue.id}> {title}{assignee}")
        else:
            lines.append(f"• `#{issue.id}` {title}{assignee}")

    post_thread_reply(client, channel_id, thread_ts, "\n".join(lines))


def handle_close_command(
    client: WebClient,
    channel_id: str,
    thread_ts: str,
    issue_id: int,
    tenant_id: int,
) -> None:
    """Close an issue and post confirmation.

    Args:
        client: Slack WebClient
        channel_id: Channel to post to
        thread_ts: Thread timestamp to reply to
        issue_id: Issue ID to close
        tenant_id: Tenant ID for authorization check
    """
    issue = ExternalIssue.query.get(issue_id)

    if not issue:
        post_thread_reply(
            client, channel_id, thread_ts,
            f":warning: Issue `#{issue_id}` not found."
        )
        return

    # Verify tenant access via project_integration -> project -> tenant
    project = issue.project_integration.project if issue.project_integration else None
    if project and project.tenant_id != tenant_id:
        post_thread_reply(
            client, channel_id, thread_ts,
            f":no_entry: You don't have access to issue `#{issue_id}`."
        )
        return

    if issue.status in ["closed", "done", "resolved"]:
        post_thread_reply(
            client, channel_id, thread_ts,
            f":information_source: Issue `#{issue_id}` is already closed."
        )
        return

    # Close the issue
    issue.status = "closed"
    issue.status_label = "Closed"
    db.session.commit()

    post_thread_reply(
        client, channel_id, thread_ts,
        f":white_check_mark: Closed issue `#{issue_id}`: {issue.title}"
    )


def handle_delete_command(
    client: WebClient,
    channel_id: str,
    thread_ts: str,
    issue_id: int,
    tenant_id: int,
) -> None:
    """Delete an issue and post confirmation.

    Args:
        client: Slack WebClient
        channel_id: Channel to post to
        thread_ts: Thread timestamp to reply to
        issue_id: Issue ID to delete
        tenant_id: Tenant ID for authorization check
    """
    issue = ExternalIssue.query.get(issue_id)

    if not issue:
        post_thread_reply(
            client, channel_id, thread_ts,
            f":warning: Issue `#{issue_id}` not found."
        )
        return

    # Verify tenant access via project_integration -> project -> tenant
    project = issue.project_integration.project if issue.project_integration else None
    if project and project.tenant_id != tenant_id:
        post_thread_reply(
            client, channel_id, thread_ts,
            f":no_entry: You don't have access to issue `#{issue_id}`."
        )
        return

    title = issue.title
    db.session.delete(issue)
    db.session.commit()

    post_thread_reply(
        client, channel_id, thread_ts,
        f":wastebasket: Deleted issue `#{issue_id}`: {title}"
    )


def handle_slack_command(
    client: WebClient,
    command: SlackCommand,
    slack_msg: SlackMessage,
    config: SlackIntegrationConfig,
    project_integration: ProjectIntegration,
) -> Optional[ExternalIssue]:
    """Handle a parsed Slack command.

    Args:
        client: Slack WebClient
        command: Parsed command
        slack_msg: Original Slack message
        config: Integration configuration
        project_integration: Project integration for issue creation

    Returns:
        Created issue if command was CREATE, None otherwise
    """
    # For DMs (channel starts with 'D'), don't use thread_ts - reply directly
    # For channels, use thread to keep conversations organized
    is_dm = slack_msg.channel_id.startswith(("D", "G"))  # D=DM, G=group DM
    if is_dm:
        thread_ts = None  # Reply directly in DM, not as thread
    else:
        thread_ts = slack_msg.thread_ts or slack_msg.message_ts

    if command.command_type == SlackCommandType.HELP:
        handle_help_command(client, slack_msg.channel_id, thread_ts)
        mark_message_processed(
            slack_msg.channel_id, slack_msg.message_ts, "help"
        )
        return None

    if command.command_type == SlackCommandType.LIST:
        handle_list_command(
            client,
            slack_msg.channel_id,
            thread_ts,
            config.tenant_id,
            command.project_name,
            command.list_all,
            config.default_project_id,
        )
        mark_message_processed(
            slack_msg.channel_id, slack_msg.message_ts, "list"
        )
        return None

    if command.command_type == SlackCommandType.CLOSE:
        handle_close_command(
            client,
            slack_msg.channel_id,
            thread_ts,
            command.issue_id,
            config.tenant_id,
        )
        mark_message_processed(
            slack_msg.channel_id, slack_msg.message_ts, "close"
        )
        return None

    if command.command_type == SlackCommandType.DELETE:
        handle_delete_command(
            client,
            slack_msg.channel_id,
            thread_ts,
            command.issue_id,
            config.tenant_id,
        )
        mark_message_processed(
            slack_msg.channel_id, slack_msg.message_ts, "delete"
        )
        return None

    if command.command_type == SlackCommandType.CONFIRM_PENDING:
        issue = handle_confirm_pending(client, slack_msg, config)
        if issue:
            mark_message_processed(
                slack_msg.channel_id, slack_msg.message_ts, "confirm_pending"
            )
        return issue

    if command.command_type == SlackCommandType.CANCEL_PENDING:
        handle_cancel_pending(client, slack_msg, config)
        mark_message_processed(
            slack_msg.channel_id, slack_msg.message_ts, "cancel_pending"
        )
        return None

    if command.command_type == SlackCommandType.CREATE:
        # Determine target project
        target_integration = project_integration
        target_project = Project.query.get(config.default_project_id)

        if command.project_name:
            # Find project by name within tenant
            project = Project.query.filter(
                Project.tenant_id == config.tenant_id,
                Project.name.ilike(f"%{command.project_name}%"),
            ).first()

            if not project:
                post_thread_reply(
                    client,
                    slack_msg.channel_id,
                    thread_ts,
                    f":warning: Project `{command.project_name}` not found. "
                    f"Creating issue in default project.",
                )
            else:
                target_project = project
                # Get or create project integration for this project
                target_integration = ProjectIntegration.query.filter_by(
                    project_id=project.id,
                    provider="slack",
                ).first()

                if not target_integration:
                    target_integration = ProjectIntegration(
                        project_id=project.id,
                        provider="slack",
                        provider_key="slack",
                        name=f"Slack ({project.name})",
                        enabled=True,
                        settings={
                            "tenant_integration_id": config.integration_id,
                        },
                    )
                    db.session.add(target_integration)
                    db.session.commit()

        # Check if Ollama preview is enabled
        from flask import current_app
        ollama_enabled = current_app.config.get("SLACK_OLLAMA_ENABLED", False)

        if ollama_enabled:
            # Mark message as processed BEFORE calling Ollama (which is slow)
            # to prevent duplicate processing on subsequent polls
            mark_message_processed(
                slack_msg.channel_id, slack_msg.message_ts, "ollama_preview"
            )
            # Use Ollama to elaborate and show preview
            return handle_create_with_ollama_preview(
                client,
                slack_msg,
                command,
                config,
                target_integration,
                target_project,
                thread_ts,
            )

        # Standard flow: create issue directly
        slack_msg_with_text = SlackMessage(
            channel_id=slack_msg.channel_id,
            message_ts=slack_msg.message_ts,
            user_id=slack_msg.user_id,
            text=command.message_text or slack_msg.text,
            thread_ts=slack_msg.thread_ts,
            permalink=slack_msg.permalink,
        )

        return create_issue_from_slack(
            slack_msg_with_text, target_integration, config, client
        )

    return None


def handle_create_with_ollama_preview(
    client: WebClient,
    slack_msg: SlackMessage,
    command: SlackCommand,
    config: SlackIntegrationConfig,
    project_integration: ProjectIntegration,
    project: Project,
    thread_ts: str | None,
) -> None:
    """Handle CREATE command with Ollama elaboration and preview.

    Posts a preview of the elaborated issue and stores it for confirmation.

    Args:
        client: Slack WebClient
        slack_msg: Original Slack message
        command: Parsed command
        config: Slack integration config
        project_integration: Target project integration
        project: Target project
        thread_ts: Thread timestamp for replies
    """
    from datetime import timedelta

    from .ollama_service import (
        OllamaServiceError,
        SlackIssueContext,
        elaborate_issue_for_slack,
    )

    brief_text = command.message_text or slack_msg.text

    # Get user info
    requester_name, requester_email = get_slack_user_info(client, slack_msg.user_id)

    # Get channel name
    channel_name = get_slack_channel_name(client, slack_msg.channel_id)

    # Get project context
    recent_issues = get_recent_project_issues(project.id, limit=10)
    common_labels = get_common_project_labels(project.id, limit=10)

    # Get tenant
    tenant = project.tenant

    # Get integration provider
    integration = TenantIntegration.query.get(config.integration_id)
    provider = integration.provider if integration else "slack"

    # Get global agent context
    from ..models import GlobalAgentContext
    global_context = GlobalAgentContext.query.order_by(
        GlobalAgentContext.updated_at.desc()
    ).first()
    global_agent_content = global_context.content if global_context else None

    # Get project AGENTS.md from repo
    project_agents_md = None
    try:
        from .git_service import read_file_from_repo
        project_agents_md = read_file_from_repo(project.id, "AGENTS.md")
    except Exception as e:
        logger.debug("Could not read AGENTS.md for project %s: %s", project.name, e)

    # Build context
    context = SlackIssueContext(
        brief_text=brief_text,
        requester_name=requester_name,
        requester_email=requester_email,
        channel_name=channel_name,
        channel_id=slack_msg.channel_id,
        timestamp=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        thread_context=None,  # TODO: Get parent message if in thread
        project_name=project.name,
        project_description=project.description,
        tenant_name=tenant.name if tenant else "Unknown",
        integration_provider=provider,
        recent_issue_titles=recent_issues,
        common_labels=common_labels,
        global_agent_context=global_agent_content,
        project_agents_md=project_agents_md,
    )

    try:
        # Call Ollama to elaborate (with timing)
        import time
        start_time = time.time()
        elaborated = elaborate_issue_for_slack(context)
        elapsed_time = time.time() - start_time
        title = elaborated["title"]
        description = elaborated["description"]
        logger.info("Ollama elaboration completed in %.2fs", elapsed_time)
    except OllamaServiceError as e:
        logger.warning("Ollama elaboration failed, falling back to direct creation: %s", e)
        # Fall back to direct creation
        slack_msg_with_text = SlackMessage(
            channel_id=slack_msg.channel_id,
            message_ts=slack_msg.message_ts,
            user_id=slack_msg.user_id,
            text=brief_text,
            thread_ts=slack_msg.thread_ts,
            permalink=slack_msg.permalink,
        )
        issue = create_issue_from_slack(
            slack_msg_with_text, project_integration, config, client
        )
        if issue:
            notify_issue_created(client, issue, config)
        return

    # Post preview message using Slack blocks for better formatting
    # Convert markdown-style formatting to Slack mrkdwn
    # Slack uses *bold*, _italic_, ~strikethrough~, `code`, ```code block```
    slack_description = description.replace("##", "*").replace("- [ ]", "☐")

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "📝 Issue Preview", "emoji": True}
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Title:*\n{title}"}
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Description:*\n{slack_description}"}
        },
        {"type": "divider"},
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"📁 *{project.name}* • React with ✅ to create this issue, or ❌ to cancel • _Generated in {elapsed_time:.1f}s_"
                }
            ]
        }
    ]

    # Fallback text for notifications
    fallback_text = f"Issue Preview: {title}"

    try:
        # Post the preview - for DMs, no thread_ts
        is_dm = slack_msg.channel_id.startswith(("D", "G"))  # D=DM, G=group DM
        response = client.chat_postMessage(
            channel=slack_msg.channel_id,
            text=fallback_text,
            blocks=blocks,
            thread_ts=None if is_dm else thread_ts,
        )
        preview_message_ts = response["ts"]
    except SlackApiError as e:
        logger.error("Failed to post preview message: %s", e)
        post_thread_reply(
            client,
            slack_msg.channel_id,
            thread_ts,
            f":x: Failed to create issue preview: {e}",
        )
        return

    # Store pending issue
    pending = SlackPendingIssue(
        channel_id=slack_msg.channel_id,
        preview_message_ts=preview_message_ts,
        original_message_ts=slack_msg.message_ts,
        title=title,
        description=description,
        project_integration_id=project_integration.id,
        integration_id=config.integration_id,
        created_by_slack_id=slack_msg.user_id,
        requester_name=requester_name,
        requester_email=requester_email,
        created_at=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(minutes=10),
    )
    db.session.add(pending)
    db.session.commit()

    # Note: message was already marked as processed before calling Ollama
    # to prevent duplicate processing during the slow Ollama call

    logger.info(
        "Posted Ollama preview for issue creation (pending_id=%d, preview_ts=%s)",
        pending.id,
        preview_message_ts,
    )


def get_recent_project_issues(project_id: int, limit: int = 10) -> list[str]:
    """Get recent issue titles for a project.

    Args:
        project_id: Project ID
        limit: Maximum number of issues to return

    Returns:
        List of recent issue titles
    """
    # ExternalIssue links to ProjectIntegration, which links to Project
    issues = (
        ExternalIssue.query.join(ProjectIntegration)
        .filter(ProjectIntegration.project_id == project_id)
        .order_by(ExternalIssue.created_at.desc())
        .limit(limit)
        .all()
    )
    return [i.title for i in issues]


def get_common_project_labels(project_id: int, limit: int = 10) -> list[str]:
    """Get commonly used labels for a project.

    Args:
        project_id: Project ID
        limit: Maximum number of labels to return

    Returns:
        List of common labels
    """
    # ExternalIssue links to ProjectIntegration, which links to Project
    issues = (
        ExternalIssue.query.join(ProjectIntegration)
        .filter(ProjectIntegration.project_id == project_id)
        .filter(ExternalIssue.labels.isnot(None))
        .order_by(ExternalIssue.created_at.desc())
        .limit(50)
        .all()
    )

    # Count label occurrences
    label_counts: dict[str, int] = {}
    for issue in issues:
        if issue.labels:
            for label in issue.labels:
                label_counts[label] = label_counts.get(label, 0) + 1

    # Sort by count and return top labels
    sorted_labels = sorted(label_counts.items(), key=lambda x: x[1], reverse=True)
    return [label for label, _ in sorted_labels[:limit]]


def get_slack_user_info(client: WebClient, user_id: str) -> tuple[str, str | None]:
    """Get Slack user's name and email.

    Args:
        client: Slack WebClient
        user_id: Slack user ID

    Returns:
        Tuple of (display_name, email or None)
    """
    try:
        response = client.users_info(user=user_id)
        user = response.get("user", {})
        profile = user.get("profile", {})

        # Prefer real_name, fall back to display_name
        name = profile.get("real_name") or profile.get("display_name") or user.get("name", "Unknown")
        email = profile.get("email")

        return name, email
    except SlackApiError as e:
        logger.warning("Failed to get user info for %s: %s", user_id, e)
        return "Unknown", None


def get_slack_channel_name(client: WebClient, channel_id: str) -> str:
    """Get Slack channel name.

    Args:
        client: Slack WebClient
        channel_id: Slack channel ID

    Returns:
        Channel name or channel ID if lookup fails
    """
    try:
        response = client.conversations_info(channel=channel_id)
        channel = response.get("channel", {})
        return channel.get("name", channel_id)
    except SlackApiError as e:
        logger.warning("Failed to get channel info for %s: %s", channel_id, e)
        return channel_id


def create_issue_from_pending(
    pending: SlackPendingIssue,
    client: WebClient,
    config: SlackIntegrationConfig,
) -> ExternalIssue:
    """Create an issue from a pending issue preview.

    Args:
        pending: SlackPendingIssue with elaborated content
        client: Slack WebClient
        config: Slack integration config

    Returns:
        Created ExternalIssue
    """
    # Get the project integration
    project_integration = ProjectIntegration.query.get(pending.project_integration_id)
    if not project_integration:
        raise SlackServiceError(f"Project integration {pending.project_integration_id} not found")

    # Create the issue
    issue = ExternalIssue(
        external_id=f"slack-{pending.preview_message_ts}",
        provider="slack",
        title=pending.title,
        description=pending.description,
        status="open",
        project_id=project_integration.project_id,
        integration_id=pending.integration_id,
        slack_channel_id=pending.channel_id,
        slack_message_ts=pending.original_message_ts or pending.preview_message_ts,
        created_at=datetime.utcnow(),
        raw_data={
            "created_via": "ollama_preview",
            "requester_slack_id": pending.created_by_slack_id,
            "requester_name": pending.requester_name,
            "requester_email": pending.requester_email,
        },
    )

    # Try to assign to the Slack user if mapped
    if pending.requester_email:
        user = User.query.filter_by(email=pending.requester_email).first()
        if user:
            issue.assignee = user.display_name or user.email

    db.session.add(issue)
    db.session.commit()

    logger.info("Created issue #%d from pending preview %s", issue.id, pending.preview_message_ts)
    return issue


def find_pending_issue_for_user(
    channel_id: str,
    user_id: str,
    thread_ts: str | None,
) -> SlackPendingIssue | None:
    """Find the pending issue a user is responding to.

    Args:
        channel_id: Slack channel ID
        user_id: Slack user ID
        thread_ts: Thread timestamp if replying in thread

    Returns:
        SlackPendingIssue or None if not found
    """
    if thread_ts:
        # In a thread - the thread_ts is the preview message timestamp
        pending = SlackPendingIssue.query.filter_by(
            preview_message_ts=thread_ts,
            created_by_slack_id=user_id,
        ).first()
        if pending:
            return pending

    # In DM or channel - find most recent non-expired pending for this user in this channel
    return (
        SlackPendingIssue.query.filter(
            SlackPendingIssue.channel_id == channel_id,
            SlackPendingIssue.created_by_slack_id == user_id,
            SlackPendingIssue.expires_at > datetime.utcnow(),
        )
        .order_by(SlackPendingIssue.created_at.desc())
        .first()
    )


def handle_confirm_pending(
    client: WebClient,
    slack_msg: SlackMessage,
    config: SlackIntegrationConfig,
) -> ExternalIssue | None:
    """Handle confirm command (ok/yes) for pending issue.

    Args:
        client: Slack WebClient
        slack_msg: The confirm message
        config: Slack integration config

    Returns:
        Created ExternalIssue or None if no pending found
    """
    pending = find_pending_issue_for_user(
        slack_msg.channel_id,
        slack_msg.user_id,
        slack_msg.thread_ts,
    )

    if not pending:
        # No pending issue found - inform user
        is_dm = slack_msg.channel_id.startswith(("D", "G"))  # D=DM, G=group DM
        thread_ts = None if is_dm else (slack_msg.thread_ts or slack_msg.message_ts)
        client.chat_postMessage(
            channel=slack_msg.channel_id,
            text="No pending issue preview found. Create one first with a message.",
            thread_ts=thread_ts,
        )
        mark_message_processed(slack_msg.channel_id, slack_msg.message_ts, "confirm_no_pending")
        return None

    try:
        # Create the issue
        issue = create_issue_from_pending(pending, client, config)
        notify_issue_created(client, issue, config)

        # Reply to confirm
        is_dm = slack_msg.channel_id.startswith(("D", "G"))  # D=DM, G=group DM
        client.chat_postMessage(
            channel=slack_msg.channel_id,
            text=f"✅ Issue created: #{issue.id}",
            thread_ts=None if is_dm else pending.preview_message_ts,
        )

        # Delete pending
        db.session.delete(pending)
        db.session.commit()

        mark_message_processed(slack_msg.channel_id, slack_msg.message_ts, "confirm_pending")
        logger.info("Created issue #%d from text confirm", issue.id)
        return issue

    except Exception as e:
        logger.error("Failed to create issue from text confirm: %s", e)
        client.chat_postMessage(
            channel=slack_msg.channel_id,
            text=f"❌ Failed to create issue: {e}",
            thread_ts=slack_msg.thread_ts or slack_msg.message_ts,
        )
        mark_message_processed(slack_msg.channel_id, slack_msg.message_ts, "confirm_error")
        return None


def handle_cancel_pending(
    client: WebClient,
    slack_msg: SlackMessage,
    config: SlackIntegrationConfig,
) -> None:
    """Handle cancel command (cancel/no) for pending issue.

    Args:
        client: Slack WebClient
        slack_msg: The cancel message
        config: Slack integration config
    """
    pending = find_pending_issue_for_user(
        slack_msg.channel_id,
        slack_msg.user_id,
        slack_msg.thread_ts,
    )

    if not pending:
        # No pending issue found - inform user
        is_dm = slack_msg.channel_id.startswith(("D", "G"))  # D=DM, G=group DM
        thread_ts = None if is_dm else (slack_msg.thread_ts or slack_msg.message_ts)
        client.chat_postMessage(
            channel=slack_msg.channel_id,
            text="No pending issue preview to cancel.",
            thread_ts=thread_ts,
        )
        mark_message_processed(slack_msg.channel_id, slack_msg.message_ts, "cancel_no_pending")
        return

    # Delete pending and confirm
    is_dm = slack_msg.channel_id.startswith(("D", "G"))  # D=DM, G=group DM
    client.chat_postMessage(
        channel=slack_msg.channel_id,
        text="❌ Issue creation cancelled.",
        thread_ts=None if is_dm else pending.preview_message_ts,
    )

    db.session.delete(pending)
    db.session.commit()

    mark_message_processed(slack_msg.channel_id, slack_msg.message_ts, "cancel_pending")
    logger.info("Cancelled pending issue %d via text command", pending.id)


def poll_pending_issue_reactions(
    client: WebClient,
    config: SlackIntegrationConfig,
    project_integration: ProjectIntegration,
) -> dict[str, Any]:
    """Poll reactions on pending issue previews.

    Checks for ✅ (confirm) or ❌ (cancel) reactions on preview messages
    and creates or cancels issues accordingly.

    Args:
        client: Slack WebClient
        config: Slack integration config
        project_integration: Project integration for issue creation

    Returns:
        Dict with results: {created: int, cancelled: int, expired: int, errors: list}
    """
    results = {"created": 0, "cancelled": 0, "expired": 0, "errors": []}

    # Get all non-expired pending issues for this integration
    pending_issues = SlackPendingIssue.query.filter(
        SlackPendingIssue.integration_id == config.integration_id,
        SlackPendingIssue.expires_at > datetime.utcnow(),
    ).all()

    for pending in pending_issues:
        try:
            # Get reactions on the preview message
            reactions = get_message_reactions(
                client, pending.channel_id, pending.preview_message_ts
            )

            reaction_names = [r.get("name", "") for r in reactions]

            if "white_check_mark" in reaction_names:  # ✅
                # Create the issue
                try:
                    issue = create_issue_from_pending(pending, client, config)
                    notify_issue_created(client, issue, config)

                    # Reply in thread to confirm
                    client.chat_postMessage(
                        channel=pending.channel_id,
                        text=f"✅ Issue created: #{issue.id}",
                        thread_ts=pending.preview_message_ts,
                    )

                    db.session.delete(pending)
                    db.session.commit()
                    results["created"] += 1
                    logger.info("Created issue from pending %s", pending.id)
                except Exception as e:
                    error_msg = f"Failed to create issue from pending {pending.id}: {e}"
                    logger.error(error_msg)
                    results["errors"].append(error_msg)

            elif "x" in reaction_names:  # ❌
                # Cancel
                try:
                    client.chat_postMessage(
                        channel=pending.channel_id,
                        text="❌ Issue creation cancelled.",
                        thread_ts=pending.preview_message_ts,
                    )
                except SlackApiError as e:
                    logger.warning("Failed to post cancellation message: %s", e)

                db.session.delete(pending)
                db.session.commit()
                results["cancelled"] += 1
                logger.info("Cancelled pending issue %s", pending.id)

        except Exception as e:
            error_msg = f"Error checking reactions for pending {pending.id}: {e}"
            logger.warning(error_msg)
            results["errors"].append(error_msg)

    # Clean up expired pending issues
    expired_issues = SlackPendingIssue.query.filter(
        SlackPendingIssue.expires_at <= datetime.utcnow()
    ).all()

    for expired in expired_issues:
        try:
            client.chat_postMessage(
                channel=expired.channel_id,
                text="⏰ Issue preview expired (10 minute timeout). Please create a new request.",
                thread_ts=expired.preview_message_ts,
            )
        except SlackApiError as e:
            logger.warning("Failed to post expiration message: %s", e)

        db.session.delete(expired)
        results["expired"] += 1
        logger.info("Expired pending issue %s", expired.id)

    if expired_issues:
        db.session.commit()

    return results


def poll_integration(config: SlackIntegrationConfig) -> dict[str, Any]:
    """Poll a single Slack integration for new messages to process.

    Args:
        config: Slack integration configuration

    Returns:
        Dict with polling results: {processed: int, errors: list}
    """
    results = {"processed": 0, "errors": []}

    try:
        client = get_slack_client(config.bot_token)
    except Exception as e:
        results["errors"].append(f"Failed to create Slack client: {e}")
        return results

    # Get the project integration for creating issues
    if not config.default_project_id:
        results["errors"].append("No default_project_id configured")
        return results

    project = Project.query.get(config.default_project_id)
    if not project:
        results["errors"].append(
            f"Project {config.default_project_id} not found"
        )
        return results

    # Find or create a project integration for Slack issues
    project_integration = ProjectIntegration.query.filter_by(
        project_id=config.default_project_id,
        integration_id=config.integration_id,
    ).first()

    if not project_integration:
        # Create a project integration for Slack
        project_integration = ProjectIntegration(
            project_id=config.default_project_id,
            integration_id=config.integration_id,
            external_identifier="slack",
            config={},
        )
        db.session.add(project_integration)
        db.session.commit()

    # Poll each configured channel
    for channel_id in config.channels:
        try:
            triggered_messages = find_messages_with_trigger(
                client,
                channel_id,
                config.trigger_emoji,
                config.trigger_keyword,
                config.bot_user_id,
            )

            for slack_msg in triggered_messages:
                try:
                    # Parse command from message text
                    command = parse_slack_command(slack_msg.text)

                    # Handle the command
                    issue = handle_slack_command(
                        client,
                        command,
                        slack_msg,
                        config,
                        project_integration,
                    )

                    # Only notify and count for CREATE commands that succeeded
                    if issue:
                        notify_issue_created(client, issue, config)
                        results["processed"] += 1

                except Exception as e:
                    error_msg = f"Failed to process message {slack_msg.message_ts}: {e}"
                    logger.error(error_msg)
                    results["errors"].append(error_msg)

        except SlackChannelError as e:
            results["errors"].append(str(e))
        except Exception as e:
            error_msg = f"Error polling channel {channel_id}: {e}"
            logger.error(error_msg)
            results["errors"].append(error_msg)

    # Poll reactions on pending issue previews (Ollama flow)
    try:
        from flask import current_app
        if current_app.config.get("SLACK_OLLAMA_ENABLED", False):
            pending_results = poll_pending_issue_reactions(
                client, config, project_integration
            )
            results["processed"] += pending_results.get("created", 0)
            results["errors"].extend(pending_results.get("errors", []))
            if pending_results.get("created", 0) > 0:
                logger.info(
                    "Pending issues: %d created, %d cancelled, %d expired",
                    pending_results.get("created", 0),
                    pending_results.get("cancelled", 0),
                    pending_results.get("expired", 0),
                )
    except Exception as e:
        logger.warning("Failed to poll pending issue reactions: %s", e)

    return results


def get_bot_dm_channels(client: WebClient) -> list[str]:
    """Get list of DM channel IDs where users have messaged the bot.

    Args:
        client: Slack WebClient

    Returns:
        List of DM channel IDs (im channels)
    """
    try:
        # List all IM (direct message) and MPIM (group DM) conversations the bot is part of
        # Requires scopes: im:read, mpim:read
        response = client.conversations_list(
            types="im,mpim",
            limit=100,
        )
        channels = response.get("channels", [])
        # Return channel IDs for DMs that are open
        return [ch["id"] for ch in channels if not ch.get("is_archived", False)]
    except SlackApiError as e:
        logger.warning("Failed to list bot DM channels: %s", e)
        return []


def poll_dm_messages(
    client: WebClient,
    config: SlackIntegrationConfig,
    project_integration: ProjectIntegration,
) -> dict[str, Any]:
    """Poll bot's DM channels for commands.

    In DMs, users don't need to use @aiops prefix - all messages are treated as commands.

    Args:
        client: Slack WebClient
        config: Slack integration configuration
        project_integration: Project integration for issue operations

    Returns:
        Dict with polling results: {processed: int, errors: list}
    """
    results = {"processed": 0, "errors": []}

    dm_channels = get_bot_dm_channels(client)
    if not dm_channels:
        return results

    logger.debug("Polling %d DM channels", len(dm_channels))

    for channel_id in dm_channels:
        try:
            # Get recent messages from DM
            messages = get_channel_history(client, channel_id, limit=10)

            for msg in messages:
                message_ts = msg.get("ts", "")
                user_id = msg.get("user", "")
                text = msg.get("text", "").strip()

                # Skip if no text or no user
                if not text or not user_id:
                    continue

                # Skip bot's own messages
                if config.bot_user_id and user_id == config.bot_user_id:
                    continue

                # Skip already processed messages
                if is_message_processed(channel_id, message_ts):
                    continue

                # In DMs, treat all messages as commands (no @mention needed)
                # Parse the command directly
                command = parse_slack_command(text)

                # Create SlackMessage for the handler
                permalink = get_message_permalink(client, channel_id, message_ts)
                slack_msg = SlackMessage(
                    channel_id=channel_id,
                    message_ts=message_ts,
                    user_id=user_id,
                    text=text,
                    thread_ts=None,  # DMs don't have threads in the same way
                    permalink=permalink,
                )

                try:
                    # Handle the command
                    issue = handle_slack_command(
                        client,
                        command,
                        slack_msg,
                        config,
                        project_integration,
                    )

                    # Only count CREATE commands that succeeded
                    if issue:
                        notify_issue_created(client, issue, config)
                        results["processed"] += 1

                except Exception as e:
                    error_msg = f"Failed to process DM message {message_ts}: {e}"
                    logger.error(error_msg)
                    results["errors"].append(error_msg)

        except Exception as e:
            error_msg = f"Error polling DM channel {channel_id}: {e}"
            logger.warning(error_msg)
            results["errors"].append(error_msg)

    return results


def poll_all_integrations() -> dict[str, Any]:
    """Poll all enabled Slack integrations including DMs.

    Returns:
        Dict with overall results: {total_processed: int, errors: list}
    """
    configs = get_slack_integrations()

    if not configs:
        logger.debug("No Slack integrations configured")
        return {"total_processed": 0, "errors": []}

    logger.info("Polling %d Slack integrations", len(configs))

    total_results = {"total_processed": 0, "errors": []}

    for config in configs:
        try:
            # Poll configured channels
            results = poll_integration(config)
            total_results["total_processed"] += results["processed"]
            total_results["errors"].extend(results["errors"])

            # Also poll DMs for this integration
            try:
                client = get_slack_client(config.bot_token)
                # Get or create project integration for DM commands
                if config.default_project_id:
                    project_integration = ProjectIntegration.query.filter_by(
                        project_id=config.default_project_id,
                        integration_id=config.integration_id,
                    ).first()
                    if project_integration:
                        dm_results = poll_dm_messages(client, config, project_integration)
                        total_results["total_processed"] += dm_results["processed"]
                        total_results["errors"].extend(dm_results["errors"])
            except Exception as e:
                logger.warning("Failed to poll DMs for integration %s: %s", config.integration_id, e)

        except Exception as e:
            error_msg = f"Failed to poll integration {config.integration_id}: {e}"
            logger.exception(error_msg)
            total_results["errors"].append(error_msg)

    logger.info(
        "Slack polling complete: %d issues created, %d errors",
        total_results["total_processed"],
        len(total_results["errors"]),
    )

    return total_results


def get_slack_user_mappings(tenant_id: int) -> list[SlackUserMapping]:
    """Get all Slack user mappings for a tenant.

    Args:
        tenant_id: Tenant ID

    Returns:
        List of SlackUserMapping instances
    """
    return (
        SlackUserMapping.query.filter_by(tenant_id=tenant_id)
        .order_by(SlackUserMapping.slack_display_name)
        .all()
    )


def update_user_mapping(
    mapping_id: int,
    aiops_user_id: Optional[int],
) -> SlackUserMapping:
    """Update a Slack user mapping to link/unlink an aiops user.

    Args:
        mapping_id: SlackUserMapping ID
        aiops_user_id: aiops User ID to link (None to unlink)

    Returns:
        Updated SlackUserMapping

    Raises:
        SlackServiceError: If mapping not found
    """
    mapping = SlackUserMapping.query.get(mapping_id)
    if not mapping:
        raise SlackServiceError(f"Mapping {mapping_id} not found")

    mapping.aiops_user_id = aiops_user_id
    mapping.updated_at = datetime.utcnow()
    db.session.commit()

    return mapping


def test_slack_connection(bot_token: str) -> dict[str, Any]:
    """Test Slack API connection with the given bot token.

    Args:
        bot_token: Slack Bot OAuth token

    Returns:
        Dict with connection status and bot info
    """
    try:
        client = get_slack_client(bot_token)
        response = client.auth_test()

        return {
            "ok": True,
            "team": response.get("team"),
            "team_id": response.get("team_id"),
            "bot_user_id": response.get("user_id"),
            "bot_user": response.get("user"),
        }
    except SlackApiError as e:
        return {
            "ok": False,
            "error": str(e),
        }


def list_bot_channels(bot_token: str) -> list[dict[str, str]]:
    """List channels the bot has access to.

    Args:
        bot_token: Slack Bot OAuth token

    Returns:
        List of channel info dicts with id and name
    """
    try:
        client = get_slack_client(bot_token)
        response = client.conversations_list(
            types="public_channel,private_channel",
            exclude_archived=True,
        )

        channels = []
        for channel in response.get("channels", []):
            if channel.get("is_member"):
                channels.append({
                    "id": channel["id"],
                    "name": channel["name"],
                    "is_private": channel.get("is_private", False),
                })

        return channels
    except SlackApiError as e:
        logger.error("Failed to list channels: %s", e)
        return []
