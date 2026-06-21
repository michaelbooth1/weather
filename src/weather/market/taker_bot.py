"""Compatibility facade for the taker bot implementation slices."""

from __future__ import annotations

from weather.market.taker_bot_strategy_registry import *  # noqa: F403
from weather.market.taker_bot_tape_io import *  # noqa: F403
from weather.market.taker_bot_strategy_evaluation import *  # noqa: F403
from weather.market.taker_bot_sizing import *  # noqa: F403
from weather.market.taker_bot_scoring import *  # noqa: F403
from weather.market.taker_bot_reporting import *  # noqa: F403
from weather.market.taker_bot_bakeoff import *  # noqa: F403
from weather.market.taker_bot_finalization import *  # noqa: F403
from weather.market.taker_bot_cli import *  # noqa: F403

__all__ = [name for name in globals() if not name.startswith("__")]

if __name__ == "__main__":
    main()
