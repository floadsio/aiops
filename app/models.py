from __future__ import annotations

import secrets
from datetime import datetime
from typing import Any, Optional

import bcrypt
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .constants import DEFAULT_TENANT_COLOR
from .extensions import BaseModel, db, login_manager
from .security import LoginUser


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class User(BaseModel, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    linux_username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    aiops_cli_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    aiops_cli_api_key: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    # yadm/dotfile configuration
    personal_dotfile_repo_url: Mapped[Optional[str]] = mapped_column(
        String(512), nullable=True
    )
    personal_dotfile_branch: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True
    )
    # GPG key for yadm decryption (encrypted with Fernet)
    gpg_private_key_encrypted: Mapped[Optional[bytes]] = mapped_column(
        db.LargeBinary, nullable=True
    )
    gpg_key_id: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)

    ssh_keys: Mapped[list["SSHKey"]] = relationship(
        "SSHKey", back_populates="user", cascade="all, delete-orphan"
    )
    projects: Mapped[list["Project"]] = relationship("Project", back_populates="owner")
    user_integration_credentials: Mapped[list["UserIntegrationCredential"]] = (
        relationship(
            "UserIntegrationCredential",
            back_populates="user",
            cascade="all, delete-orphan",
        )
    )


class SSHKey(BaseModel, TimestampMixin):
    __tablename__ = "ssh_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    public_key: Mapped[str] = mapped_column(Text, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    private_key_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    # Encrypted private key stored in database (alternative to private_key_path)
    encrypted_private_key: Mapped[Optional[bytes]] = mapped_column(db.LargeBinary, nullable=True)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    tenant_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("tenants.id"), nullable=True
    )
    user: Mapped["User"] = relationship("User", back_populates="ssh_keys")
    tenant: Mapped[Optional["Tenant"]] = relationship(
        "Tenant", back_populates="ssh_keys"
    )
    projects: Mapped[list["Project"]] = relationship(
        "Project", back_populates="ssh_key"
    )


class Tenant(BaseModel, TimestampMixin):
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    color: Mapped[str] = mapped_column(
        String(16), nullable=False, default=DEFAULT_TENANT_COLOR
    )

    projects: Mapped[list["Project"]] = relationship(
        "Project", back_populates="tenant", cascade="all, delete-orphan"
    )
    ssh_keys: Mapped[list["SSHKey"]] = relationship(
        "SSHKey",
        back_populates="tenant",
        cascade="all, delete-orphan",
    )
    issue_integrations: Mapped[list["TenantIntegration"]] = relationship(
        "TenantIntegration", back_populates="tenant", cascade="all, delete-orphan"
    )

    @property
    def slug(self) -> str:
        """Generate a filesystem-safe slug from the tenant name.

        This matches the logic used in workspace_service._slugify().

        Returns:
            str: Slugified tenant name (lowercase, special chars converted to dashes)
        """
        translation_map: dict[str, str | int] = {c: "-" for c in " ./\\:@"}
        slug = self.name.lower().translate(str.maketrans(translation_map))
        while "--" in slug:
            slug = slug.replace("--", "-")
        slug = slug.strip("-")
        return slug or f"tenant-{self.id}"


class Project(BaseModel, TimestampMixin):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    repo_url: Mapped[str] = mapped_column(String(512), nullable=False)
    default_branch: Mapped[str] = mapped_column(
        String(64), default="main", nullable=False
    )
    local_path: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    ssh_key_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("ssh_keys.id"), nullable=True
    )

    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="projects")
    owner: Mapped["User"] = relationship("User", back_populates="projects")
    ssh_key: Mapped[Optional["SSHKey"]] = relationship(
        "SSHKey", back_populates="projects"
    )
    automation_tasks: Mapped[list["AutomationTask"]] = relationship(
        "AutomationTask", back_populates="project", cascade="all, delete-orphan"
    )
    issue_integrations: Mapped[list["ProjectIntegration"]] = relationship(
        "ProjectIntegration", back_populates="project", cascade="all, delete-orphan"
    )


class AutomationTask(BaseModel, TimestampMixin):
    __tablename__ = "automation_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_type: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    result: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    project: Mapped["Project"] = relationship(
        "Project", back_populates="automation_tasks"
    )


