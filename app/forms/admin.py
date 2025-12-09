from __future__ import annotations

from urllib.parse import urlparse

from flask_wtf import FlaskForm  # type: ignore
from wtforms import (
    BooleanField,
    HiddenField,
    PasswordField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
    URLField,
)
from wtforms.validators import URL, DataRequired, Length, Optional, ValidationError

from ..constants import DEFAULT_TENANT_COLOR, TENANT_COLOR_CHOICES


class TenantForm(FlaskForm):
    name = StringField("Name", validators=[DataRequired(), Length(max=255)])
    description = TextAreaField("Description", validators=[Length(max=1000)])
    color = SelectField(
        "Tenant Color",
        validators=[DataRequired()],
        choices=TENANT_COLOR_CHOICES,
        default=DEFAULT_TENANT_COLOR,
        render_kw={
            "aria-description": "Used to color-code dashboards, issue lists, and project cards."
        },
    )


def validate_repo_url(form, field):
    value = (field.data or "").strip()
    if not value:
        raise ValidationError("Repository URL is required.")

    if value.startswith("git@"):
        if ":" not in value:
            raise ValidationError(
                "SSH URLs must follow git@host:owner/repo.git format."
            )
        host, _, path = value.partition(":")
        if not path or "/" not in path:
            raise ValidationError("SSH URLs must include owner/repo.git.")
        if not path.endswith(".git"):
            raise ValidationError("SSH URLs must end with .git.")
        return

    if value.lower().startswith("ssh://git@"):
        parsed = urlparse(value)
        if not parsed.hostname:
            raise ValidationError("SSH URLs must include a hostname.")
        path = parsed.path.lstrip("/")
        if "/" not in path:
            raise ValidationError("SSH URLs must include owner/repo.git.")
        if not path.endswith(".git"):
            raise ValidationError("SSH URLs must end with .git.")
        return

    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValidationError("Enter a valid HTTPS or SSH repository URL.")
    if "/" not in parsed.path.strip("/"):
        raise ValidationError("Repository path must include owner/repo.")


def validate_dotfiles_url(form, field):
    """Validate dotfiles repository URL.

    Accepts:
    - HTTPS URLs: https://github.com/owner/dotfiles.git
    - Git SSH URLs: git@github.com:owner/dotfiles.git
    - Optional .git suffix for HTTP URLs
    """
    value = (field.data or "").strip()
    if not value:
        # Field is optional, so empty is OK
        return

    # Accept git@host:path format
    if value.startswith("git@"):
        if ":" not in value:
            raise ValidationError(
                "SSH URLs must follow git@host:owner/repo format."
            )
        return

    # Accept ssh://git@host/path format
    if value.lower().startswith("ssh://"):
        parsed = urlparse(value)
        if not parsed.hostname:
            raise ValidationError("SSH URLs must include a hostname.")
        return

    # Accept HTTP/HTTPS URLs
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValidationError("Enter a valid HTTPS URL (https://...) or Git SSH URL (git@host:owner/repo).")
    if "/" not in parsed.path.strip("/"):
        raise ValidationError("URL must include repository path (e.g., owner/repo).")


class ProjectForm(FlaskForm):
    name = StringField("Name", validators=[DataRequired(), Length(max=255)])
    repo_url = StringField(
        "Repository URL",
        validators=[DataRequired(), Length(max=512), validate_repo_url],
        render_kw={
            "placeholder": "https://example.com/org/repo.git or git@example.com:org/repo.git"
        },
    )
    default_branch = StringField(
        "Default Branch", validators=[DataRequired(), Length(max=64)]
    )
    description = TextAreaField("Description", validators=[Length(max=1000)])
    tenant_id = SelectField("Tenant", coerce=int, validators=[DataRequired()])
    owner_id = SelectField("Owner", coerce=int, validators=[DataRequired()])


class SSHKeyForm(FlaskForm):
    name = StringField("Name", validators=[DataRequired(), Length(max=128)])
    public_key = TextAreaField("Public Key", validators=[DataRequired()])
    tenant_id = SelectField("Tenant", coerce=int, validators=[Optional()])
    private_key = TextAreaField(
        "Private Key (optional)",
        description="Paste the private key material to store it securely on the server.",
        validators=[Optional()],
    )
    remove_private_key = BooleanField("Remove stored private key")


