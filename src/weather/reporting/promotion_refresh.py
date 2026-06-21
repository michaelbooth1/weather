"""Compatibility facade for promotion refresh implementation slices."""

from __future__ import annotations

from weather.reporting.promotion_refresh_readers import *  # noqa: F403
from weather.reporting.promotion_refresh_decisions import *  # noqa: F403
from weather.reporting.promotion_refresh_gap_analysis import *  # noqa: F403
from weather.reporting.promotion_refresh_report import *  # noqa: F403
from weather.reporting.promotion_refresh_orchestration import *  # noqa: F403
from weather.reporting.promotion_refresh_cli import *  # noqa: F403

__all__ = [name for name in globals() if not name.startswith("__")]

if __name__ == "__main__":
    main()
