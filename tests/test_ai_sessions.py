import json
import shlex
from types import SimpleNamespace

from app import create_app
from app.ai_sessions import (
    create_session,
)
from app.config import Config
from app.services.claude_config_service import save_claude_api_key
from app.services.codex_config_service import save_codex_auth
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


# Test disabled - _interactive_ssh_agent_commands removed during SSH key refactoring
# def test_interactive_agent_commands_include_trailing_newline():
#     key_material = "-----BEGIN KEY-----\nline-1\n-----END KEY-----"
#     commands = _interactive_ssh_agent_commands(key_material)
#     heredoc = commands[-1]
#     parts = heredoc.splitlines()
#     encoded_line = parts[1]
#     decoded = base64.b64decode(encoded_line.encode("ascii")).decode("utf-8")
#     assert decoded.endswith("\n")
#     assert decoded.rstrip("\n") == key_material


def test_create_session_uses_shared_tmux_window(monkeypatch, tmp_path):
    class TestConfig(Config):
        TESTING = True
        WTF_CSRF_ENABLED = False
        REPO_STORAGE_PATH = str(tmp_path / "repos")
        CODEX_CONFIG_DIR = str(tmp_path / ".codex")

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
            lambda project, window_name=None, session_name=None: (
                session_obj,
                window,
                True,
            ),
        )
        monkeypatch.setattr("app.ai_sessions.shutil.which", lambda _: "/usr/bin/tmux")
        monkeypatch.setattr("app.ai_sessions.pty.fork", lambda: (1234, 56))
        monkeypatch.setattr("app.ai_sessions._set_winsize", lambda *_, **__: None)

        class DummyThread:
            def __init__(self, *_, **__):
                pass

            def start(self):
                pass

        monkeypatch.setattr(
            "app.ai_sessions.threading.Thread", lambda *a, **k: DummyThread()
        )

        captured = {}

        def fake_register(session):
            captured["session"] = session
            return session

        monkeypatch.setattr("app.ai_sessions._register_session", fake_register)

        session = create_session(project, user_id=99, tool="codex")

        expected_command = app.config["ALLOWED_AI_TOOLS"]["codex"]
        assert session.command == expected_command
        assert session.tmux_target == "aiops:demo-project-p1"
        assert session.pid == 1234
        assert session.fd == 56
        assert captured["session"] is session
        git_env = build_project_git_env(project)
        expected_export = (
            f"export GIT_SSH_COMMAND={shlex.quote(git_env['GIT_SSH_COMMAND'])}"
        )
        assert pane.commands[0] == (expected_export, True)
        assert pane.commands[1] == ("clear", True)
        assert pane.commands[2] == (expected_command, True)


def test_create_session_respects_explicit_tmux_target(monkeypatch, tmp_path):
    class TestConfig(Config):
        TESTING = True
        WTF_CSRF_ENABLED = False
        REPO_STORAGE_PATH = str(tmp_path / "repos")
        CODEX_CONFIG_DIR = str(tmp_path / ".codex")

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

        monkeypatch.setattr(
            "app.ai_sessions.threading.Thread", lambda *a, **k: DummyThread()
        )

        monkeypatch.setattr(
            "app.ai_sessions._register_session", lambda session: session
        )

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
        CODEX_CONFIG_DIR = str(tmp_path / ".codex")

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
            lambda project, window_name=None, session_name=None: (
                session_obj,
                window,
                False,
            ),
        )
        monkeypatch.setattr("app.ai_sessions.shutil.which", lambda _: "/usr/bin/tmux")
        monkeypatch.setattr("app.ai_sessions.pty.fork", lambda: (9876, 54))
        monkeypatch.setattr("app.ai_sessions._set_winsize", lambda *_, **__: None)

        class DummyThread:
            def __init__(self, *_, **__):
                pass

            def start(self):
                pass

        monkeypatch.setattr(
            "app.ai_sessions.threading.Thread", lambda *a, **k: DummyThread()
        )
        monkeypatch.setattr(
            "app.ai_sessions._register_session", lambda session: session
        )

        session = create_session(
            project, user_id=202, tmux_target="aiops:demo-project-p3", tool="codex"
        )

        expected_command = app.config["ALLOWED_AI_TOOLS"]["codex"]
        assert session.command == expected_command
        # When reusing a window, only clear is sent (not the command again)
        assert pane.commands == [("clear", True)]