class TenantIntegrationForm(FlaskForm):
    tenant_id = SelectField("Tenant", coerce=int, validators=[DataRequired()])
    name = StringField("Name", validators=[DataRequired(), Length(max=255)])
    provider = SelectField(
        "Provider",
        choices=[
            ("github", "GitHub"),
            ("gitlab", "GitLab"),
            ("jira", "Jira"),
        ],
        validators=[DataRequired()],
    )
    base_url = URLField("Base URL", validators=[Optional(), URL(), Length(max=512)])
    api_token = PasswordField(
        "API Token", validators=[DataRequired(), Length(max=4096)]
    )
    jira_email = StringField(
        "Jira Account Email",
        description="Atlassian account email used with the API token (required for Jira Cloud).",
        validators=[Optional(), Length(max=255)],
    )
    enabled = BooleanField("Enabled", default=True)
    save = SubmitField("Save Integration")


class TenantIntegrationUpdateForm(FlaskForm):
    name = StringField("Name", validators=[DataRequired(), Length(max=255)])
    base_url = URLField("Base URL", validators=[Optional(), URL(), Length(max=512)])
    api_token = PasswordField(
        "API Token",
        description="Leave blank to keep current token",
        validators=[Optional(), Length(max=4096)],
    )
    submit = SubmitField("Update Integration")


class TenantIntegrationDeleteForm(FlaskForm):
    integration_id = HiddenField(validators=[DataRequired()])
    submit = SubmitField("Remove Integration")


class ProjectIntegrationForm(FlaskForm):
    project_id = SelectField("Project", coerce=int, validators=[DataRequired()])
    integration_id = SelectField("Integration", coerce=int, validators=[DataRequired()])
    external_identifier = StringField(
        "External Identifier",
        description="Owner/repo (GitHub), group/project (GitLab), or project key (Jira)",
        validators=[DataRequired(), Length(max=255)],
    )
    jira_jql = TextAreaField(
        "Jira JQL Override",
        description="Optional: custom JQL query to scope issues (defaults to project key).",
        validators=[Optional(), Length(max=2000)],
    )
    # Per-project credential overrides
    override_api_token = PasswordField(
        "Override API Token",
        description="Optional: project-specific token (overrides tenant integration)",
        validators=[Optional(), Length(max=4096)],
    )
    override_base_url = StringField(
        "Override Base URL",
        description="Optional: project-specific instance URL (e.g., https://gitlab.private.com)",
        validators=[Optional(), Length(max=512)],
    )
    override_username = StringField(
        "Override Username",
        description="Optional: project-specific username (for Jira email)",
        validators=[Optional(), Length(max=255)],
    )
    link = SubmitField("Link Project")


class ProjectIntegrationUpdateForm(FlaskForm):
    external_identifier = StringField(
        "External Identifier", validators=[DataRequired(), Length(max=255)]
    )
    jira_jql = TextAreaField(
        "Jira JQL Override",
        validators=[Optional(), Length(max=2000)],
    )
    # Per-project credential overrides
    override_api_token = PasswordField(
        "Override API Token",
        description="Optional: project-specific token (leave blank to keep existing)",
        validators=[Optional(), Length(max=4096)],
    )
    override_base_url = StringField(
        "Override Base URL",
        description="Optional: project-specific instance URL",
        validators=[Optional(), Length(max=512)],
    )
    override_username = StringField(
        "Override Username",
        description="Optional: project-specific username (for Jira email)",
        validators=[Optional(), Length(max=255)],
    )
    auto_sync_enabled = BooleanField(
        "Auto-sync enabled",
        description="Automatically sync issues from this integration on a schedule",
        default=True,
    )
    submit = SubmitField("Update Link")


class ProjectIntegrationDeleteForm(FlaskForm):
    submit = SubmitField("Remove Link")


class ProjectDeleteForm(FlaskForm):
    project_id = HiddenField(validators=[DataRequired()])
    submit = SubmitField("Remove Project")


class TenantDeleteForm(FlaskForm):
    tenant_id = HiddenField(validators=[DataRequired()])
    submit = SubmitField("Remove Tenant")


class TenantAppearanceForm(FlaskForm):
    tenant_id = HiddenField(validators=[DataRequired()])
    color = SelectField(
        "Tenant Color",
        validators=[DataRequired()],
        choices=TENANT_COLOR_CHOICES,
        default=DEFAULT_TENANT_COLOR,
    )
    save = SubmitField("Save")


class SSHKeyDeleteForm(FlaskForm):
    key_id = HiddenField(validators=[DataRequired()])
    submit = SubmitField("Remove Key")


class ProjectIssueSyncForm(FlaskForm):
    project_id = HiddenField(validators=[DataRequired()])
    submit = SubmitField("Refresh Issues")


