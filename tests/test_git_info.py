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
