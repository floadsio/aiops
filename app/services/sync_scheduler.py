"""Background scheduler for automatic issue synchronization.

Provides periodic syncing of issues from external providers (GitHub, GitLab, Jira)
without requiring manual intervention.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from flask import Flask

logger = logging.getLogger(__name__)

# Global scheduler instance
_scheduler: Optional[BackgroundScheduler] = None
_scheduler_lock = threading.Lock()


def get_scheduler() -> Optional[BackgroundScheduler]:
    """Get the global scheduler instance."""
    return _scheduler


def init_scheduler(app: Flask) -> Optional[BackgroundScheduler]:
    """Initialize and start the background scheduler.

    Args:
        app: Flask application instance

    Returns:
        BackgroundScheduler instance or None if disabled
    """
    global _scheduler

    with _scheduler_lock:
        if _scheduler is not None:
            logger.warning("Scheduler already initialized")
            return _scheduler

        # Check if auto-sync is enabled
        if not app.config.get("ISSUE_SYNC_ENABLED", False):
            logger.info("Automatic issue sync is disabled")
            return None

        # Get configuration
        sync_interval = app.config.get("ISSUE_SYNC_INTERVAL", 900)  # 15 minutes default
        sync_on_startup = app.config.get("ISSUE_SYNC_ON_STARTUP", True)

        logger.info(
            "Initializing issue sync scheduler (interval=%ds, sync_on_startup=%s)",
            sync_interval,
            sync_on_startup,
        )

        # Create scheduler
        _scheduler = BackgroundScheduler(
            daemon=True,
            job_defaults={
                "coalesce": True,  # Combine missed runs into one
                "max_instances": 1,  # Only one instance of each job at a time
                "misfire_grace_time": 60,  # Allow 60s grace for missed jobs
            },
        )

        # Add the sync job
        _scheduler.add_job(
            func=_run_sync_all,
            trigger=IntervalTrigger(seconds=sync_interval),
            id="issue_sync_all",
            name="Sync all issues from external providers",
            replace_existing=True,
            kwargs={"app": app},
        )

        # Start the scheduler
        _scheduler.start()
        logger.info("Issue sync scheduler started")

        # Run initial sync if configured
        if sync_on_startup:
            # Delay initial sync by 30 seconds to let the app fully start
            _scheduler.add_job(
                func=_run_sync_all,
                trigger="date",
                run_date=datetime.now() + timedelta(seconds=30),
                id="issue_sync_startup",
                name="Initial issue sync on startup",
                kwargs={"app": app},
            )
            logger.info("Scheduled initial sync in 30 seconds")

        return _scheduler


def shutdown_scheduler() -> None:
    """Shutdown the scheduler gracefully."""
    global _scheduler

    with _scheduler_lock:
        if _scheduler is not None:
            logger.info("Shutting down issue sync scheduler...")
            _scheduler.shutdown(wait=True)
            _scheduler = None
            logger.info("Issue sync scheduler stopped")


def _run_sync_all(app: Flask) -> dict:
    """Run sync for all enabled project integrations.

    Args:
        app: Flask application instance

    Returns:
        Dict with sync results summary
    """
    with app.app_context():
        from ..extensions import db
        from ..models import ProjectIntegration, SyncHistory
        from .issues import IssueSyncError, sync_project_integration
        from .notification_generator import notify_sync_error

        # Get all enabled project integrations
        project_integrations = (
            ProjectIntegration.query.join(ProjectIntegration.integration)
            .filter(ProjectIntegration.integration.has(enabled=True))
            .filter(ProjectIntegration.auto_sync_enabled == True)  # noqa: E712
            .all()
        )

        if not project_integrations:
            logger.debug("No project integrations configured for auto-sync")
            return {"total": 0, "success": 0, "failed": 0}

        logger.info(
            "Starting auto-sync for %d project integrations", len(project_integrations)
        )

        results = {"total": len(project_integrations), "success": 0, "failed": 0}

        for pi in project_integrations:
            try:
                start_time = datetime.utcnow()
                updated_issues = sync_project_integration(pi)
                duration = (datetime.utcnow() - start_time).total_seconds()

                # Record success in sync history
                history = SyncHistory(
                    project_integration_id=pi.id,
                    status="success",
                    issues_updated=len(updated_issues),
                    duration_seconds=duration,
                )
                db.session.add(history)
                db.session.commit()

                results["success"] += 1
                logger.info(
                    "Synced %d issues for %s/%s in %.2fs",
                    len(updated_issues),
                    pi.project.name if pi.project else "?",
                    pi.integration.name if pi.integration else "?",
                    duration,
                )

            except IssueSyncError as e:
                results["failed"] += 1
                error_msg = str(e)

                # Record failure in sync history
                history = SyncHistory(
                    project_integration_id=pi.id,
                    status="failed",
                    error_message=error_msg[:1000],  # Truncate long errors
                )
                db.session.add(history)
                db.session.commit()

                logger.error(
                    "Failed to sync %s/%s: %s",
                    pi.project.name if pi.project else "?",
                    pi.integration.name if pi.integration else "?",
                    error_msg,
                )

                # Send notification to admins on failure
                try:
                    notify_sync_error(
                        project_id=pi.project_id,
                        project_name=pi.project.name if pi.project else "Unknown",
                        integration_id=pi.integration_id,
                        provider=pi.integration.provider if pi.integration else "Unknown",
                        error_message=error_msg,
                    )
                except Exception as notify_err:
                    logger.warning("Failed to send sync error notification: %s", notify_err)

            except Exception as e:
                results["failed"] += 1
                logger.exception(
                    "Unexpected error syncing %s/%s",
                    pi.project.name if pi.project else "?",
                    pi.integration.name if pi.integration else "?",
                )

                # Record failure
                history = SyncHistory(
                    project_integration_id=pi.id,
                    status="failed",
                    error_message=str(e)[:1000],
                )
                db.session.add(history)
                db.session.commit()

        logger.info(
            "Auto-sync completed: %d/%d successful, %d failed",
            results["success"],
            results["total"],
            results["failed"],
        )

        return results


def trigger_sync_now(app: Flask) -> None:
    """Manually trigger an immediate sync.

    Args:
        app: Flask application instance
    """
    global _scheduler

    if _scheduler is None:
        logger.warning("Scheduler not running, executing sync directly")
        _run_sync_all(app)
        return

    # Add a one-time job to run immediately
    _scheduler.add_job(
        func=_run_sync_all,
        trigger="date",
        run_date=datetime.now(),
        id=f"issue_sync_manual_{datetime.now().timestamp()}",
        name="Manual issue sync trigger",
        kwargs={"app": app},
    )
    logger.info("Manual sync triggered")


def get_scheduler_status() -> dict:
    """Get current scheduler status.

    Returns:
        Dict with scheduler status information
    """
    global _scheduler

    if _scheduler is None:
        return {
            "running": False,
            "enabled": False,
            "next_run": None,
            "jobs": [],
        }

    jobs = []
    for job in _scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
        })

    # Find the main sync job
    main_job = _scheduler.get_job("issue_sync_all")
    next_run = main_job.next_run_time if main_job else None

    return {
        "running": _scheduler.running,
        "enabled": True,
        "next_run": next_run.isoformat() if next_run else None,
        "jobs": jobs,
    }
