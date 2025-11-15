#!/usr/bin/env python3
"""Diagnostic script to test GitHub issue creation setup."""

from __future__ import annotations

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app import create_app
from app.models import Project


def diagnose_github_integration(project_id: int):
    """Diagnose GitHub integration setup for a project."""
    app = create_app()
    with app.app_context():
        project = Project.query.get(project_id)
        if not project:
            print(f"❌ Project {project_id} not found")
            return

        print(f"✅ Project: {project.name}")
        print(f"   Tenant: {project.tenant.name if project.tenant else 'None'}")
        print()

        # Check integrations
        github_integrations = [
            link
            for link in project.issue_integrations
            if link.integration
            and link.integration.provider
            and link.integration.provider.lower() == "github"
        ]

        if not github_integrations:
            print("❌ No GitHub integrations found for this project")
            print("   Add a GitHub integration in Admin → Integrations")
            return

        for link in github_integrations:
            integration = link.integration
            print(f"📦 Integration: {integration.name}")
            print(f"   Provider: {integration.provider}")
            print(f"   Enabled: {integration.enabled}")
            print(f"   Has API token: {'Yes' if integration.api_token else 'No'}")
            print(f"   Repository: {link.external_identifier or 'NOT SET'}")
            print()

            if not integration.enabled:
                print("   ⚠️  Integration is disabled")
                continue

            if not integration.api_token:
                print("   ❌ No API token configured")
                continue

            if not link.external_identifier:
                print("   ❌ No repository identifier set (should be owner/repo)")
                continue

            # Test API connection
            print("   Testing GitHub API connection...")
            try:
                from github import Github

                client = Github(integration.api_token)
                user = client.get_user()
                print(f"   ✅ Authenticated as: {user.login}")

                # Test repo access
                try:
                    repo = client.get_repo(link.external_identifier)
                    print(f"   ✅ Repository accessible: {repo.full_name}")
                    print(f"   ✅ Permissions: {repo.permissions}")

                    # Check if we can create issues
                    if hasattr(repo.permissions, "push") and repo.permissions.push:
                        print("   ✅ Can create issues (has push permission)")
                    else:
                        print("   ⚠️  May not have permission to create issues")

                except Exception as e:
                    print(f"   ❌ Cannot access repository: {e}")

            except ImportError:
                print("   ❌ PyGithub not installed")
            except Exception as e:
                print(f"   ❌ GitHub API error: {e}")

            print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/diagnose_github_issue_creation.py <project_id>")
        sys.exit(1)

    try:
        project_id = int(sys.argv[1])
    except ValueError:
        print("Error: project_id must be an integer")
        sys.exit(1)

    diagnose_github_integration(project_id)
