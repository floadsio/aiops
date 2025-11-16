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
) -> None:
    """Format and display output.

    Args:
        data: Data to format
        format_type: Output format (table, json, yaml)
        console: Rich console instance
        title: Optional title for table output
    """
    if console is None:
        console = Console()

    if format_type == "json":
        console.print(json.dumps(data, indent=2))
    elif format_type == "yaml":
        console.print(yaml.dump(data, default_flow_style=False))
    elif format_type == "table":
        _format_table(data, console, title)
    else:
        console.print(data)


def _format_table(data: Any, console: Console, title: Optional[str] = None) -> None:
    """Format data as a table.

    Args:
        data: Data to format
        console: Rich console instance
        title: Optional table title
    """
    if isinstance(data, list):
        if not data:
            console.print("[yellow]No data to display[/yellow]")
            return

        # Use first item to determine columns
        first_item = data[0]
        if isinstance(first_item, dict):
            table = Table(title=title)

            # Add columns from keys
            columns = list(first_item.keys())
            for col in columns:
                table.add_column(col.replace("_", " ").title(), style="cyan")

            # Add rows
            for item in data:
                row = []
                for col in columns:
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
                table.add_row(*row)

            console.print(table)
        else:
            # Simple list
            for item in data:
                console.print(f"• {item}")

    elif isinstance(data, dict):
        table = Table(title=title, show_header=False)
        table.add_column("Key", style="cyan")
        table.add_column("Value", style="green")

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
