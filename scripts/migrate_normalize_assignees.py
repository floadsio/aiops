#!/usr/bin/env python3
"""
Migration script to normalize existing assignee names in the database.

This script applies the assignee normalization logic to all existing issues,
removing organizational suffixes like "(Floads)" and normalizing whitespace.

Run with:
    python scripts/migrate_normalize_assignees.py [--dry-run]
"""
import argparse
import sys
from pathlib import Path

# Add app to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app import create_app
from app.extensions import db
from app.models import ExternalIssue
from app.services.issues.utils import normalize_assignee_name


def migrate_assignees(dry_run: bool = False) -> None:
    """Normalize all assignee names in the database."""
    app = create_app()

    with app.app_context():
        # Get all issues with assignees
        issues = ExternalIssue.query.filter(
            ExternalIssue.assignee.isnot(None)
        ).all()

        total_issues = len(issues)
        updated_count = 0
        changes: list[tuple[str, str]] = []

        print(f"Found {total_issues} issues with assignees")
        print()

        for issue in issues:
            original = issue.assignee
            normalized = normalize_assignee_name(original)

            if normalized != original:
                changes.append((original, normalized or ""))
                if not dry_run:
                    issue.assignee = normalized
                    updated_count += 1

        # Show unique changes
        unique_changes = sorted(set(changes))
        if unique_changes:
            print(f"{'DRY RUN: ' if dry_run else ''}Changes to be applied:")
            for old_name, new_name in unique_changes:
                print(f"  '{old_name}' → '{new_name}'")
            print()

        if dry_run:
            print(f"DRY RUN: Would update {len(changes)} issue(s)")
            print("Run without --dry-run to apply changes")
        else:
            db.session.commit()
            print(f"✓ Updated {updated_count} issue(s)")
            print(f"✓ {len(unique_changes)} unique assignee name(s) normalized")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Normalize assignee names in existing issues"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed without modifying the database",
    )
    args = parser.parse_args()

    migrate_assignees(dry_run=args.dry_run)