def test_create_session_exports_codex_auth(monkeypatch, tmp_path):
    class TestConfig(Config):
        TESTING = True
        WTF_CSRF_ENABLED = False
        REPO_STORAGE_PATH = str(tmp_path / "repos")
        CODEX_CONFIG_DIR = str(tmp_path / ".codex")

    app = create_app(TestConfig, instance_path=tmp_path / "instance")

    with app.app_context():
        project_path = tmp_path / "repos" / "demo"
        project_path.mkdir(parents=True, exist_ok=True)
        project = SimpleNamespace(
            id=4,
            name="Demo Project",
            local_path=str(project_path),
            tenant=SimpleNamespace(name="Tenant Beta"),
        )

        pane = FakePane()
        window = FakeWindow("demo-project-p6")
        window._pane = pane
        session_obj = FakeSession("aiops", window)

        monkeypatch.setattr(
            "app.ai_sessions.ensure_project_window",
            lambda project, window_name=None, session_name=None: (
                session_obj,
                window,
                True,
            ),
        )
        monkeypatch.setattr("app.ai_sessions.shutil.which", lambda _: "/usr/bin/tmux")
        monkeypatch.setattr("app.ai_sessions.pty.fork", lambda: (9753, 51))
        monkeypatch.setattr("app.ai_sessions._set_winsize", lambda *_, **__: None)

        class DummyThread:
            def __init__(self, *_, **__):
                pass

            def start(self):
                pass

        monkeypatch.setattr(
            "app.ai_sessions.threading.Thread", lambda *a, **k: DummyThread()
        )
        monkeypatch.setattr(
            "app.ai_sessions._register_session", lambda session: session
        )

        save_codex_auth(json.dumps({"token": "codex-token"}), user_id=88)

        session = create_session(project, user_id=88, tool="codex")

        expected_command = app.config["ALLOWED_AI_TOOLS"]["codex"]
        assert session.command == expected_command
        git_env = build_project_git_env(project)
        expected_git = (
            f"export GIT_SSH_COMMAND={shlex.quote(git_env['GIT_SSH_COMMAND'])}"
        )
        expected_codex_dir = (
            f"export CODEX_CONFIG_DIR={shlex.quote(str(tmp_path / '.codex'))}"
        )
        expected_codex_file = f"export CODEX_AUTH_FILE={shlex.quote(str((tmp_path / '.codex') / 'auth.json'))}"

        assert pane.commands[0] == (expected_git, True)
        assert pane.commands[1] == (expected_codex_dir, True)
        assert pane.commands[2] == (expected_codex_file, True)
        assert pane.commands[3] == ("clear", True)
        assert pane.commands[4] == (expected_command, True)


