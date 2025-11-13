from __future__ import annotations

from flask_wtf import FlaskForm  # type: ignore
from wtforms import (
    BooleanField,
    HiddenField,
    IntegerField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Length, Optional


class AIRunForm(FlaskForm):
    ai_tool = SelectField("AI Tool", validators=[Optional()], choices=[])
    prompt = TextAreaField("Prompt", validators=[Length(max=2000)])


class GitActionForm(FlaskForm):
    action = SelectField(
        "Action",
        choices=[
            ("pull", "Pull Latest"),
            ("push", "Push Changes"),
            ("status", "Show Status"),
        ],
        validators=[DataRequired()],
    )
    ref = StringField("Ref", description="Optional branch or tag")
    clean_pull = BooleanField(
        "Clean pull (discard local changes before pulling)",
        false_values={False, "false", "", 0, "0"},
    )
    submit = SubmitField("Execute Git Action")


class AnsibleForm(FlaskForm):
    semaphore_project_id = IntegerField(
        "Semaphore Project ID",
        validators=[DataRequired()],
        description="Project identifier inside Semaphore.",
    )
    template_id = SelectField(
        "Template",
        validators=[DataRequired()],
        choices=[],
        coerce=int,
        description="Semaphore template to launch.",
    )
    playbook = StringField("Playbook Override", validators=[Length(max=255)])
    git_branch = StringField("Git Branch", validators=[Length(max=255)])
    arguments = TextAreaField("Arguments (JSON/YAML)", validators=[Length(max=2000)])
    limit = StringField("Limit", validators=[Length(max=255)])
    message = StringField("Message", validators=[Length(max=255)])
    inventory_id = IntegerField("Inventory Override", validators=[Optional()])
    dry_run = BooleanField("Dry Run")
    debug = BooleanField("Debug")
    diff = BooleanField("Show Diff")
    submit = SubmitField("Run Task")


class IssueCreateForm(FlaskForm):
    integration_id = HiddenField(validators=[DataRequired()])
    summary = StringField(
        "Issue Summary",
        validators=[DataRequired(), Length(max=255)],
        render_kw={"placeholder": "What needs to happen?"},
    )
    description = TextAreaField(
        "Description",
        validators=[Optional(), Length(max=4000)],
        render_kw={"rows": 4, "placeholder": "Optional details or reproduction steps."},
    )
    issue_type = StringField(
        "Issue Type",
        validators=[Optional(), Length(max=128)],
        description="Defaults to the integration's configured issue type.",
    )
    labels = StringField(
        "Labels",
        validators=[Optional(), Length(max=512)],
        description="Comma-separated labels.",
    )
    submit = SubmitField("Create Issue")


class ProjectKeyForm(FlaskForm):
    ssh_key_id = SelectField("SSH Key", coerce=int, validators=[Optional()])
    submit = SubmitField("Update SSH Key")


class AgentFileForm(FlaskForm):
    contents = TextAreaField(
        "AGENTS.override.md Contents",
        validators=[Optional()],
        render_kw={
            "rows": 24,
            "spellcheck": "false",
            "class": "code-editor",
        },
    )
    commit_message = StringField(
        "Commit Message",
        validators=[Optional(), Length(max=255)],
        render_kw={"placeholder": "Update AGENTS.override.md"},
    )
    save = SubmitField("Save Changes")
    save_and_push = SubmitField("Save, Commit & Push")
