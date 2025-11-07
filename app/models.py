from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from .constants import DEFAULT_TENANT_COLOR
from .extensions import db, login_manager
from .security import LoginUser



class TimestampMixin:
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class User(db.Model, TimestampMixin):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    password_hash = Column(String(255), nullable=False)
    is_admin = Column(Boolean, default=False, nullable=False)

    ssh_keys = relationship("SSHKey", back_populates="user", cascade="all, delete-orphan")
    projects = relationship("Project", back_populates="owner")


class SSHKey(db.Model, TimestampMixin):
    __tablename__ = "ssh_keys"

    id = Column(Integer, primary_key=True)
    name = Column(String(128), nullable=False)
    public_key = Column(Text, nullable=False)
    fingerprint = Column(String(128), nullable=False, unique=True)
    private_key_path = Column(String(512), nullable=True)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=True)
    user = relationship("User", back_populates="ssh_keys")
    tenant = relationship("Tenant", back_populates="ssh_keys")
    projects = relationship("Project", back_populates="ssh_key")


class Tenant(db.Model, TimestampMixin):
    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    color = Column(String(16), nullable=False, default=DEFAULT_TENANT_COLOR)

    projects = relationship("Project", back_populates="tenant", cascade="all, delete-orphan")
    ssh_keys = relationship(
        "SSHKey",
        back_populates="tenant",
        cascade="all, delete-orphan",
    )
    issue_integrations = relationship(
        "TenantIntegration", back_populates="tenant", cascade="all, delete-orphan"
    )


class Project(db.Model, TimestampMixin):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    repo_url = Column(String(512), nullable=False)
    default_branch = Column(String(64), default="main", nullable=False)
    local_path = Column(String(512), nullable=False)
    description = Column(Text)

    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    ssh_key_id = Column(Integer, ForeignKey("ssh_keys.id"), nullable=True)

    tenant = relationship("Tenant", back_populates="projects")
    owner = relationship("User", back_populates="projects")
    ssh_key = relationship("SSHKey", back_populates="projects")
    automation_tasks = relationship(
        "AutomationTask", back_populates="project", cascade="all, delete-orphan"
    )
    issue_integrations = relationship(
        "ProjectIntegration", back_populates="project", cascade="all, delete-orphan"
    )


class AutomationTask(db.Model, TimestampMixin):
    __tablename__ = "automation_tasks"

    id = Column(Integer, primary_key=True)
    task_type = Column(String(50), nullable=False)
    payload = Column(Text, nullable=False)
    status = Column(String(20), default="pending", nullable=False)
    result = Column(Text, nullable=True)

    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    project = relationship("Project", back_populates="automation_tasks")


class TenantIntegration(db.Model, TimestampMixin):
    __tablename__ = "tenant_integrations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_tenant_integration_name"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    provider = Column(String(50), nullable=False)
    name = Column(String(255), nullable=False)
    base_url = Column(String(512), nullable=True)
    api_token = Column(Text, nullable=False)
    settings = Column(db.JSON, default=dict, nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)

    tenant = relationship("Tenant", back_populates="issue_integrations")
    project_integrations = relationship(
        "ProjectIntegration", back_populates="integration", cascade="all, delete-orphan"
    )


class ProjectIntegration(db.Model, TimestampMixin):
    __tablename__ = "project_integrations"
    __table_args__ = (
        UniqueConstraint(
            "integration_id", "project_id", name="uq_project_integration_unique"
        ),
    )

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    integration_id = Column(Integer, ForeignKey("tenant_integrations.id"), nullable=False)
    external_identifier = Column(String(255), nullable=False)
    config = Column(db.JSON, default=dict, nullable=False)
    last_synced_at = Column(DateTime, nullable=True)

    project = relationship("Project", back_populates="issue_integrations")
    integration = relationship("TenantIntegration", back_populates="project_integrations")
    issues = relationship(
        "ExternalIssue", back_populates="project_integration", cascade="all, delete-orphan"
    )


class ExternalIssue(db.Model, TimestampMixin):
    __tablename__ = "external_issues"
    __table_args__ = (
        UniqueConstraint(
            "project_integration_id", "external_id", name="uq_external_issue_identifier"
        ),
    )

    id = Column(Integer, primary_key=True)
    project_integration_id = Column(
        Integer, ForeignKey("project_integrations.id"), nullable=False
    )
    external_id = Column(String(128), nullable=False)
    title = Column(String(512), nullable=False)
    status = Column(String(128), nullable=True)
    assignee = Column(String(255), nullable=True)
    url = Column(String(1024), nullable=True)
    labels = Column(db.JSON, default=list, nullable=False)
    external_updated_at = Column(DateTime, nullable=True)
    last_seen_at = Column(DateTime, nullable=True)
    raw_payload = Column(db.JSON, nullable=True)

    project_integration = relationship("ProjectIntegration", back_populates="issues")


@login_manager.user_loader
def load_user(user_id: str) -> Optional[LoginUser]:
    user = User.query.get(int(user_id))
    return LoginUser(user) if user else None