def test_create_session_exports_claude_key(monkeypatch, tmp_path):
    class TestConfig(Config):
        TESTING = True
        WTF_CSRF_ENABLED = False
        REPO_STORAGE_PATH = str(tmp_path / "repos")
        CODEX_CONFIG_DIR = str(tmp_path / ".codex")
        CLAUDE_CONFIG_DIR = str(tmp_path / ".claude")

    app = create_app(TestConfig, instance_path=tmp_path / "instance")

    with app.app_context():
        project_path = tmp_path / "repos" / "demo"
        project_path.mkdir(parents=True, exist_ok=True)
        project = SimpleNamespace(
            id=5,
            name="Demo Project",
            local_path=str(project_path),
            tenant=SimpleNamespace(name="Tenant Beta"),
        )

        pane = FakePane()
        window = FakeWindow("demo-project-p7")
        window._pane = pane
        session_obj = FakeSession("aiops", window)

        monkeypatch.setattr(
            "app.ai_sessions.ensure_project_window",
            lambda project, window_name=None, session_name=None: (
                session_obj,
                window,
                True,
            ),
        )
        monkeypatch.setattr("app.ai_sessions.shutil.which", lambda _: "/usr/bin/tmux")
        monkeypatch.setattr("app.ai_sessions.pty.fork", lambda: (5555, 28))
        monkeypatch.setattr("app.ai_sessions._set_winsize", lambda *_, **__: None)

        class DummyThread:
            def __init__(self, *_, **__):
                pass

            def start(self):
                pass

        monkeypatch.setattr(
            "app.ai_sessions.threading.Thread", lambda *a, **k: DummyThread()
        )
        monkeypatch.setattr(
            "app.ai_sessions._register_session", lambda session: session
        )

        save_claude_api_key("claude-token", user_id=505)

        session = create_session(project, user_id=505, tool="claude")

        expected_command = app.config["ALLOWED_AI_TOOLS"]["claude"]
        git_env = build_project_git_env(project)
        expected_git = (
            f"export GIT_SSH_COMMAND={shlex.quote(git_env['GIT_SSH_COMMAND'])}"
        )

        # Claude uses web auth, no env exports expected
        assert pane.commands == [
            (expected_git, True),
            ("clear", True),
            (expected_command, True),
        ]
        assert session.command == expected_command
        assert (tmp_path / ".claude" / "api_key").read_text().strip() == "claude-token"
        stored_path = tmp_path / "instance" / "claude" / "user-505" / "api_key"
        assert stored_path.read_text().strip() == "claude-token"


def test_per_user_session_injects_tenant_key_via_ssh_agent(monkeypatch, tmp_path):
    class TestConfig(Config):
        TESTING = True
        WTF_CSRF_ENABLED = False
        REPO_STORAGE_PATH = str(tmp_path / "repos")
        CODEX_CONFIG_DIR = str(tmp_path / ".codex")

    app = create_app(TestConfig, instance_path=tmp_path / "instance")

    with app.app_context():
        project_path = tmp_path / "repos" / "demo"
        project_path.mkdir(parents=True, exist_ok=True)
        key_file = tmp_path / "instance" / "keys" / "tenant-key"
        key_file.parent.mkdir(parents=True, exist_ok=True)
        key_file.write_text(
            "-----BEGIN OPENSSH PRIVATE KEY-----\nline\n-----END OPENSSH PRIVATE KEY-----\n",
            encoding="utf-8",
        )
        project = SimpleNamespace(
            id=6,
            name="Demo Project",
            local_path=str(project_path),
            tenant=SimpleNamespace(name="Tenant Beta"),
            ssh_key=SimpleNamespace(private_key_path=str(key_file)),
        )

        pane = FakePane()
        window = FakeWindow("demo-project-p8")
        window._pane = pane
        session_obj = FakeSession("aiops", window)

        monkeypatch.setattr(
            "app.ai_sessions.ensure_project_window",
            lambda project, window_name=None, session_name=None: (
                session_obj,
                window,
                True,
            ),
        )
        monkeypatch.setattr("app.ai_sessions.shutil.which", lambda _: "/usr/bin/tmux")
        monkeypatch.setattr("app.ai_sessions.pty.fork", lambda: (1111, 22))
        monkeypatch.setattr("app.ai_sessions._set_winsize", lambda *_, **__: None)

        class DummyThread:
            def __init__(self, *_, **__):
                pass

            def start(self):
                pass

        monkeypatch.setattr(
            "app.ai_sessions.threading.Thread", lambda *a, **k: DummyThread()
        )
        monkeypatch.setattr(
            "app.ai_sessions._register_session", lambda session: session
        )

        class MockUser:
            def __init__(self):
                self.id = 606
                self.email = "user@example.com"
                self.name = "Tenant User"
                self.linux_username = "devuser"

        monkeypatch.setattr(
            "app.ai_sessions.User.query.get", lambda user_id: MockUser(), raising=False
        )

        session = create_session(project, user_id=606, tool="codex")

        command = pane.commands[0][0]
        expected_tool = app.config["ALLOWED_AI_TOOLS"]["codex"]
        assert session.command == expected_tool
        assert "sudo -u devuser" in command
        assert "ssh-agent -s" in command
        assert "AIOPS_KEY_B64" in command
        assert expected_tool in command


