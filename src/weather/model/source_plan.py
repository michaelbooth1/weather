"""Canonical serving-time source planning.

Market specifications list their durable provider set.  A few free adjuncts
are enabled by policy from that declared set; keeping those rules here makes
live collection, replay research, and source inventories use the same plan.
"""

from __future__ import annotations


OPEN_METEO_ADJUNCTS = (
    "open_meteo_air_quality",
    "open_meteo_global_models",
)
US_GUIDANCE_TRIGGER_SOURCES = (
    "nws_grid",
    "open_meteo_multimodel",
)
US_GUIDANCE_ADJUNCT = "nbm_probabilistic_tmax"


def planned_live_source_names(spec) -> tuple[str, ...]:
    """Return the ordered, de-duplicated live plan for one market spec."""

    names = list(getattr(spec, "sources", ()) or ())
    if "open_meteo" in names:
        for adjunct in OPEN_METEO_ADJUNCTS:
            if adjunct not in names:
                names.append(adjunct)
    history_id = str(getattr(spec, "wu_history_id", "") or "")
    if (
        ":US" in history_id
        and any(source in names for source in US_GUIDANCE_TRIGGER_SOURCES)
        and US_GUIDANCE_ADJUNCT not in names
    ):
        names.append(US_GUIDANCE_ADJUNCT)
    return tuple(dict.fromkeys(str(name) for name in names if str(name)))
