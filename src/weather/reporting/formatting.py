"""Shared report formatting helpers."""

from __future__ import annotations


def fmt_pct(value):
    if value is None:
        return "-"
    return f"{value * 100:.1f}%"


def fmt_num(value, decimals=4):
    if value is None:
        return "-"
    return f"{float(value):.{decimals}f}"


def fmt_signed(value, decimals=4):
    if value is None:
        return "-"
    return f"{float(value):+.{decimals}f}"


def fmt_group(value):
    if value is None or value == "":
        return "-"
    return str(value)


def fmt_pnl(value):
    return f"{float(value):+.2f}"


def markdown_table(headers, rows):
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(":---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(value) if value not in (None, "") else "-" for value in row) + " |")
    return lines

