"""Compatibility facade for fleet observability implementation slices."""

from __future__ import annotations

from weather.reporting.fleet.fleet_observability_inventory import *  # noqa: F403
from weather.reporting.fleet.fleet_observability_loops import *  # noqa: F403
from weather.reporting.fleet.fleet_observability_gates import *  # noqa: F403
from weather.reporting.fleet.fleet_observability_payload import *  # noqa: F403
from weather.reporting.fleet.fleet_observability_render import *  # noqa: F403
from weather.reporting.fleet.fleet_observability_cli import *  # noqa: F403

__all__ = [name for name in globals() if not name.startswith("__")]

if __name__ == "__main__":
    main()
