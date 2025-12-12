"""Slack integration service for polling-based issue creation and notifications.

This service handles:
- Polling Slack channels for messages with trigger emoji reactions
- Creating issues from flagged Slack messages
- Posting updates to Slack threads when issue status changes
- Managing Slack user to aiops user mappings
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from ..extensions import db
from ..models import (
    ExternalIssue,
    Project,
    ProjectIntegration,
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


def get_channel_history(
    client: WebClient,
    channel_id: str,
    oldest: Optional[str] = None,
    limit: int = 100,
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
    try:
        response = client.reactions_get(
            channel=channel_id,
            timestamp=message_ts,
        )
        message = response.get("message", {})
        return message.get("reactions", [])
    except SlackApiError as e:
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
    """Check if a message has already been processed into an issue.

    Args:
        channel_id: Slack channel ID
        message_ts: Message timestamp

    Returns:
        True if an issue exists with this Slack context
    """
    existing = ExternalIssue.query.filter_by(
        slack_channel_id=channel_id,
        slack_message_ts=message_ts,
    ).first()
    return existing is not None


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

    for msg in messages:
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
                    issue = create_issue_from_slack(
                        slack_msg,
                        project_integration,
                        config,
                        client,
                    )
                    notify_issue_created(client, issue, config)
                    results["processed"] += 1

                except Exception as e:
                    error_msg = f"Failed to create issue from {slack_msg.message_ts}: {e}"
                    logger.error(error_msg)
                    results["errors"].append(error_msg)

        except SlackChannelError as e:
            results["errors"].append(str(e))
        except Exception as e:
            error_msg = f"Error polling channel {channel_id}: {e}"
            logger.error(error_msg)
            results["errors"].append(error_msg)

    return results


def poll_all_integrations() -> dict[str, Any]:
    """Poll all enabled Slack integrations.

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
            results = poll_integration(config)
            total_results["total_processed"] += results["processed"]
            total_results["errors"].extend(results["errors"])

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
