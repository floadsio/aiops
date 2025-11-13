from __future__ import annotations

from flask_login import UserMixin  # type: ignore
from werkzeug.security import check_password_hash, generate_password_hash


def hash_password(password: str) -> str:
    return generate_password_hash(password, method="pbkdf2:sha256")


def verify_password(password_hash: str, candidate: str) -> bool:
    return check_password_hash(password_hash, candidate)


class LoginUser(UserMixin):
    """Adapter to satisfy Flask-Login interface."""

    def __init__(self, db_user) -> None:
        self._db_user = db_user

    def get_id(self) -> str:
        return str(self._db_user.id)

    @property
    def email(self) -> str:
        return self._db_user.email

    @property
    def is_admin(self) -> bool:
        return self._db_user.is_admin

    @property
    def model(self):
        return self._db_user

    def __getattr__(self, item):
        return getattr(self._db_user, item)
