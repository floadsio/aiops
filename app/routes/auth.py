from __future__ import annotations

from flask import Blueprint, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user  # type: ignore

from ..forms.auth import LoginForm
from ..models import User
from ..security import LoginUser, verify_password

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("admin.dashboard"))
    return render_template("index.html")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower()).first()
        if user and verify_password(user.password_hash, form.password.data):
            login_user(LoginUser(user), remember=True)
            next_url = request.args.get("next") or url_for("admin.dashboard")
            return redirect(next_url)
        form.password.errors.append("Invalid credentials.")
    return render_template("auth/login.html", form=form)


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
