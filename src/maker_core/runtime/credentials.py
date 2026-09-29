"""Explicit LAN reader token file only. No environment, venue keys or vault IO."""
import re

from maker_core.runtime.portfolio_io import read_json


def reader_credentials(path):
    value = read_json(path)
    if (not isinstance(value, dict) or set(value) != {"url", "token"}
            or not isinstance(value["url"], str)
            or not isinstance(value["token"], str) or not re.fullmatch(r"[0-9a-fA-F]{64}", value["token"])):
        raise ValueError("reader_config_refused")
    return value
