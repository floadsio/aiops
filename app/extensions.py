from flask_login import LoginManager  # type: ignore
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect  # type: ignore

db = SQLAlchemy()


class BaseModel(db.Model):  # type: ignore
    __abstract__ = True


login_manager = LoginManager()
csrf = CSRFProtect()
migrate = Migrate()

login_manager.login_view = "auth.login"
