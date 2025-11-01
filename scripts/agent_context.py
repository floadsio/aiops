#!/usr/bin/env python3
"""Helper to manage local instructions for coding agents.

The script writes to a git-ignored Markdown file (AGENTS.local.md by default)
so you can stash issue-specific guidance that agents should read at the start
of a session without committing the content to the repository.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Optional


DEFAULT_FILENAME = "AGENTS.local.md"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Manage the local AGENTS.md companion file that stores "
            "issue-specific instructions for coding agents."
        )
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=Path(DEFAULT_FILENAME),
        help=f"Where to write the context file (default: {DEFAULT_FILENAME}).",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    write_parser = subparsers.add_parser(
        "write", help="Replace the context file with new content read from stdin or a file."
    )
    add_content_arguments(write_parser)

    append_parser = subparsers.add_parser(
        "append", help="Append new content to the context file."
    )
    add_content_arguments(append_parser)

    subparsers.add_parser("clear", help="Delete the context file.")
    subparsers.add_parser("show", help="Print the current context file to stdout.")

    return parser.parse_args()


def add_content_arguments(subparser: argparse.ArgumentParser) -> None:
    subparser.add_argument(
        "--source",
        type=Path,
        help="Read content from an existing file instead of stdin.",
    )
    subparser.add_argument(
        "--issue",
        help="Optional issue identifier to include as a heading, e.g. AIOPS-123.",
    )
    subparser.add_argument(
        "--title",
        help="Optional short summary that appears next to the issue identifier.",
    )
    subparser.add_argument(
        "--no-timestamp",
        action="store_true",
        help="Skip adding the Updated timestamp line to the entry.",
    )


def main() -> None:
    args = parse_args()

    if args.command in {"write", "append"}:
        content = load_content(args)
        entry = build_entry(content, issue=args.issue, title=args.title, add_timestamp=not args.no_timestamp)
        write_content(args.path, entry, mode=args.command)
        return

    if args.command == "clear":
        clear_file(args.path)
        return

    if args.command == "show":
        show_file(args.path)
        return

    raise SystemExit(f"Unsupported command: {args.command}")


def load_content(args: argparse.Namespace) -> str:
    if args.source:
        if not args.source.exists():
            raise SystemExit(f"Source file not found: {args.source}")
        return args.source.read_text()

    if sys.stdin.isatty():
        print("Reading context from stdin. Press Ctrl-D (Unix) or Ctrl-Z (Windows) to finish.", file=sys.stderr)

    data = sys.stdin.read()
    if not data.strip():
        raise SystemExit("No content provided.")
    return data


def build_entry(content: str, issue: Optional[str], title: Optional[str], add_timestamp: bool) -> str:
    blocks = []
    heading_parts = []
    if issue:
        heading_parts.append(issue.strip())
    if title:
        heading_parts.append(title.strip())
    if heading_parts:
        blocks.append(f"# {' — '.join(heading_parts)}")

    if add_timestamp:
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
        blocks.append(f"_Updated: {timestamp}_")

    blocks.append(content.rstrip())
    return "\n\n".join(blocks).strip() + "\n"


def write_content(path: Path, entry: str, mode: str) -> None:
    if path.is_dir():
        raise SystemExit(f"Target path is a directory: {path}")

    if mode == "append" and path.exists():
        existing = path.read_text().rstrip()
        if existing:
            entry = f"{existing}\n\n---\n\n{entry}"
    path.write_text(entry)
    print(f"Wrote context to {path}")


def clear_file(path: Path) -> None:
    if path.exists():
        path.unlink()
        print(f"Removed {path}")
    else:
        print(f"No context file to remove at {path}")


def show_file(path: Path) -> None:
    if not path.exists():
        raise SystemExit(f"No context file found at {path}")
    sys.stdout.write(path.read_text())


if __name__ == "__main__":
    main()
