from __future__ import annotations

from flask_wtf import FlaskForm
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
from wtforms.validators import DataRequired, Length, Optional, URL, ValidationError
from urllib.parse import urlparse


class TenantForm(FlaskForm):
    name = StringField("Name", validators=[DataRequired(), Length(max=255)])
    description = TextAreaField("Description", validators=[Length(max=1000)])


def validate_repo_url(form, field):
    value = (field.data or "").strip()
    if not value:
        raise ValidationError("Repository URL is required.")

    if value.startswith("git@"):
        if ":" not in value:
            raise ValidationError("SSH URLs must follow git@host:owner/repo.git format.")
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


class ProjectForm(FlaskForm):
    name = StringField("Name", validators=[DataRequired(), Length(max=255)])
    repo_url = StringField(
        "Repository URL",
        validators=[DataRequired(), Length(max=512), validate_repo_url],
        render_kw={"placeholder": "https://example.com/org/repo.git or git@example.com:org/repo.git"},
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
    api_token = PasswordField("API Token", validators=[DataRequired(), Length(max=4096)])
    jira_email = StringField(
        "Jira Account Email",
        description="Atlassian account email used with the API token (required for Jira Cloud).",
        validators=[Optional(), Length(max=255)],
    )
    enabled = BooleanField("Enabled", default=True)
    save = SubmitField("Save Integration")


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
    link = SubmitField("Link Project")


class ProjectIntegrationUpdateForm(FlaskForm):
    external_identifier = StringField(
        "External Identifier", validators=[DataRequired(), Length(max=255)]
    )
    jira_jql = TextAreaField(
        "Jira JQL Override",
        validators=[Optional(), Length(max=2000)],
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


class SSHKeyDeleteForm(FlaskForm):
    key_id = HiddenField(validators=[DataRequired()])
    submit = SubmitField("Remove Key")


class ProjectIssueSyncForm(FlaskForm):
    project_id = HiddenField(validators=[DataRequired()])
    submit = SubmitField("Refresh Issues")


class ProjectGitRefreshForm(FlaskForm):
    project_id = HiddenField(validators=[DataRequired()])
    submit = SubmitField("Pull Latest")


class UpdateApplicationForm(FlaskForm):
    restart = BooleanField("Restart application after update")
    next = HiddenField()
    submit = SubmitField("Run Update")


class CreateUserForm(FlaskForm):
    name = StringField("Full Name", validators=[DataRequired(), Length(max=255)])
    email = StringField("Email", validators=[DataRequired(), Length(max=255)])
    password = PasswordField("Password", validators=[DataRequired(), Length(min=8, max=255)])
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


class UserToggleAdminForm(FlaskForm):
    user_id = HiddenField(validators=[DataRequired()])
    submit = SubmitField("Toggle Admin")


class UserResetPasswordForm(FlaskForm):
    user_id = HiddenField(validators=[DataRequired()])
    password = PasswordField("New Password", validators=[DataRequired(), Length(min=8, max=255)])
    submit = SubmitField("Reset Password")


class UserDeleteForm(FlaskForm):
    user_id = HiddenField(validators=[DataRequired()])
    submit = SubmitField("Delete User")
