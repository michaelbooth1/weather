"""Verbatim _parse_pair_row from parser integration abd648c7c; no provider imports."""
import re


def _parse_pair_row(line: str) -> list[tuple[float | None, float | None]]:
    groups = str(line[6:] or "").split("|")
    pairs = []
    for group in groups:
        tokens = re.findall(r"-?\d+(?:\.\d+)?", group)
        first = float(tokens[0]) if tokens else None
        second = float(tokens[1]) if len(tokens) > 1 else None
        pairs.append((first, second))
    return pairs
