"""Activity log cleanup service for managing database size.

This service provides functionality to clean up old activity logs to prevent
the database from growing too large over time.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from flask import current_app

from ..extensions import db
from ..models import Activity


class ActivityCleanupError(Exception):
    """Raised when activity cleanup operations fail."""

    pass


def cleanup_old_activities(
    days_to_keep: int = 90,
    max_records_to_keep: Optional[int] = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """Clean up old activity log entries.

    Args:
        days_to_keep: Number of days of activity to retain (default: 90)
        max_records_to_keep: Maximum number of records to keep regardless of age
                           (optional, keeps most recent records)
        dry_run: If True, only count records that would be deleted without deleting

    Returns:
        dict with cleanup statistics:
            - total_before: Total activities before cleanup
            - deleted: Number of activities deleted
            - total_after: Total activities after cleanup
            - oldest_kept: Timestamp of oldest kept activity

    Examples:
        # Delete activities older than 90 days
        cleanup_old_activities(days_to_keep=90)

        # Keep only last 10,000 activities
        cleanup_old_activities(max_records_to_keep=10000)

        # Keep last 90 days OR last 50,000 records (whichever is more)
        cleanup_old_activities(days_to_keep=90, max_records_to_keep=50000)
    """
    try:
        total_before = Activity.query.count()

        if total_before == 0:
            return {
                "total_before": 0,
                "deleted": 0,
                "total_after": 0,
                "oldest_kept": None,
            }

        # Calculate cutoff date
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_to_keep)

        # Build delete query
        delete_query = Activity.query.filter(Activity.created_at < cutoff_date)

        # If max_records_to_keep is specified, ensure we keep at least that many
        if max_records_to_keep is not None:
            # Get the Nth most recent record
            nth_record = (
                Activity.query.order_by(Activity.created_at.desc())
                .offset(max_records_to_keep)
                .first()
            )

            if nth_record:
                # Only delete records older than both cutoff_date AND the Nth record
                delete_query = delete_query.filter(
                    Activity.created_at < nth_record.created_at
                )

        # Count records to be deleted
        to_delete = delete_query.count()

        if dry_run:
            if current_app:
                current_app.logger.info(
                    f"[DRY RUN] Would delete {to_delete} activities older than {cutoff_date}"
                )
            deleted = 0
        else:
            # Perform deletion
            deleted = delete_query.delete(synchronize_session=False)
            db.session.commit()

            if current_app:
                current_app.logger.info(
                    f"Deleted {deleted} activities older than {cutoff_date}"
                )

        total_after = Activity.query.count()

        # Get oldest kept activity
        oldest_kept_activity = Activity.query.order_by(Activity.created_at.asc()).first()
        oldest_kept = (
            oldest_kept_activity.created_at if oldest_kept_activity else None
        )

        return {
            "total_before": total_before,
            "deleted": deleted,
            "total_after": total_after,
            "oldest_kept": oldest_kept,
        }

    except Exception as e:
        db.session.rollback()
        if current_app:
            current_app.logger.error(f"Activity cleanup failed: {e}")
        raise ActivityCleanupError(f"Failed to clean up activities: {e}") from e


def get_cleanup_stats() -> dict[str, any]:
    """Get statistics about activity log for cleanup planning.

    Returns:
        dict with statistics:
            - total_count: Total number of activities
            - oldest_activity: Timestamp of oldest activity
            - newest_activity: Timestamp of newest activity
            - age_days: Age of oldest activity in days
            - size_estimate_mb: Estimated database size in MB
    """
    total_count = Activity.query.count()

    if total_count == 0:
        return {
            "total_count": 0,
            "oldest_activity": None,
            "newest_activity": None,
            "age_days": 0,
            "size_estimate_mb": 0,
        }

    oldest = Activity.query.order_by(Activity.created_at.asc()).first()
    newest = Activity.query.order_by(Activity.created_at.desc()).first()

    oldest_ts = oldest.created_at if oldest else None
    newest_ts = newest.created_at if newest else None

    # Calculate age in days
    age_days = 0
    if oldest_ts:
        now = datetime.now(timezone.utc)
        # Ensure oldest_ts is timezone-aware
        if oldest_ts.tzinfo is None:
            oldest_ts_aware = oldest_ts.replace(tzinfo=timezone.utc)
        else:
            oldest_ts_aware = oldest_ts
        age_days = (now - oldest_ts_aware).days

    # Rough estimate: ~1KB per activity record
    size_estimate_mb = (total_count * 1024) / (1024 * 1024)

    return {
        "total_count": total_count,
        "oldest_activity": oldest_ts,
        "newest_activity": newest_ts,
        "age_days": age_days,
        "size_estimate_mb": round(size_estimate_mb, 2),
    }


def auto_cleanup_activities(
    threshold_days: int = 90,
    max_records: int = 100000,
    force: bool = False,
) -> Optional[dict[str, int]]:
    """Automatically clean up activities if thresholds are exceeded.

    This function checks if cleanup is needed and performs it automatically.
    Useful for scheduled tasks.

    Args:
        threshold_days: Trigger cleanup if oldest activity is older than this
        max_records: Trigger cleanup if total records exceed this
        force: Force cleanup even if thresholds aren't met

    Returns:
        Cleanup statistics dict if cleanup was performed, None otherwise
    """
    stats = get_cleanup_stats()

    should_cleanup = force or (
        stats["total_count"] > max_records or stats["age_days"] > threshold_days
    )

    if not should_cleanup:
        if current_app:
            current_app.logger.info(
                f"Auto cleanup skipped: {stats['total_count']} records, "
                f"{stats['age_days']} days old (thresholds: {max_records} records, {threshold_days} days)"
            )
        return None

    if current_app:
        current_app.logger.info(
            f"Auto cleanup triggered: {stats['total_count']} records, "
            f"{stats['age_days']} days old"
        )

    # Keep 90 days OR max_records, whichever preserves more data
    keep_days = min(threshold_days, 90)
    result = cleanup_old_activities(
        days_to_keep=keep_days, max_records_to_keep=max_records
    )

    return result