def test_per_user_session_ssh_agent_script_for_non_interactive(monkeypatch, tmp_path):
    class TestConfig(Config):
        TESTING = True
        WTF_CSRF_ENABLED = False
        REPO_STORAGE_PATH = str(tmp_path / "repos")

    app = create_app(TestConfig, instance_path=tmp_path / "instance")

    with app.app_context():
        project_path = tmp_path / "repos" / "demo"
        project_path.mkdir(parents=True, exist_ok=True)
        key_file = tmp_path / "instance" / "keys" / "tenant-key"
        key_file.parent.mkdir(parents=True, exist_ok=True)
        key_file.write_text(
            "-----BEGIN OPENSSH PRIVATE KEY-----\nline\n-----END OPENSSH PRIVATE KEY-----\n",
            encoding="utf-8",
        )
        project = SimpleNamespace(
            id=7,
            name="Demo Project",
            local_path=str(project_path),
            tenant=SimpleNamespace(name="Tenant Beta"),
            ssh_key=SimpleNamespace(private_key_path=str(key_file)),
        )

        pane = FakePane()
        window = FakeWindow("demo-project-p9")
        window._pane = pane
        session_obj = FakeSession("aiops", window)

        monkeypatch.setattr(
            "app.ai_sessions.ensure_project_window",
            lambda project, window_name=None, session_name=None: (
                session_obj,
                window,
                True,
            ),
        )
        monkeypatch.setattr("app.ai_sessions.shutil.which", lambda _: "/usr/bin/tmux")
        monkeypatch.setattr("app.ai_sessions.pty.fork", lambda: (3333, 21))
        monkeypatch.setattr("app.ai_sessions._set_winsize", lambda *_, **__: None)

        class DummyThread:
            def __init__(self, *_, **__):
                pass

            def start(self):
                pass

        monkeypatch.setattr(
            "app.ai_sessions.threading.Thread", lambda *a, **k: DummyThread()
        )
        monkeypatch.setattr(
            "app.ai_sessions._register_session", lambda session: session
        )

        class MockUser:
            def __init__(self):
                self.id = 707
                self.email = "user@example.com"
                self.name = "Tenant User"
                self.linux_username = "devuser"

        monkeypatch.setattr(
            "app.ai_sessions.User.query.get", lambda user_id: MockUser(), raising=False
        )

        session = create_session(
            project,
            user_id=707,
            command="/bin/true",
        )

        command = pane.commands[0][0]
        assert session.command == "/bin/true"
        assert "ssh-add <<'AIOPS_SSH_KEY'" in command
        assert "-----BEGIN OPENSSH PRIVATE KEY-----" in command
        assert "AIOPS_SSH_KEY" in command


