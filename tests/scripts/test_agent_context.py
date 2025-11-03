from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_agent_context_module():
    module_path = Path(__file__).parents[2] / "scripts" / "agent_context.py"
    spec = importlib.util.spec_from_file_location("agent_context", module_path)
    module = importlib.util.module_from_spec(spec)
    if spec.loader is None:  # pragma: no cover - defensive guard
        raise RuntimeError("Failed to load agent_context module")
    spec.loader.exec_module(module)
    return module


agent_context = _load_agent_context_module()
build_entry = agent_context.build_entry
write_content = agent_context.write_content


def test_write_creates_override_with_base_content(tmp_path, monkeypatch):
    base = tmp_path / "AGENTS.md"
    base.write_text("Base guidance")
    override_path = tmp_path / "AGENTS.override.md"
    monkeypatch.chdir(tmp_path)

    entry = build_entry("Issue details here", issue="AIOPS-123", title="Check overrides", add_timestamp=False)
    write_content(override_path, entry, mode="write")

    contents = override_path.read_text().strip().split("\n\n---\n\n")
    assert contents[0] == "Base guidance"
    assert "AIOPS-123" in contents[1]
    assert "Issue details here" in contents[1]


def test_append_keeps_single_base_section(tmp_path, monkeypatch):
    base = tmp_path / "AGENTS.md"
    base.write_text("Base instructions")
    override_path = tmp_path / "AGENTS.override.md"
    monkeypatch.chdir(tmp_path)

    first = build_entry("Initial context", issue="ISSUE-1", title=None, add_timestamp=False)
    write_content(override_path, first, mode="write")

    second = build_entry("Follow-up context", issue="ISSUE-2", title=None, add_timestamp=False)
    write_content(override_path, second, mode="append")

    contents = override_path.read_text().strip().split("\n\n---\n\n")
    assert contents[0] == "Base instructions"
    assert "Initial context" in contents[1]
    assert "Follow-up context" in contents[2]
