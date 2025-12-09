import os
import shutil
import tarfile
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from flask import current_app

from ..extensions import db
from ..models import Backup
from .notification_generator import notify_backup_completed, notify_backup_failed


class BackupError(Exception):
    """Custom exception for backup-related errors."""
    pass


def _get_backup_dir() -> Path:
    """Returns the path to the backup storage directory."""
    backup_dir = Path(current_app.instance_path) / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


def create_backup(description: Optional[str] = None, user_id: Optional[int] = None) -> Backup:
    """
    Creates a new database backup.

    The backup includes the SQLite database file and can optionally include
    other instance-specific files (e.g., SSH keys).

    Args:
        description: Optional description of the backup
        user_id: Optional user ID of the user creating the backup

    Returns:
        Backup: The created backup model instance

    Raises:
        BackupError: If backup creation fails
    """
    backup_dir = _get_backup_dir()
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup_filename = f"aiops_backup_{timestamp}.tar.gz"
    backup_path = backup_dir / backup_filename

    db_path = Path(current_app.config["SQLALCHEMY_DATABASE_URI"].replace("sqlite:///", ""))
    if not db_path.is_file():
        raise BackupError(f"Database file not found at {db_path}")

    try:
        with tarfile.open(backup_path, "w:gz") as tar:
            # Add database file
            tar.add(db_path, arcname=db_path.name)

            # Optionally add SSH keys or other instance files
            keys_dir = Path(current_app.instance_path) / "keys"
            if keys_dir.is_dir():
                tar.add(keys_dir, arcname="keys")

        # Store backup metadata in the database
        backup = Backup(
            filename=backup_filename,
            filepath=str(backup_path),
            size_bytes=backup_path.stat().st_size,
            description=description,
            created_by_user_id=user_id,
        )
        db.session.add(backup)
        db.session.commit()

        # Notify admins about successful backup
        notify_backup_completed(backup.id, description or backup_filename)

        return backup
    except Exception as e:
        if backup_path.exists():
            os.remove(backup_path)
        db.session.rollback()
        # Notify admins about failed backup
        notify_backup_failed(str(e))
        raise BackupError(f"Failed to create backup: {e}")


def list_backups() -> list[dict[str, Any]]:
    """Lists available backups with their metadata.

    Returns:
        list: List of backup metadata dictionaries
    """
    backups = Backup.query.order_by(Backup.created_at.desc()).all()
    result = []
    for backup in backups:
        # Verify file still exists
        backup_path = Path(backup.filepath)
        if not backup_path.exists():
            continue

        result.append({
            "id": backup.id,
            "filename": backup.filename,
            "filepath": backup.filepath,
            "size_bytes": backup.size_bytes,
            "description": backup.description,
            "created_at": backup.created_at.isoformat() if backup.created_at else None,
            "created_by": {
                "id": backup.created_by.id,
                "name": backup.created_by.name,
                "email": backup.created_by.email,
            }
            if backup.created_by
            else None,
        })
    return result


def get_backup(backup_id: int) -> Backup:
    """Retrieves a backup by ID.

    Args:
        backup_id: Database ID of the backup

    Returns:
        Backup: The backup model instance

    Raises:
        BackupError: If backup not found
    """
    backup = Backup.query.get(backup_id)
    if not backup:
        raise BackupError(f"Backup with ID '{backup_id}' not found in database.")

    # Verify file still exists
    backup_path = Path(backup.filepath)
    if not backup_path.is_file():
        raise BackupError(
            f"Backup file '{backup.filename}' not found at '{backup.filepath}'."
        )

    return backup


def get_backup_path(backup_id: int) -> Path:
    """Retrieves the full path for a given backup ID.

    Args:
        backup_id: Database ID of the backup

    Returns:
        Path: Full path to the backup file

    Raises:
        BackupError: If backup not found
    """
    backup = get_backup(backup_id)
    return Path(backup.filepath)


def restore_backup(backup_id: int) -> None:
    """
    Restores the database from a specified backup.
    This is a destructive operation and should be used with caution.

    Args:
        backup_id: Database ID of the backup to restore

    Raises:
        BackupError: If restore fails
    """
    backup_path = get_backup_path(backup_id)
    db_path = Path(current_app.config["SQLALCHEMY_DATABASE_URI"].replace("sqlite:///", ""))
    instance_path = Path(current_app.instance_path)

    # Ensure the database file exists before attempting to restore
    if not db_path.is_file():
        raise BackupError(f"Current database file not found at {db_path}. Cannot proceed with restore.")

    # Stop the application or ensure no active connections before restoring
    # For now, we'll just overwrite the file. In a real app, this needs more robust handling.

    # Create a temporary directory for extraction
    temp_extract_dir = instance_path / f"restore_temp_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    temp_extract_dir.mkdir(parents=True, exist_ok=True)

    try:
        with tarfile.open(backup_path, "r:gz") as tar:
            # Extract only the database file and keys directory
            members = [m for m in tar.getmembers() if m.name == db_path.name or m.name.startswith("keys/")]
            tar.extractall(path=temp_extract_dir, members=members)

        extracted_db_path = temp_extract_dir / db_path.name
        if not extracted_db_path.is_file():
            raise BackupError(f"Database file not found in backup '{backup_id}'.")

        # Close existing DB connections before replacing the file
        db.session.close_all()
        db.engine.dispose()

        # Overwrite the current database file
        shutil.copy(extracted_db_path, db_path)

        # Overwrite keys directory if present in backup
        extracted_keys_dir = temp_extract_dir / "keys"
        if extracted_keys_dir.is_dir():
            target_keys_dir = instance_path / "keys"
            if target_keys_dir.is_dir():
                shutil.rmtree(target_keys_dir)
            shutil.copytree(extracted_keys_dir, target_keys_dir)

    except Exception as e:
        raise BackupError(f"Failed to restore backup '{backup_id}': {e}")
    finally:
        # Clean up temporary extraction directory
        if temp_extract_dir.exists():
            shutil.rmtree(temp_extract_dir)

