"""Compatibility facade for pooled feature model implementation slices."""

from __future__ import annotations

from weather.calibration.pooled_feature_assembly import *  # noqa: F403
from weather.calibration.pooled_density_training import *  # noqa: F403
from weather.calibration.pooled_band_training import *  # noqa: F403
from weather.calibration.pooled_training import *  # noqa: F403
from weather.calibration.pooled_artifact_io import *  # noqa: F403
from weather.calibration.pooled_reporting import *  # noqa: F403
from weather.calibration.pooled_feature_cli import *  # noqa: F403

__all__ = [name for name in globals() if not name.startswith("__")]

if __name__ == "__main__":
    main()