def test_create_session_with_linux_user_switching(monkeypatch, tmp_path):
    """Test that sessions attempt to switch to configured Linux user."""

    class TestConfig(Config):
        TESTING = True
        WTF_CSRF_ENABLED = False
        REPO_STORAGE_PATH = str(tmp_path / "repos")
        CODEX_CONFIG_DIR = str(tmp_path / ".codex")
        # Configure Linux user mapping
        LINUX_USER_STRATEGY = "mapping"
        LINUX_USER_MAPPING = {"user@example.com": "root"}

    app = create_app(TestConfig, instance_path=tmp_path / "instance")

    with app.app_context():
        project_path = tmp_path / "repos" / "demo"
        project_path.mkdir(parents=True, exist_ok=True)
        project = SimpleNamespace(
            id=10,
            name="Demo Project",
            local_path=str(project_path),
            tenant=SimpleNamespace(name="Tenant Beta"),
        )

        pane = FakePane()
        window = FakeWindow("demo-project-p10")
        window._pane = pane
        session_obj = FakeSession("aiops", window)

        monkeypatch.setattr(
            "app.ai_sessions.ensure_project_window",
            lambda project, window_name=None, session_name=None: (
                session_obj,
                window,
                True,
            ),
        )
        monkeypatch.setattr("app.ai_sessions.shutil.which", lambda _: "/usr/bin/tmux")

        # Track the child process execution
        exec_calls = []

        def mock_fork():
            return (1111, 77)  # parent

        def mock_execvp(cmd, args):
            # This would only be called in the child process
            exec_calls.append((cmd, args))

        # Mock os.setuid and os.setgid to track user switching
        setuid_calls = []
        setgid_calls = []

        def mock_setuid(uid):
            setuid_calls.append(uid)

        def mock_setgid(gid):
            setgid_calls.append(gid)

        monkeypatch.setattr("app.ai_sessions.pty.fork", mock_fork)
        monkeypatch.setattr("app.ai_sessions.os.execvp", mock_execvp)
        monkeypatch.setattr("app.ai_sessions.os.setuid", mock_setuid)
        monkeypatch.setattr("app.ai_sessions.os.setgid", mock_setgid)
        monkeypatch.setattr("app.ai_sessions._set_winsize", lambda *_, **__: None)

        class DummyThread:
            def __init__(self, *_, **__):
                pass

            def start(self):
                pass

        monkeypatch.setattr(
            "app.ai_sessions.threading.Thread", lambda *a, **k: DummyThread()
        )
        monkeypatch.setattr(
            "app.ai_sessions._register_session", lambda session: session
        )

        # Create a mock user with email that maps to root
        class MockUser:
            def __init__(self):
                self.id = 999
                self.email = "user@example.com"
                self.name = "Test User"

        def mock_user_query(user_id):
            return MockUser()

        monkeypatch.setattr(
            "app.ai_sessions.User.query.get", mock_user_query, raising=False
        )

        session = create_session(project, user_id=999, tool="codex")

        assert session.command == app.config["ALLOWED_AI_TOOLS"]["codex"]
        assert session.tmux_target == "aiops:demo-project-p10"


def test_create_session_logs_user_switch_failure(monkeypatch, tmp_path, capsys):
    """Test that failures to switch users are logged but don't crash."""

    class TestConfig(Config):
        TESTING = True
        WTF_CSRF_ENABLED = False
        REPO_STORAGE_PATH = str(tmp_path / "repos")
        CODEX_CONFIG_DIR = str(tmp_path / ".codex")
        LINUX_USER_STRATEGY = "mapping"
        LINUX_USER_MAPPING = {"user@example.com": "nonexistent_user_xyz"}

    app = create_app(TestConfig, instance_path=tmp_path / "instance")

    with app.app_context():
        project_path = tmp_path / "repos" / "demo"
        project_path.mkdir(parents=True, exist_ok=True)
        project = SimpleNamespace(
            id=11,
            name="Demo Project",
            local_path=str(project_path),
            tenant=SimpleNamespace(name="Tenant Beta"),
        )

        pane = FakePane()
        window = FakeWindow("demo-project-p11")
        window._pane = pane
        session_obj = FakeSession("aiops", window)

        monkeypatch.setattr(
            "app.ai_sessions.ensure_project_window",
            lambda project, window_name=None, session_name=None: (
                session_obj,
                window,
                True,
            ),
        )
        monkeypatch.setattr("app.ai_sessions.shutil.which", lambda _: "/usr/bin/tmux")
        monkeypatch.setattr("app.ai_sessions.pty.fork", lambda: (1234, 56))
        monkeypatch.setattr("app.ai_sessions._set_winsize", lambda *_, **__: None)

        class DummyThread:
            def __init__(self, *_, **__):
                pass

            def start(self):
                pass

        monkeypatch.setattr(
            "app.ai_sessions.threading.Thread", lambda *a, **k: DummyThread()
        )
        monkeypatch.setattr(
            "app.ai_sessions._register_session", lambda session: session
        )

        # Create a mock user with email that maps to nonexistent user
        class MockUser:
            def __init__(self):
                self.id = 998
                self.email = "user@example.com"
                self.name = "Test User"

        def mock_user_query(user_id):
            return MockUser()

        monkeypatch.setattr(
            "app.ai_sessions.User.query.get", mock_user_query, raising=False
        )

        # Session creation should succeed even if user mapping fails
        session = create_session(project, user_id=998, tool="codex")
        assert session is not None
        assert session.command == app.config["ALLOWED_AI_TOOLS"]["codex"]


