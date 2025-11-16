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
    claude_input_tokens_limit: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    claude_input_tokens_remaining: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    claude_output_tokens_limit: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    claude_output_tokens_remaining: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    claude_requests_limit: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    claude_requests_remaining: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    claude_usage_last_updated: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    aiops_cli_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    aiops_cli_api_key: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    ssh_keys: Mapped[list["SSHKey"]] = relationship(
        "SSHKey", back_populates="user", cascade="all, delete-orphan"
    )
    projects: Mapped[list["Project"]] = relationship("Project", back_populates="owner")


class SSHKey(BaseModel, TimestampMixin):
    __tablename__ = "ssh_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    public_key: Mapped[str] = mapped_column(Text, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    private_key_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

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


class AISession(BaseModel, TimestampMixin):
    """Tracks AI tool sessions for resumption across Claude, Codex, and Gemini.

    Stores session identifiers that can be used to resume interrupted or
    completed AI sessions via the web UI. Each tool has different resumption
    patterns:
    - Claude: uses session UUIDs with --resume flag
    - Codex: uses session UUIDs with resume command
    - Gemini: uses custom tags with /chat resume command
    """

    __tablename__ = "ai_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
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


@login_manager.user_loader
def load_user(user_id: str) -> Optional[LoginUser]:
    user = User.query.get(int(user_id))
    return LoginUser(user) if user else None
