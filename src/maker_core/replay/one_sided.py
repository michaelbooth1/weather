"""Replay adapter for one-sided-edge-v0; the shared lifecycle bytes stay unchanged.

The candidate runs the informed lifecycle (full events and fair value) with
three overrides: decidedness is a quoting signal instead of a permanent pull,
a band holds to settlement after its first fill, and the band shape needed to
read decidedness comes from captured plugin_input band rows at capture time.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields, replace

from maker_core.quoting.one_sided import (
    BAND_KINDS, NAME, EdgeProfile, decide_one_sided, edge_inputs, one_sided_edge_v0,
)
from maker_core.replay.bundle import BundleError, timestamp
from maker_core.replay.engine import ReplayConfig, ReplayEngine


@dataclass(frozen=True)
class EdgeReplayConfig(ReplayConfig):
    """Binds the edge profile (z, a, K, cells) into any registration's replay_config."""
    policy: str = NAME
    profile: EdgeProfile = one_sided_edge_v0

    def __post_init__(self):
        if self.policy != NAME or not isinstance(self.profile, EdgeProfile):
            raise BundleError("unsupported_replay_policy")
        base = self.base()  # Shared validation and Decimal normalization.
        for f in fields(ReplayConfig):
            if f.name != "policy":
                object.__setattr__(self, f.name, getattr(base, f.name))

    def base(self) -> ReplayConfig:
        return ReplayConfig(**{**{f.name: getattr(self, f.name) for f in fields(ReplayConfig)},
                               "policy": "informed-v0"})


class EdgeReplayEngine(ReplayEngine):
    def __init__(self, bundles, config: EdgeReplayConfig, *, check=lambda: None):
        if not isinstance(config, EdgeReplayConfig):
            raise BundleError("unsupported_replay_policy")
        super().__init__(bundles, config.base(), check=check)
        self.edge_config, self.profile = config, config.profile
        self.band_kinds, self.full_events = {}, {}

    def ingest(self, row, at):
        if row.kind == "plugin_input":
            self.band_row(row)
        super().ingest(row, at)
        self.states[row.condition_id].decided = False  # Never a permanent pull for this profile.

    def band_row(self, row):
        payload = row.payload
        record = payload.get("record") if isinstance(payload, Mapping) and payload.get("source") == "snapshots" else None
        if not isinstance(record, Mapping) or str(record.get("condition_id", "")).lower() != row.condition_id:
            return
        try:
            captured = timestamp(record["captured_at_utc"])
        except (BundleError, KeyError, TypeError, ValueError):
            return  # An unreadable band row leaves the shape unknown, never guessed.
        self.band_kinds.setdefault(row.condition_id, {}).setdefault(captured, set()).add(record.get("bin_kind"))

    def band_kind(self, cid):
        """Latest captured shape; unknown or conflicting shapes give decidedness no direction."""
        shapes = self.band_kinds.get(cid)
        if not shapes:
            return None
        kinds = shapes[max(shapes)]
        return next(iter(kinds)) if len(kinds) == 1 and kinds <= set(BAND_KINDS) else None

    def tick(self, cid, at):
        state = self.states[cid]
        events = state.latest.get("info_event")
        if events is None:
            return super().tick(cid, at)
        # The lifecycle pulls DECIDED bands forever; hide only those events from
        # it and hand the complete set to the kernel through decide_inputs.
        self.full_events[cid] = events
        state.latest["info_event"] = tuple(e for e in events if (e.decided or {}).get(cid, 0) < .5)
        try:
            super().tick(cid, at)
        finally:
            state.latest["info_event"] = events

    def decide_inputs(self, value):
        cid, event_id = value.market.condition_id, value.market.event_id
        state = self.states[cid]
        elsewhere = any(
            k != cid and "descriptor" in s.latest and s.latest["descriptor"].market.event_id == event_id
            and any(x.outcome == "YES" for x in (*s.legs, *s.lots)) for k, s in self.states.items())
        return decide_one_sided(edge_inputs(
            value, self.profile, events=self.full_events.get(cid, value.events), fill_seen=bool(state.lots),
            band_kind=self.band_kind(cid), event_yes_elsewhere=elsewhere))

    def run(self):
        return replace(super().run(), config=self.edge_config)


def edge_replay(bundles, config=EdgeReplayConfig(), *, check=lambda: None):
    return EdgeReplayEngine(tuple(bundles), config, check=check).run()