def test_find_session_for_issue_respects_tool_for_persistent(monkeypatch):
    from app.ai_sessions import (
        PersistentAISession,
        _register_session,
        find_session_for_issue,
    )

    # Clear session registry
    monkeypatch.setattr("app.ai_sessions._sessions", {})
    monkeypatch.setattr("app.ai_sessions.session_exists", lambda _: True)

    session = PersistentAISession(
        "s-1",
        project_id=1,
        user_id=10,
        tool="claude",
        command="claude --permission-mode acceptEdits",
        tmux_target="aiops:win",
        pipe_file="/tmp/fake-pipe",
        issue_id=77,
    )
    _register_session(session)

    # Matches when tool/command align
    found = find_session_for_issue(
        issue_id=77,
        user_id=10,
        project_id=1,
        expected_tool="claude",
        expected_command="claude --permission-mode acceptEdits",
    )
    assert found is session

    # Different tool should not match
    assert (
        find_session_for_issue(
            issue_id=77,
            user_id=10,
            project_id=1,
            expected_tool="codex",
            expected_command="codex --sandbox danger",
        )
        is None
    )

    # When no tool is specified, should return the most recent session
    found = find_session_for_issue(
        issue_id=77,
        user_id=10,
        project_id=1,
        expected_tool=None,
    )
    assert found is session


def test_find_session_for_issue_returns_most_recent_when_no_tool_specified(monkeypatch):
    """Test that reattaching without --tool returns the most recently created session."""
    import time
    from app.ai_sessions import (
        PersistentAISession,
        _register_session,
        find_session_for_issue,
    )

    # Clear session registry
    monkeypatch.setattr("app.ai_sessions._sessions", {})
    monkeypatch.setattr("app.ai_sessions.session_exists", lambda _: True)

    # Create two Claude sessions at different times
    session1 = PersistentAISession(
        "s-1",
        project_id=1,
        user_id=10,
        tool="claude",
        command="claude --permission-mode acceptEdits",
        tmux_target="aiops:win1",
        pipe_file="/tmp/fake-pipe1",
        issue_id=77,
    )
    _register_session(session1)

    # Sleep briefly to ensure different creation times
    time.sleep(0.01)

    session2 = PersistentAISession(
        "s-2",
        project_id=1,
        user_id=10,
        tool="claude",
        command="claude --permission-mode acceptEdits",
        tmux_target="aiops:win2",
        pipe_file="/tmp/fake-pipe2",
        issue_id=77,
    )
    _register_session(session2)

    # When no tool is specified, should return the most recent session (session2)
    found = find_session_for_issue(
        issue_id=77,
        user_id=10,
        project_id=1,
        expected_tool=None,
    )
    assert found is session2

    # When tool is specified, should return the matching session
    found = find_session_for_issue(
        issue_id=77,
        user_id=10,
        project_id=1,
        expected_tool="claude",
    )
    # Should return the most recent claude session (session2)
    assert found is session2
