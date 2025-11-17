"""Swagger/OpenAPI configuration for API documentation."""

from flasgger import Swagger  # type: ignore

SWAGGER_CONFIG = {
    "headers": [],
    "specs": [
        {
            "endpoint": "apispec_1",
            "route": "/api/v1/apispec.json",
            "rule_filter": lambda rule: rule.rule.startswith("/api/v1"),
            "model_filter": lambda tag: True,
        }
    ],
    "static_url_path": "/flasgger_static",
    "swagger_ui": True,
    "specs_route": "/api/docs",
}

SWAGGER_TEMPLATE = {
    "swagger": "2.0",
    "info": {
        "title": "AIops REST API",
        "description": (
            "A comprehensive REST API for programmatic access to AIops functionality. "
            "This API allows AI agents and CLI clients to manage issues, git repositories, "
            "projects, tenants, and execute automated workflows."
        ),
        "contact": {
            "name": "AIops Support",
            "url": "https://github.com/exampleorg/aiops",
        },
        "version": "1.0.0",
    },
    "host": "",  # Will be set dynamically
    "basePath": "/api/v1",
    "schemes": ["http", "https"],
    "securityDefinitions": {
        "Bearer": {
            "type": "apiKey",
            "name": "Authorization",
            "in": "header",
            "description": (
                'API key authentication. Use format: "Bearer aiops_your_api_key_here". '
                "You can also use the X-API-Key header."
            ),
        },
        "ApiKeyHeader": {
            "type": "apiKey",
            "name": "X-API-Key",
            "in": "header",
            "description": "Alternative API key authentication via X-API-Key header.",
        },
    },
    "security": [{"Bearer": []}, {"ApiKeyHeader": []}],
    "tags": [
        {
            "name": "Authentication",
            "description": "API key management and user authentication",
        },
        {
            "name": "Tenants",
            "description": "Tenant management operations",
        },
        {
            "name": "Projects",
            "description": "Project management operations",
        },
        {
            "name": "Issues",
            "description": "Issue tracking across GitHub, GitLab, and Jira",
        },
        {
            "name": "Git Operations",
            "description": "Git repository operations (pull, push, commit, branches)",
        },
        {
            "name": "Workflows",
            "description": "High-level AI agent workflows for issue management",
        },
    ],
}


def init_swagger(app):
    """Initialize Swagger documentation for the Flask app.

    Args:
        app: Flask application instance
    """
    # Set host dynamically based on server
    SWAGGER_TEMPLATE["host"] = app.config.get("SERVER_NAME", "localhost:5000")

    swagger = Swagger(app, config=SWAGGER_CONFIG, template=SWAGGER_TEMPLATE)
    return swagger
