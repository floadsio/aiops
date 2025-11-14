from app.services import tmux_service


def test_session_name_prefers_linux_username():
    class DummyUser:
        def __init__(self):
            self.linux_username = "ivo"
            self.name = "Ivo Marino"

    assert tmux_service.session_name_for_user(DummyUser()) == "ivo"


def test_session_name_uses_first_token_of_full_name():
    class DummyUser:
        def __init__(self):
            self.linux_username = None
            self.name = "Ivo Marino"

    assert tmux_service.session_name_for_user(DummyUser()) == "ivo"


class _FakeWindow:
    def __init__(self, name: str):
        self._name = name
        self.panes = [object()]

    def get(self, key, default=None):
        if key == "window_name":
            return self._name
        if key == "window_created":
            return None
        return default


class _FakeSession:
    def __init__(self, name: str, windows: list[_FakeWindow]):
        self._name = name
        self.windows = windows

    def get(self, key, default=None):
        if key == "session_name":
            return self._name
        return default


class _FakeServer:
    def __init__(self, sessions):
        self.sessions = sessions


def test_list_windows_include_all_sessions(monkeypatch):
    sessions = [
        _FakeSession("user-alpha", [_FakeWindow("demo-alpha-p1")]),
        _FakeSession("user-beta", [_FakeWindow("demo-beta-p2")]),
    ]
    monkeypatch.setattr(tmux_service, "_get_server", lambda linux_username=None: _FakeServer(sessions))

    windows = tmux_service.list_windows_for_aliases("demo", include_all_sessions=True)

    assert len(windows) == 2
    assert {window.session_name for window in windows} == {"user-alpha", "user-beta"}
