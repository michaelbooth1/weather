"""Compatibility facade for promotion refresh implementation slices."""

from __future__ import annotations

from weather.reporting.promotion.readers import *  # noqa: F403
from weather.reporting.promotion.decisions import *  # noqa: F403
from weather.reporting.promotion.gap_analysis import *  # noqa: F403
from weather.reporting.promotion.report import *  # noqa: F403
from weather.reporting.promotion.orchestration import *  # noqa: F403
from weather.reporting.promotion.cli import *  # noqa: F403

__all__ = [name for name in globals() if not name.startswith("__")]

if __name__ == "__main__":
    main()
