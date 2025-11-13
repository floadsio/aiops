import re

from flask_wtf import FlaskForm  # type: ignore
from wtforms import PasswordField, StringField
from wtforms.validators import DataRequired, ValidationError

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class SimpleEmail:
    def __call__(self, form, field):
        value = (field.data or "").strip()
        if not EMAIL_REGEX.match(value):
            raise ValidationError("Invalid email address.")


class LoginForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), SimpleEmail()])
    password = PasswordField("Password", validators=[DataRequired()])
