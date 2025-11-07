from __future__ import annotations

# Curated palette for tenant accent colors (hex codes, lowercase for consistency).
TENANT_COLOR_CHOICES: list[tuple[str, str]] = [
    ("#2563eb", "Indigo"),
    ("#7c3aed", "Violet"),
    ("#db2777", "Magenta"),
    ("#ec4899", "Pink"),
    ("#f97316", "Orange"),
    ("#f59e0b", "Amber"),
    ("#10b981", "Emerald"),
    ("#0d9488", "Teal"),
    ("#14b8a6", "Aqua"),
    ("#06b6d4", "Cyan"),
]

DEFAULT_TENANT_COLOR: str = TENANT_COLOR_CHOICES[0][0]


def tenant_color_values() -> list[str]:
    """Return just the color codes for quick membership checks."""
    return [value for value, _ in TENANT_COLOR_CHOICES]


def sanitize_tenant_color(raw: str | None) -> str:
    """Normalize a color input against the supported palette."""
    if not raw:
        return DEFAULT_TENANT_COLOR

    normalized = raw.strip().lower()
    if not normalized:
        return DEFAULT_TENANT_COLOR

    if not normalized.startswith("#"):
        normalized = f"#{normalized.lstrip('#')}"

    return normalized if normalized in tenant_color_values() else DEFAULT_TENANT_COLOR
