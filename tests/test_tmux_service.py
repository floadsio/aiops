
from app.services import tmux_service


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
    monkeypatch.setattr(tmux_service, "_get_server", lambda: _FakeServer(sessions))

    windows = tmux_service.list_windows_for_aliases("demo", include_all_sessions=True)

    assert len(windows) == 2
    assert {window.session_name for window in windows} == {"user-alpha", "user-beta"}