class TenantIntegration(BaseModel, TimestampMixin):
    __tablename__ = "tenant_integrations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_tenant_integration_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    base_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    api_token: Mapped[str] = mapped_column(Text, nullable=False)
    settings: Mapped[dict[str, Any]] = mapped_column(
        db.JSON, default=dict, nullable=False
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    tenant: Mapped["Tenant"] = relationship(
        "Tenant", back_populates="issue_integrations"
    )
    project_integrations: Mapped[list["ProjectIntegration"]] = relationship(
        "ProjectIntegration", back_populates="integration", cascade="all, delete-orphan"
    )


class ProjectIntegration(BaseModel, TimestampMixin):
    __tablename__ = "project_integrations"
    __table_args__ = (
        UniqueConstraint(
            "integration_id", "project_id", name="uq_project_integration_unique"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    integration_id: Mapped[int] = mapped_column(
        ForeignKey("tenant_integrations.id"), nullable=False
    )
    external_identifier: Mapped[str] = mapped_column(String(255), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(
        db.JSON, default=dict, nullable=False
    )
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Per-project credential overrides (for different GitLab/Jira instances)
    override_api_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    override_base_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    override_settings: Mapped[Optional[dict[str, Any]]] = mapped_column(
        db.JSON, nullable=True
    )
    # Auto-sync configuration
    auto_sync_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )

    project: Mapped["Project"] = relationship(
        "Project", back_populates="issue_integrations"
    )
    integration: Mapped["TenantIntegration"] = relationship(
        "TenantIntegration", back_populates="project_integrations"
    )
    issues: Mapped[list["ExternalIssue"]] = relationship(
        "ExternalIssue",
        back_populates="project_integration",
        cascade="all, delete-orphan",
    )


class ExternalIssue(BaseModel, TimestampMixin):
    __tablename__ = "external_issues"
    __table_args__ = (
        UniqueConstraint(
            "project_integration_id", "external_id", name="uq_external_issue_identifier"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_integration_id: Mapped[int] = mapped_column(
        ForeignKey("project_integrations.id"), nullable=False
    )
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    assignee: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    labels: Mapped[list[str]] = mapped_column(db.JSON, default=list, nullable=False)
    comments: Mapped[list[dict[str, Any]]] = mapped_column(
        db.JSON, default=list, nullable=False
    )
    external_updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    raw_payload: Mapped[Optional[dict[str, Any]]] = mapped_column(
        db.JSON, nullable=True
    )
    manually_assigned: Mapped[bool] = mapped_column(
        db.Boolean, default=False, nullable=False, server_default=db.false()
    )

    project_integration: Mapped["ProjectIntegration"] = relationship(
        "ProjectIntegration", back_populates="issues"
    )


class PinnedIssue(BaseModel):
    __tablename__ = "pinned_issues"
    __table_args__ = (UniqueConstraint("user_id", "issue_id", name="uq_user_issue"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    issue_id: Mapped[int] = mapped_column(
        ForeignKey("external_issues.id", ondelete="CASCADE"), nullable=False
    )
    pinned_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    user: Mapped["User"] = relationship("User")
    issue: Mapped["ExternalIssue"] = relationship("ExternalIssue")


class PinnedComment(BaseModel):
    """Pinned comment for follow-up tracking on dashboard."""

    __tablename__ = "pinned_comments"
    __table_args__ = (
        UniqueConstraint("user_id", "issue_id", "comment_id", name="uq_user_issue_comment"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    issue_id: Mapped[int] = mapped_column(
        ForeignKey("external_issues.id", ondelete="CASCADE"), nullable=False
    )
    comment_id: Mapped[str] = mapped_column(String(64), nullable=False)
    pinned_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    note: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)

    user: Mapped["User"] = relationship("User")
    issue: Mapped["ExternalIssue"] = relationship("ExternalIssue")


class UserIntegrationCredential(BaseModel, TimestampMixin):
    """User-specific credentials for issue integrations.

    Allows users to override integration credentials with their personal tokens
    so that comments and issues are created under their account instead of the bot.
    """

    __tablename__ = "user_integration_credentials"
    __table_args__ = (
        UniqueConstraint("user_id", "integration_id", name="uq_user_integration_cred"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    integration_id: Mapped[int] = mapped_column(
        ForeignKey("tenant_integrations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    api_token: Mapped[str] = mapped_column(Text, nullable=False)
    settings: Mapped[Optional[dict[str, Any]]] = mapped_column(
        db.JSON, nullable=True
    )

    user: Mapped["User"] = relationship(
        "User", back_populates="user_integration_credentials"
    )
    integration: Mapped["TenantIntegration"] = relationship("TenantIntegration")


class AISession(BaseModel, TimestampMixin):
    """Tracks AI tool sessions for resumption across Claude and Codex.

    Stores session identifiers that can be used to resume interrupted or
    completed AI sessions via the web UI. Each tool has different resumption
    patterns:
    - Claude: uses session UUIDs with --resume flag
    - Codex: uses session UUIDs with resume command
    """

    __tablename__ = "ai_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    issue_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("external_issues.id", ondelete="SET NULL"), nullable=True, index=True
    )
    tool: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    session_id: Mapped[str] = mapped_column(String(255), nullable=False)
    command: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tmux_target: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    project: Mapped["Project"] = relationship("Project")
    user: Mapped["User"] = relationship("User")
    issue: Mapped[Optional["ExternalIssue"]] = relationship("ExternalIssue")


class SystemConfig(BaseModel, TimestampMixin):
    """System-wide configuration settings stored in the database.

    Currently stores Linux user mapping for per-user tmux sessions.
    """

    __tablename__ = "system_config"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(
        String(128), unique=True, nullable=False, index=True
    )
    value: Mapped[Optional[dict[str, Any]]] = mapped_column(db.JSON, nullable=True)


class UserIdentityMap(BaseModel, TimestampMixin):
    """Maps aiops users to their identities on external issue providers.

    Used for correctly assigning issues and attributing work across
    GitHub, GitLab, and Jira platforms.
    """

    __tablename__ = "user_identity_map"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    github_username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    gitlab_username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    jira_account_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    user: Mapped["User"] = relationship("User")

    def __repr__(self) -> str:
        return (
            f"<UserIdentityMap user_id={self.user_id} "
            f"github={self.github_username} "
            f"gitlab={self.gitlab_username} "
            f"jira={self.jira_account_id}>"
        )


class APIKey(BaseModel, TimestampMixin):
    """API keys for programmatic access to the AIops API.

    Supports token-based authentication with scoped permissions.
    """

    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    key_prefix: Mapped[str] = mapped_column(
        String(16), nullable=False, index=True
    )  # First 8 chars for identification
    scopes: Mapped[list[str]] = mapped_column(
        db.JSON, default=list, nullable=False
    )  # e.g., ['read', 'write', 'admin']
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship("User")

    @staticmethod
    def generate_key() -> tuple[str, str, str]:
        """Generate a new API key.

        Returns:
            tuple: (full_key, key_hash, key_prefix)
                - full_key: The raw key to return to user (only shown once)
                - key_hash: Hashed key to store in database
                - key_prefix: First 8 chars for identification
        """
        # Generate a 32-byte random key and encode as hex
        raw_key = secrets.token_hex(32)
        full_key = f"aiops_{raw_key}"
        key_prefix = full_key[:12]  # "aiops_" + first 6 hex chars

        # Hash the key for storage
        key_hash = bcrypt.hashpw(full_key.encode("utf-8"), bcrypt.gensalt()).decode(
            "utf-8"
        )

        return full_key, key_hash, key_prefix

    def verify_key(self, key: str) -> bool:
        """Verify a provided API key against this record.

        Args:
            key: The raw API key to verify

        Returns:
            bool: True if key matches, False otherwise
        """
        try:
            return bcrypt.checkpw(key.encode("utf-8"), self.key_hash.encode("utf-8"))
        except (ValueError, TypeError):
            return False

    def has_scope(self, scope: str) -> bool:
        """Check if this API key has a specific scope.

        Args:
            scope: The scope to check (e.g., 'read', 'write', 'admin')

        Returns:
            bool: True if key has the scope
        """
        if not self.is_active:
            return False
        if self.expires_at and datetime.utcnow() > self.expires_at:
            return False
        return scope in (self.scopes or []) or "admin" in (self.scopes or [])


class APIAuditLog(BaseModel, TimestampMixin):
    """Audit log for API requests.

    Tracks all API calls for security and compliance.
    """

    __tablename__ = "api_audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    api_key_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("api_keys.id", ondelete="SET NULL"), nullable=True, index=True
    )
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    path: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    query_params: Mapped[Optional[dict[str, Any]]] = mapped_column(
        db.JSON, nullable=True
    )
    request_body: Mapped[Optional[dict[str, Any]]] = mapped_column(
        db.JSON, nullable=True
    )
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_time_ms: Mapped[Optional[float]] = mapped_column(Integer, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    user: Mapped[Optional["User"]] = relationship("User")
    api_key: Mapped[Optional["APIKey"]] = relationship("APIKey")


class GlobalAgentContext(BaseModel, TimestampMixin):
    """Global AGENTS.md content that appears in all AGENTS.override.md files.

    This table stores the global agent context that is prepended to all
    AGENTS.override.md files generated by the system. If no record exists,
    the system falls back to reading AGENTS.md from the repository.

    There should only be one record in this table at any time.
    """

    __tablename__ = "global_agent_context"

    id: Mapped[int] = mapped_column(primary_key=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    updated_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    updated_by: Mapped[Optional["User"]] = relationship("User")


class GlobalAgentsHistory(BaseModel, TimestampMixin):
    """Version history for global agents context.

    This table stores historical versions of the global agents content,
    allowing users to view changes over time and rollback to previous versions.
    Each update to GlobalAgentContext creates a new history entry.
    """

    __tablename__ = "global_agents_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, unique=True, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    change_description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    created_by: Mapped[Optional["User"]] = relationship("User")


class Backup(BaseModel, TimestampMixin):
    """Database backups with metadata tracking.

    Stores metadata about database backups for tracking, download, and restore operations.
    """

    __tablename__ = "backups"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    filepath: Mapped[str] = mapped_column(String(512), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    created_by: Mapped[Optional["User"]] = relationship("User")


class Activity(BaseModel, TimestampMixin):
    """Activity log for tracking all aiops operations.

    Captures all user actions across web UI and CLI including issue management,
    git operations, session management, and system operations.
    """

    __tablename__ = "activities"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action_type: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )  # e.g., 'issue.create', 'git.commit', 'session.start'
    resource_type: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True, index=True
    )  # e.g., 'issue', 'project', 'session'
    resource_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, index=True
    )  # ID of the resource
    resource_name: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )  # Human-readable resource name
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="success", index=True
    )  # 'success', 'failure', 'pending'
    description: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )  # Human-readable action description
    extra_data: Mapped[Optional[dict[str, Any]]] = mapped_column(
        db.JSON, nullable=True
    )  # Additional context (files, messages, etc.)
    error_message: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )  # Error details if status='failure'
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    source: Mapped[str] = mapped_column(
        String(20), nullable=False, default="web", index=True
    )  # 'web' or 'cli'

    user: Mapped[Optional["User"]] = relationship("User")


class AIIssuePreviews(BaseModel, TimestampMixin):
    """Temporary storage for AI-assisted issue preview data.

    Stores preview data (issue_data, project_id, integration_id) temporarily
    while users review and confirm the AI-generated issue. Preview tokens
    expire after a configurable timeout (default: 1 hour).
    """

    __tablename__ = "ai_issue_previews"

    id: Mapped[int] = mapped_column(primary_key=True)
    preview_token: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    integration_id: Mapped[int] = mapped_column(
        ForeignKey("project_integrations.id", ondelete="CASCADE"), nullable=False
    )
    issue_data: Mapped[dict[str, Any]] = mapped_column(db.JSON, nullable=False)
    ai_tool: Mapped[str] = mapped_column(String(50), nullable=False)
    issue_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, index=True
    )


class IssuePlan(BaseModel, TimestampMixin):
    """Stores AI-generated implementation plans for issues.

    Plans are stored as markdown and can be used to resume AI sessions
    with existing implementation strategies.
    """

    __tablename__ = "issue_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    issue_id: Mapped[int] = mapped_column(
        ForeignKey("external_issues.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="draft", nullable=False
    )
    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    issue: Mapped["ExternalIssue"] = relationship("ExternalIssue")
    created_by: Mapped[Optional["User"]] = relationship("User")


class Notification(BaseModel):
    """User notifications for events across all integrated platforms.

    Notifications are generated for issue assignments, comments, mentions,
    status changes, and system events (backups, sync errors, etc.).
    """

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    notification_type: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    resource_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    resource_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    resource_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    priority: Mapped[str] = mapped_column(
        String(32), default="normal", nullable=False
    )
    metadata_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False, index=True
    )
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship("User")

    __table_args__ = (
        db.Index("idx_notifications_user_unread", "user_id", "is_read", "created_at"),
    )

    def get_metadata(self) -> dict[str, Any]:
        """Parse metadata JSON into a dictionary."""
        import json

        if self.metadata_json:
            try:
                return json.loads(self.metadata_json)
            except json.JSONDecodeError:
                return {}
        return {}

    def set_metadata(self, value: dict[str, Any]) -> None:
        """Serialize metadata dictionary to JSON."""
        import json

        self.metadata_json = json.dumps(value) if value else None

    def to_dict(self) -> dict[str, Any]:
        """Convert notification to dictionary for API responses."""
        return {
            "id": self.id,
            "type": self.notification_type,
            "title": self.title,
            "message": self.message,
            "priority": self.priority,
            "is_read": self.is_read,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "resource_url": self.resource_url,
            "metadata": self.get_metadata(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "read_at": self.read_at.isoformat() if self.read_at else None,
        }


class NotificationPreferences(BaseModel, TimestampMixin):
    """User preferences for notification types and filtering.

    Controls which notification types a user receives and allows
    muting specific projects or integrations.
    """

    __tablename__ = "notification_preferences"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    enabled_types_json: Mapped[str] = mapped_column(
        Text, default="[]", nullable=False
    )
    muted_projects_json: Mapped[str] = mapped_column(
        Text, default="[]", nullable=False
    )
    muted_integrations_json: Mapped[str] = mapped_column(
        Text, default="[]", nullable=False
    )
    email_notifications: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    email_frequency: Mapped[str] = mapped_column(
        String(32), default="realtime", nullable=False
    )

    user: Mapped["User"] = relationship("User")

    # Default notification types enabled for new users (all enabled by default)
    DEFAULT_ENABLED_TYPES = [
        # Issue events
        "issue.assigned",
        "issue.mentioned",
        "issue.commented",
        "issue.status_changed",
        "issue.created",
        # Project events
        "project.sync_error",
        # System events (admin only)
        "system.backup_completed",
        "system.backup_failed",
        "system.integration_error",
        # AI Session events
        "session.completed",
        "session.error",
    ]

    @property
    def enabled_types(self) -> list[str]:
        """Parse enabled types JSON into a list."""
        import json

        try:
            return json.loads(self.enabled_types_json or "[]")
        except json.JSONDecodeError:
            return []

    @enabled_types.setter
    def enabled_types(self, value: list[str]) -> None:
        """Serialize enabled types list to JSON."""
        import json

        self.enabled_types_json = json.dumps(value) if value else "[]"

    @property
    def muted_projects(self) -> list[int]:
        """Parse muted projects JSON into a list."""
        import json

        try:
            return json.loads(self.muted_projects_json or "[]")
        except json.JSONDecodeError:
            return []

    @muted_projects.setter
    def muted_projects(self, value: list[int]) -> None:
        """Serialize muted projects list to JSON."""
        import json

        self.muted_projects_json = json.dumps(value) if value else "[]"

    @property
    def muted_integrations(self) -> list[int]:
        """Parse muted integrations JSON into a list."""
        import json

        try:
            return json.loads(self.muted_integrations_json or "[]")
        except json.JSONDecodeError:
            return []

    @muted_integrations.setter
    def muted_integrations(self, value: list[int]) -> None:
        """Serialize muted integrations list to JSON."""
        import json

        self.muted_integrations_json = json.dumps(value) if value else "[]"

    @classmethod
    def create_default(cls, user_id: int) -> "NotificationPreferences":
        """Create default notification preferences for a user."""
        prefs = cls(user_id=user_id)
        prefs.enabled_types = cls.DEFAULT_ENABLED_TYPES
        return prefs

    def to_dict(self) -> dict[str, Any]:
        """Convert preferences to dictionary for API responses."""
        return {
            "enabled_types": self.enabled_types,
            "muted_projects": self.muted_projects,
            "muted_integrations": self.muted_integrations,
            "email_notifications": self.email_notifications,
            "email_frequency": self.email_frequency,
        }


class SyncHistory(BaseModel):
    """History of automatic issue sync operations."""

    __tablename__ = "sync_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_integration_id: Mapped[int] = mapped_column(
        ForeignKey("project_integrations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # 'success', 'failed'
    issues_updated: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duration_seconds: Mapped[Optional[float]] = mapped_column(
        db.Float, nullable=True
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False, index=True
    )

    project_integration: Mapped["ProjectIntegration"] = relationship(
        "ProjectIntegration", backref="sync_history"
    )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "id": self.id,
            "project_integration_id": self.project_integration_id,
            "status": self.status,
            "issues_updated": self.issues_updated,
            "duration_seconds": self.duration_seconds,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


@login_manager.user_loader
def load_user(user_id: str) -> Optional[LoginUser]:
    user = User.query.get(int(user_id))
    return LoginUser(user) if user else None
