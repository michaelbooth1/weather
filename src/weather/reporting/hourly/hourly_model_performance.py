"""Compatibility facade for hourly model performance implementation slices."""

from __future__ import annotations

from weather.reporting.hourly.hourly_model_scoring import *  # noqa: F403
from weather.reporting.hourly.hourly_model_slots import *  # noqa: F403
from weather.reporting.hourly.hourly_model_gate import *  # noqa: F403
from weather.reporting.hourly.hourly_model_context import *  # noqa: F403
from weather.reporting.hourly.hourly_model_render import *  # noqa: F403
from weather.reporting.hourly.hourly_model_cli import *  # noqa: F403

__all__ = [name for name in globals() if not name.startswith("__")]

if __name__ == "__main__":
    main()
