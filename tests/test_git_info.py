from types import SimpleNamespace

from git.exc import InvalidGitRepositoryError

from app import git_info


def test_detect_repo_branch_returns_active_branch(monkeypatch, tmp_path):
    class DummyRepo:
        head = SimpleNamespace(is_detached=False)
        active_branch = SimpleNamespace(name="feature/x")

    monkeypatch.setattr(git_info, "Repo", lambda *args, **kwargs: DummyRepo())

    branch = git_info.detect_repo_branch(tmp_path)
    assert branch == "feature/x"


def test_detect_repo_branch_handles_detached_head(monkeypatch, tmp_path):
    class DummyRepo:
        head = SimpleNamespace(is_detached=True, commit=SimpleNamespace(hexsha="abcdef123456"))
        active_branch = None

    monkeypatch.setattr(git_info, "Repo", lambda *args, **kwargs: DummyRepo())

    branch = git_info.detect_repo_branch(tmp_path)
    assert branch == "abcdef1"


def test_detect_repo_branch_handles_invalid_repo(monkeypatch, tmp_path):
    def _raise(*args, **kwargs):
        raise InvalidGitRepositoryError("no repo")

    monkeypatch.setattr(git_info, "Repo", _raise)

    assert git_info.detect_repo_branch(tmp_path) is None


def test_list_repo_branches_includes_current_and_remote(monkeypatch, tmp_path):
    class DummyRef:
        def __init__(self, remote_head):
            self.remote_head = remote_head

    class DummyRemote:
        def __init__(self, refs):
            self.refs = refs

    class DummyHead:
        def __init__(self, name):
            self.name = name

    class DummyRepo:
        head = SimpleNamespace(is_detached=False)
        active_branch = SimpleNamespace(name="git-identities")
        heads = [DummyHead("git-identities"), DummyHead("main")]
        remotes = [DummyRemote([DummyRef("release-2024-08"), DummyRef("main")])]

    monkeypatch.setattr(git_info, "Repo", lambda *args, **kwargs: DummyRepo())

    branches = git_info.list_repo_branches(tmp_path)
    assert branches[0] == "git-identities"
    assert "main" in branches
    assert "release-2024-08" in branches


def test_list_repo_branches_handles_invalid_repo(monkeypatch, tmp_path):
    def _raise(*args, **kwargs):
        raise InvalidGitRepositoryError("no repo")

    monkeypatch.setattr(git_info, "Repo", _raise)
    assert git_info.list_repo_branches(tmp_path) == []
