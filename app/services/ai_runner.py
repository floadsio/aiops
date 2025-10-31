from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

from flask import current_app

from ..models import Project


def run_ai_tool(project: Project, tool: str, prompt: str) -> str:
    tool_commands = current_app.config.get("ALLOWED_AI_TOOLS", {})
    if tool not in tool_commands:
        raise ValueError(f"Unsupported AI tool: {tool}")

    command = tool_commands[tool]
    repo_path = Path(project.local_path)
    repo_path.mkdir(parents=True, exist_ok=True)

    if tool == "aider":
        args = f"{command} --message {shlex.quote(prompt)}"
    elif tool == "codex":
        args = f"{command} apply {shlex.quote(prompt)}"
    else:
        args = f"{command} {shlex.quote(prompt)}"

    completed = subprocess.run(
        args,
        cwd=repo_path,
        shell=True,
        check=False,
        capture_output=True,
        text=True,
    )

    stdout = completed.stdout or ""
    stderr = completed.stderr or ""

    if completed.returncode != 0:
        raise RuntimeError(f"AI tool failed ({completed.returncode}): {stderr.strip()}")

    return stdout.strip() or "AI tool completed without output."
