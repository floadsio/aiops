import shlex
from types import SimpleNamespace

from app import create_app
from app.config import Config
from app.ai_sessions import create_session
from app.services.git_service import build_project_git_env


class FakePane:
    def __init__(self):
        self.commands = []

    def send_keys(self, command, enter=False):
        self.commands.append((command, enter))


class FakeWindow:
    def __init__(self, name):
        self._name = name
        self._pane = FakePane()

    def get(self, key):
        if key == "window_name":
            return self._name
        if key == "window_created":
            return None
        return None

    def select_window(self):
        return None

    @property
    def attached_pane(self):
        return self._pane

    @property
    def panes(self):
        return [self._pane]


class FakeSession:
    def __init__(self, name, window):
        self._name = name
        self._window = window

    def get(self, key):
        if key == "session_name":
            return self._name
        return None


def test_create_session_uses_shared_tmux_window(monkeypatch, tmp_path):
    class TestConfig(Config):
        TESTING = True
        WTF_CSRF_ENABLED = False
        REPO_STORAGE_PATH = str(tmp_path / "repos")

    app = create_app(TestConfig, instance_path=tmp_path / "instance")

    with app.app_context():
        project_path = tmp_path / "repos" / "demo"
        project_path.mkdir(parents=True, exist_ok=True)
        project = SimpleNamespace(
            id=1,
            name="Demo Project",
            local_path=str(project_path),
            tenant=SimpleNamespace(name="Tenant Beta"),
        )

        pane = FakePane()
        window = FakeWindow("demo-project-p1")
        window._pane = pane
        session_obj = FakeSession("aiops", window)

        monkeypatch.setattr(
            "app.ai_sessions.ensure_project_window",
            lambda project, window_name=None, session_name=None: (session_obj, window, True),
        )
        monkeypatch.setattr("app.ai_sessions.shutil.which", lambda _: "/usr/bin/tmux")
        monkeypatch.setattr("app.ai_sessions.pty.fork", lambda: (1234, 56))
        monkeypatch.setattr("app.ai_sessions._set_winsize", lambda *_, **__: None)

        class DummyThread:
            def __init__(self, *_, **__):
                pass

            def start(self):
                pass

        monkeypatch.setattr("app.ai_sessions.threading.Thread", lambda *a, **k: DummyThread())

        captured = {}

        def fake_register(session):
            captured["session"] = session
            return session

        monkeypatch.setattr("app.ai_sessions._register_session", fake_register)

        session = create_session(project, user_id=99)

        expected_command = app.config["ALLOWED_AI_TOOLS"]["codex"]
        assert session.command == expected_command
        assert session.tmux_target == "aiops:demo-project-p1"
        assert session.pid == 1234
        assert session.fd == 56
        assert captured["session"] is session
        git_env = build_project_git_env(project)
        expected_export = f"export GIT_SSH_COMMAND={shlex.quote(git_env['GIT_SSH_COMMAND'])}"
        assert pane.commands[0] == (expected_export, True)
        assert pane.commands[1] == ("clear", True)
        assert pane.commands[2] == (expected_command, True)


def test_create_session_respects_explicit_tmux_target(monkeypatch, tmp_path):
    class TestConfig(Config):
        TESTING = True
        WTF_CSRF_ENABLED = False
        REPO_STORAGE_PATH = str(tmp_path / "repos")

    app = create_app(TestConfig, instance_path=tmp_path / "instance")

    with app.app_context():
        project_path = tmp_path / "repos" / "demo"
        project_path.mkdir(parents=True, exist_ok=True)
        project = SimpleNamespace(
            id=2,
            name="Demo Project",
            local_path=str(project_path),
            tenant=SimpleNamespace(name="Tenant Beta"),
        )

        session_obj = FakeSession("aiops", FakeWindow("demo-project-p2"))

        captured: dict[str, str] = {}

        def fake_ensure(project, window_name=None, session_name=None):
            captured["window_name"] = window_name
            pane = FakePane()
            window = FakeWindow(window_name or "demo-project-p2")
            window._pane = pane
            return session_obj, window, True

        monkeypatch.setattr("app.ai_sessions.ensure_project_window", fake_ensure)
        monkeypatch.setattr("app.ai_sessions.shutil.which", lambda _: "/usr/bin/tmux")
        monkeypatch.setattr("app.ai_sessions.pty.fork", lambda: (4321, 65))
        monkeypatch.setattr("app.ai_sessions._set_winsize", lambda *_, **__: None)

        class DummyThread:
            def __init__(self, *_, **__):
                pass

            def start(self):
                pass

        monkeypatch.setattr("app.ai_sessions.threading.Thread", lambda *a, **k: DummyThread())

        monkeypatch.setattr("app.ai_sessions._register_session", lambda session: session)

        session = create_session(
            project,
            user_id=101,
            tmux_target="aiops:tenant-tooling",
        )

        assert captured["window_name"] == "tenant-tooling"
        assert session.tmux_target == "aiops:tenant-tooling"


def test_reuse_existing_tmux_window_does_not_restart_command(monkeypatch, tmp_path):
    class TestConfig(Config):
        TESTING = True
        WTF_CSRF_ENABLED = False
        REPO_STORAGE_PATH = str(tmp_path / "repos")

    app = create_app(TestConfig, instance_path=tmp_path / "instance")

    with app.app_context():
        project_path = tmp_path / "repos" / "demo"
        project_path.mkdir(parents=True, exist_ok=True)
        project = SimpleNamespace(
            id=3,
            name="Demo Project",
            local_path=str(project_path),
            tenant=SimpleNamespace(name="Tenant Beta"),
        )

        pane = FakePane()
        window = FakeWindow("demo-project-p3")
        window._pane = pane
        session_obj = FakeSession("aiops", window)

        monkeypatch.setattr(
            "app.ai_sessions.ensure_project_window",
            lambda project, window_name=None, session_name=None: (session_obj, window, False),
        )
        monkeypatch.setattr("app.ai_sessions.shutil.which", lambda _: "/usr/bin/tmux")
        monkeypatch.setattr("app.ai_sessions.pty.fork", lambda: (9876, 54))
        monkeypatch.setattr("app.ai_sessions._set_winsize", lambda *_, **__: None)

        class DummyThread:
            def __init__(self, *_, **__):
                pass

            def start(self):
                pass

        monkeypatch.setattr("app.ai_sessions.threading.Thread", lambda *a, **k: DummyThread())
        monkeypatch.setattr("app.ai_sessions._register_session", lambda session: session)

        session = create_session(project, user_id=202, tmux_target="aiops:demo-project-p3")

        expected_command = app.config["ALLOWED_AI_TOOLS"]["codex"]
        assert session.command == expected_command
        assert pane.commands == []
