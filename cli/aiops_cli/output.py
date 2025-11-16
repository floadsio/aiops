"""Output formatting utilities."""

import json
from typing import Any, Optional

import yaml
from rich.console import Console
from rich.markup import escape
from rich.table import Table


def format_output(
    data: Any,
    format_type: str = "table",
    console: Optional[Console] = None,
    title: Optional[str] = None,
    columns: Optional[list[str]] = None,
) -> None:
    """Format and display output.

    Args:
        data: Data to format
        format_type: Output format (table, json, yaml)
        console: Rich console instance
        title: Optional title for table output
        columns: Optional list of column names to display (only for table format)
    """
    if console is None:
        console = Console()

    if format_type == "json":
        console.print(json.dumps(data, indent=2))
    elif format_type == "yaml":
        console.print(yaml.dump(data, default_flow_style=False))
    elif format_type == "table":
        _format_table(data, console, title, columns)
    else:
        console.print(data)


def _format_table(
    data: Any,
    console: Console,
    title: Optional[str] = None,
    columns: Optional[list[str]] = None,
) -> None:
    """Format data as a table.

    Args:
        data: Data to format
        console: Rich console instance
        title: Optional table title
        columns: Optional list of column names to display
    """
    if isinstance(data, list):
        if not data:
            console.print("[yellow]No data to display[/yellow]")
            return

        # Use first item to determine columns
        first_item = data[0]
        if isinstance(first_item, dict):
            table = Table(title=title)

            # Determine which columns to display
            if columns:
                # Filter to only requested columns that exist
                display_columns = [c for c in columns if c in first_item]
            else:
                # Use all columns from the data
                display_columns = list(first_item.keys())

            # Add columns to table with proper wrapping configuration
            # ID-like columns (id, external_id, etc.) can be narrow and no-wrap
            # Text columns (title, description, etc.) should wrap
            for col in display_columns:
                col_name = col.replace("_", " ").title()

                # Determine column configuration based on name
                if col in ("id", "external_id", "project_id", "tenant_id", "user_id", "integration_id"):
                    # Numeric IDs - narrow, no wrap
                    table.add_column(col_name, style="cyan", no_wrap=True, width=8)
                elif col in ("status", "provider", "tool", "pinned"):
                    # Status/enum fields - moderate width, no wrap
                    table.add_column(col_name, style="cyan", no_wrap=True, width=12)
                elif col in ("started_at",):
                    # Timestamps - moderate width, no wrap
                    table.add_column(col_name, style="cyan", no_wrap=True, width=20)
                else:
                    # Text fields (title, description, etc.) - wrap to fit terminal
                    table.add_column(col_name, style="cyan", overflow="fold")

            # Add rows
            for idx, item in enumerate(data):
                row = []
                for col in display_columns:
                    value = item.get(col, "")
                    # Format value
                    if value is None:
                        value = ""
                    elif isinstance(value, bool):
                        value = "✓" if value else "✗"
                    elif isinstance(value, (list, dict)):
                        value = json.dumps(value, indent=None)
                    else:
                        value = str(value)
                    # Escape markup to prevent Rich parsing errors
                    value = escape(value)
                    row.append(value)
                # Add separator after each row except the last
                table.add_row(*row, end_section=(idx < len(data) - 1))

            console.print(table)
        else:
            # Simple list
            for item in data:
                console.print(f"• {item}")

    elif isinstance(data, dict):
        table = Table(title=title, show_header=False)
        table.add_column("Key", style="cyan", no_wrap=True, width=25)
        table.add_column("Value", style="green", overflow="fold")

        for key, value in data.items():
            # Format key
            key_display = key.replace("_", " ").title()

            # Format value
            if value is None:
                value_display = ""
            elif isinstance(value, bool):
                value_display = "✓" if value else "✗"
            elif isinstance(value, (list, dict)):
                value_display = json.dumps(value, indent=2)
            else:
                value_display = str(value)

            # Escape markup to prevent Rich parsing errors
            value_display = escape(value_display)

            table.add_row(key_display, value_display)

        console.print(table)
    else:
        console.print(str(data))