class IssueDashboardCreateForm(FlaskForm):
    project_integration_id = SelectField(
        "Project",
        coerce=int,
        validators=[DataRequired()],
        description="Select the integration to create an issue for.",
    )
    summary = StringField(
        "Title",
        validators=[DataRequired(), Length(max=255)],
        render_kw={"placeholder": "Describe the bug or feature"},
    )
    description = TextAreaField(
        "Description",
        validators=[Optional(), Length(max=5000)],
        render_kw={"rows": 5},
    )
    issue_type = StringField(
        "Issue Type",
        validators=[Optional(), Length(max=128)],
        description="Jira only. Defaults to the integration's type if left blank.",
    )
    labels = StringField(
        "Labels / Tags",
        validators=[Optional(), Length(max=512)],
        description="Comma-separated labels (GitHub/GitLab/Jira).",
    )
    assignee_user_id = SelectField(
        "Assignee",
        coerce=int,
        validators=[Optional()],
        description="Requires a mapped identity for the selected provider.",
    )
    milestone = StringField(
        "Milestone",
        validators=[Optional(), Length(max=255)],
        description="GitHub accepts number or title; GitLab matches milestone title.",
    )
    priority = StringField(
        "Priority",
        validators=[Optional(), Length(max=128)],
        description="Jira priority name (e.g. Highest, High, Medium).",
    )
    submit = SubmitField("Create Issue")


class ProjectGitRefreshForm(FlaskForm):
    project_id = HiddenField(validators=[DataRequired()])
    branch = StringField("Branch", validators=[Length(max=128)])
    submit = SubmitField("Pull Latest")
    clean_submit = SubmitField("Clean Pull")


class UpdateApplicationForm(FlaskForm):
    restart = BooleanField("Restart application after update")
    branch = SelectField(
        "Git branch",
        choices=[],
        validators=[Optional()],
        validate_choice=False,
    )
    next = HiddenField()
    submit = SubmitField("Run Update")


class QuickBranchSwitchForm(FlaskForm):
    branch = SelectField(
        "Git branch",
        choices=[],
        validators=[DataRequired()],
        validate_choice=False,
    )
    next = HiddenField()
    submit = SubmitField("Switch & Restart")


class MigrationRunForm(FlaskForm):
    next = HiddenField()
    submit = SubmitField("Run Database Migrations")


class TmuxResyncForm(FlaskForm):
    next = HiddenField()
    submit = SubmitField("Resync tmux")


class PermissionsCheckForm(FlaskForm):
    next = HiddenField()
    submit = SubmitField("Check Permissions")


class PermissionsFixForm(FlaskForm):
    next = HiddenField()
    submit = SubmitField("Fix Permissions")


class AIToolUpdateForm(FlaskForm):
    next = HiddenField()
    source = HiddenField(validators=[DataRequired(), Length(max=32)])


class ProjectBranchForm(FlaskForm):
    project_id = HiddenField(validators=[DataRequired()])
    branch_name = StringField("Branch", validators=[Length(max=128)])
    base_branch = StringField("Base Branch", validators=[Length(max=128)])
    merge_source = StringField("Source Branch", validators=[Length(max=128)])
    merge_target = StringField("Target Branch", validators=[Length(max=128)])
    checkout_submit = SubmitField("Checkout/Create")
    merge_submit = SubmitField("Merge Branch")
    delete_branch = StringField("Delete Branch", validators=[Length(max=128)])
    delete_submit = SubmitField("Delete Branch")


class CreateUserForm(FlaskForm):
    name = StringField("Full Name", validators=[DataRequired(), Length(max=255)])
    email = StringField("Email", validators=[DataRequired(), Length(max=255)])
    password = PasswordField(
        "Password", validators=[DataRequired(), Length(min=8, max=255)]
    )
    is_admin = BooleanField("Grant administrator access", default=False)
    submit = SubmitField("Create User")

    def validate_email(self, field):
        from ..models import User

        raw = (field.data or "").strip()
        email = raw.lower()
        if "@" not in email:
            raise ValidationError("Enter a valid email address.")
        if User.query.filter_by(email=email).first():
            raise ValidationError("A user with this email already exists.")
        field.data = raw


