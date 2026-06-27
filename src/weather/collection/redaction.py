"""Redaction helpers for collection/status artifacts."""

from __future__ import annotations

import re


_SENSITIVE_QUERY_PATTERN = re.compile(
    r"(?i)([?&](?:api[_-]?key|apikey|key|token|access[_-]?token|password|secret|signature)=)([^&\s)]*)"
)


def redact_sensitive_url_parts(value):
    """Redact secret-like query parameter values from status text."""
    if value is None:
        return None
    return _SENSITIVE_QUERY_PATTERN.sub(lambda match: f"{match.group(1)}<redacted>", str(value))


def has_unredacted_sensitive_url_parts(value):
    """Return true when status text still contains an unredacted secret-like query value."""
    if value is None:
        return False
    for match in _SENSITIVE_QUERY_PATTERN.finditer(str(value)):
        if match.group(2) != "<redacted>":
            return True
    return False
