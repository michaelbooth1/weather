"""One CI-only wall-clock allowance scale for deadline-bound test harnesses.

Hosted GitHub Windows runners start Windows PowerShell 5.1 and git child
processes much more slowly than the workstation or the capture host. Measured
on the reconciler execution tests (item K, 2026-10-04): hosted per-test wall
time divided by the workstation's was median 1.45, p90 1.9, max 4.0, across 147
passing cases. The harness's shortened wall-clock RPC allowances (3 s and 10 s)
then expired before a healthy helper finished, about once in seven reconciler
jobs. CI_DEADLINE_SCALE covers the p90 with margin.

Rules (owner decision 2026-10-04):
* The scale applies only when GITHUB_ACTIONS == "true". Everywhere else every
  helper returns its input unchanged, so local, workstation and capture-host
  deadlines are byte-for-byte what they were.
* It scales only time ALLOWANCES (budgets and outer timeouts). It never changes
  hang durations, ordering, kill or containment assertions, and a cap keeps a
  scaled allowance at or below the production value it stands in for.
"""

from __future__ import annotations

import math
import os
from collections.abc import Mapping

CI_DEADLINE_SCALE = 2.5


def ci_deadline_scale(environ: Mapping[str, str] | None = None) -> float:
    env = os.environ if environ is None else environ
    return CI_DEADLINE_SCALE if env.get("GITHUB_ACTIONS") == "true" else 1.0


def ci_scaled_seconds(
    seconds: int,
    *,
    cap: int | None = None,
    environ: Mapping[str, str] | None = None,
) -> int:
    """Whole-second allowance, rounded up and capped; unchanged outside CI."""
    scale = ci_deadline_scale(environ)
    if scale == 1.0:
        return seconds
    scaled = math.ceil(seconds * scale)
    return scaled if cap is None else min(scaled, cap)


def ci_scaled_timeout(seconds: float, environ: Mapping[str, str] | None = None) -> float:
    """Outer subprocess timeout; unchanged outside CI."""
    scale = ci_deadline_scale(environ)
    return seconds if scale == 1.0 else seconds * scale