class UserUpdateForm(FlaskForm):
    user_id = HiddenField(validators=[DataRequired()])
    name = StringField("Full Name", validators=[DataRequired(), Length(max=255)])
    email = StringField("Email", validators=[DataRequired(), Length(max=255)])
    is_admin = BooleanField("Grant administrator access", default=False)
    linux_username = SelectField(
        "Linux Shell User",
        validators=[Optional()],
        choices=[],
        render_kw={
            "aria-description": "Select the Linux system user for tmux sessions"
        },
    )
    submit = SubmitField("Save Changes")

    def validate_email(self, field):
        from ..models import User

        raw = (field.data or "").strip()
        email = raw.lower()
        if "@" not in email:
            raise ValidationError("Enter a valid email address.")

        query = User.query.filter(User.email == email)
        if self.user_id.data:
            try:
                current_id = int(self.user_id.data)
            except (TypeError, ValueError):
                current_id = None
            if current_id:
                query = query.filter(User.id != current_id)

        if query.first():
            raise ValidationError("A user with this email already exists.")

        field.data = raw


class UserToggleAdminForm(FlaskForm):
    user_id = HiddenField(validators=[DataRequired()])
    submit = SubmitField("Toggle Admin")


class UserResetPasswordForm(FlaskForm):
    user_id = HiddenField(validators=[DataRequired()])
    password = PasswordField(
        "New Password", validators=[DataRequired(), Length(min=8, max=255)]
    )
    submit = SubmitField("Reset Password")


class UserDeleteForm(FlaskForm):
    user_id = HiddenField(validators=[DataRequired()])
    submit = SubmitField("Delete User")


class LinuxUserMappingForm(FlaskForm):
    """Form for configuring Linux user mapping for tmux sessions.

    Users input a JSON mapping like:
    {"user@example.com": "user", "other@example.com": "other"}
    """

    mapping_json = TextAreaField(
        "Linux User Mapping (JSON)",
        validators=[DataRequired()],
        render_kw={
            "rows": 10,
            "placeholder": '{"user@example.com": "linux_username", ...}',
            "aria-description": "JSON object mapping aiops user email to Linux system username",
        },
    )
    submit = SubmitField("Save Linux User Mapping")


class UserIdentityMapForm(FlaskForm):
    """Form for managing user identity mappings across issue providers."""

    user_id = SelectField("User", coerce=int, validators=[DataRequired()])
    github_username = StringField(
        "GitHub Username",
        validators=[Optional(), Length(max=255)],
        render_kw={"placeholder": "octocat"},
    )
    gitlab_username = StringField(
        "GitLab Username",
        validators=[Optional(), Length(max=255)],
        render_kw={"placeholder": "username"},
    )
    jira_account_id = StringField(
        "Jira Account ID",
        validators=[Optional(), Length(max=255)],
        render_kw={"placeholder": "5a1234567890abcdef123456"},
    )
    submit = SubmitField("Save Identity Mapping")


class UserIdentityMapDeleteForm(FlaskForm):
    """Form for deleting user identity mappings."""

    user_id = HiddenField(validators=[DataRequired()])
    submit = SubmitField("Delete Identity Mapping")


class APIKeyCreateForm(FlaskForm):
    """Form for creating API keys."""

    name = StringField(
        "Key Name",
        validators=[DataRequired(), Length(max=255)],
        render_kw={"placeholder": "My API Key"},
    )
    scopes = SelectField(
        "Permissions",
        choices=[
            ("read", "Read Only - View resources"),
            ("read,write", "Read & Write - Modify resources"),
            ("read,write,admin", "Full Access - Administrative privileges"),
        ],
        validators=[DataRequired()],
    )
    expires_days = SelectField(
        "Expiration",
        choices=[
            ("", "Never"),
            ("30", "30 days"),
            ("90", "90 days"),
            ("180", "180 days"),
            ("365", "1 year"),
        ],
        validators=[Optional()],
    )
    submit = SubmitField("Create API Key")


class APIKeyRevokeForm(FlaskForm):
    """Form for revoking/deleting API keys."""

    key_id = HiddenField(validators=[DataRequired()])
    submit = SubmitField("Revoke Key")


class GlobalAgentContextForm(FlaskForm):
    """Form for editing global agent context."""

    content = TextAreaField(
        "Global Agent Context",
        validators=[DataRequired()],
        render_kw={
            "rows": 20,
            "placeholder": (
                "Enter global AGENTS.md content that will appear "
                "in all AGENTS.override.md files..."
            ),
        },
    )
    submit = SubmitField("Save Global Context")


class GlobalAgentContextClearForm(FlaskForm):
    """Form for clearing global agent context."""

    submit = SubmitField("Clear Global Context")


class BackupCreateForm(FlaskForm):
    """Form for creating database backups."""

    description = StringField(
        "Description",
        validators=[Optional(), Length(max=255)],
        render_kw={"placeholder": "Optional description of this backup"},
    )
    submit = SubmitField("Create Backup")


