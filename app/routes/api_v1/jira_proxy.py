"""Jira image proxy endpoint.

Proxies Jira attachment images to avoid CORS and authentication issues.
"""

import requests
from flask import current_app, request, Response

from app.auth import require_api_auth
from app.models import TenantIntegration
from . import api_v1_bp


@api_v1_bp.get("/jira/attachment/<int:integration_id>/<path:attachment_path>")
@require_api_auth(scopes=["read"])
def proxy_jira_attachment(integration_id: int, attachment_path: str):
    """Proxy a Jira attachment image.

    This endpoint fetches images from Jira using the stored API credentials
    and serves them to the frontend, avoiding CORS and cookie authentication issues.

    Args:
        integration_id: The Jira integration ID
        attachment_path: The Jira attachment path (e.g., rest/api/3/attachment/content/12345)

    Returns:
        The image data with appropriate content-type header
    """
    try:
        # Get the Jira integration
        integration = TenantIntegration.query.get(integration_id)
        if not integration or integration.provider.lower() != "jira":
            return {"error": "Invalid Jira integration"}, 404

        # Build the full URL
        base_url = integration.base_url
        if not base_url:
            return {"error": "Integration missing base URL"}, 500

        # Ensure attachment_path starts with /
        if not attachment_path.startswith("/"):
            attachment_path = "/" + attachment_path

        url = f"{base_url}{attachment_path}"

        # Get Jira credentials from integration settings
        settings = integration.settings or {}
        username = settings.get("username")
        api_token = integration.api_token

        if not username or not api_token:
            return {"error": "Integration missing credentials"}, 500

        # Fetch the image from Jira
        response = requests.get(
            url,
            auth=(username, api_token),
            timeout=30,
            stream=True,
        )

        if response.status_code != 200:
            current_app.logger.error(
                f"Failed to fetch Jira attachment: {response.status_code} from {url}"
            )
            return {"error": "Failed to fetch attachment from Jira"}, response.status_code

        # Return the image with appropriate headers
        return Response(
            response.content,
            content_type=response.headers.get("Content-Type", "image/png"),
            headers={
                "Cache-Control": "public, max-age=3600",  # Cache for 1 hour
            },
        )

    except Exception as exc:  # noqa: BLE001
        current_app.logger.error(f"Error proxying Jira attachment: {exc}")
        return {"error": "Internal server error"}, 500
