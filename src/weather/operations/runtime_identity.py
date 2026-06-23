"""Compatibility facade for weather.runtime_identity."""

from weather.runtime_identity import *  # noqa: F403

__all__ = [name for name in globals() if not name.startswith("__")]