class BackupRestoreForm(FlaskForm):
    """Form for restoring from a backup."""

    backup_id = HiddenField(validators=[DataRequired()])
    submit = SubmitField("Restore Backup")


class BackupDeleteForm(FlaskForm):
    """Form for deleting a backup."""

    backup_id = HiddenField(validators=[DataRequired()])
    submit = SubmitField("Delete Backup")


class UserCredentialCreateForm(FlaskForm):
    """Form for creating/updating a user integration credential."""

    integration_id = SelectField(
        "Integration",
        coerce=int,
        validators=[DataRequired()],
        description="Select the integration to override with your personal token",
    )
    api_token = StringField(
        "API Token",
        validators=[DataRequired(), Length(max=512)],
        description="Your personal access token (GitLab PAT, GitHub token, or Jira API token)",
    )
    submit = SubmitField("Save Personal Token")


class UserCredentialDeleteForm(FlaskForm):
    """Form for deleting a user integration credential."""

    credential_id = HiddenField(validators=[DataRequired()])
    submit = SubmitField("Remove Token")


class AIAssistedIssueForm(FlaskForm):
    """Form for creating an issue with AI assistance."""

    description = TextAreaField(
        "Description",
        validators=[DataRequired(), Length(min=10, max=5000)],
        description="Describe what you want to work on in natural language",
        render_kw={"placeholder": "Example: I want to add user authentication with OAuth2..."},
    )
    project_id = SelectField(
        "Project",
        coerce=int,
        validators=[DataRequired()],
    )
    integration_id = SelectField(
        "Integration",
        coerce=int,
        validators=[DataRequired()],
        description="Select which integration to use for creating the issue",
    )
    ai_tool = SelectField(
        "AI Tool",
        choices=[
            ("claude", "Claude"),
            ("codex", "Codex"),
        ],
        default="claude",
        validators=[DataRequired()],
    )
    issue_type = SelectField(
        "Issue Type",
        choices=[
            ("", "Auto-detect"),
            ("feature", "Feature"),
            ("bug", "Bug"),
        ],
        default="",
        validators=[Optional()],
    )
    creator_user_id = SelectField(
        "Created By",
        coerce=int,
        validators=[DataRequired()],
        description="Select which user to attribute this issue to",
    )
    submit = SubmitField("Generate Issue Preview")


class YadmSettingsForm(FlaskForm):
    """Form for managing global yadm (dotfiles) configuration."""

    dotfile_repo_url = URLField(
        "Dotfiles Repository URL",
        validators=[
            DataRequired(),
            URL(),
        ],
        render_kw={
            "placeholder": "https://gitlab.com/floads/dotfiles",
            "aria-description": "Git repository URL containing organization dotfiles (e.g., .bashrc, .zshrc, .gitconfig)",
        },
    )
    dotfile_repo_branch = StringField(
        "Repository Branch",
        validators=[
            DataRequired(),
            Length(min=1, max=128),
        ],
        default="main",
        render_kw={
            "placeholder": "main",
            "aria-description": "Git branch to clone from (default: main)",
        },
    )
    decrypt_password = PasswordField(
        "Decryption Password (Optional)",
        validators=[Optional(), Length(min=1, max=512)],
        render_kw={
            "placeholder": "Leave empty if using GPG encryption instead",
            "aria-description": "Password for decrypting yadm-encrypted files. Only required if files are encrypted with a passphrase (not GPG).",
        },
    )
    submit = SubmitField("Save Dotfiles Configuration")


class YadmPersonalConfigForm(FlaskForm):
    """Form for personal dotfiles configuration override."""

    personal_dotfile_repo_url = StringField(
        "Personal Dotfiles Repository URL",
        validators=[Optional(), Length(max=512), validate_dotfiles_url],
        render_kw={
            "placeholder": "https://github.com/yourname/dotfiles or git@github.com:yourname/dotfiles.git",
            "aria-description": "Override organization defaults with your personal dotfiles repository. Supports HTTPS and Git SSH URLs.",
        },
    )
    personal_dotfile_branch = StringField(
        "Repository Branch",
        validators=[Optional(), Length(min=1, max=128)],
        render_kw={
            "placeholder": "main",
            "aria-description": "Git branch to use for personal dotfiles",
        },
    )
    clear_override = BooleanField(
        "Clear override and use global configuration",
        render_kw={
            "aria-description": "Check this to remove your personal override and use the organization-wide dotfiles configuration"
        },
    )
    submit = SubmitField("Save Configuration")
