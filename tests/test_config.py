from app.config import _ensure_codex_flags


def test_ensure_codex_flags_appends_missing_flags():
    command = "codex"
    assert (
        _ensure_codex_flags(
            command,
            sandbox_mode="danger-full-access",
            approval_mode="never",
        )
        == "codex --sandbox danger-full-access --ask-for-approval never"
    )


def test_ensure_codex_flags_replaces_existing_values():
    command = "codex --sandbox restricted --ask-for-approval on-failure"
    assert (
        _ensure_codex_flags(
            command,
            sandbox_mode="danger-full-access",
            approval_mode="never",
        )
        == "codex --sandbox danger-full-access --ask-for-approval never"
    )


def test_ensure_codex_flags_handles_equals_syntax():
    command = "codex --sandbox=read-only --ask-for-approval=auto"
    assert (
        _ensure_codex_flags(
            command,
            sandbox_mode="danger-full-access",
            approval_mode="never",
        )
        == "codex --sandbox danger-full-access --ask-for-approval never"
    )
