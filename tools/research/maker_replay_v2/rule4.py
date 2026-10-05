"""Rule-4 design OPTION (not registered): wake ``informed-v0`` on a decision-relevant outcome-view state.

Fictional fixtures only. Registration draft §5 rule 4 wakes a band on "an outcome-view record with a
changed payload". The real exporter re-stamps every view at every evaluation (``as_of_utc`` = evaluation
time; on the NBP path ``stdev`` = sqrt(p(1-p)) * (age since issue in days + .25) moves with it), so every
book record, re-projections included, carries a changed view and rule 1's change-only saving is lost for
``informed-v0``. This module measures alternative view states without touching the engine source: it
swaps ``record_signature`` (the only wake input that reads the view) in the engine and the reference.

View states (``VIEW_RULES``):

- ``now``: the payload hash (as registered; every re-stamp wakes).
- ``A``: every ``OutcomeView`` field except ``as_of_utc``; an ``Unavailable`` reduces to (reason, kind).
- ``B``: ``A`` without ``stdev`` (the view's information content: condition, ``p_yes``, joint, expiry,
  grade, model and ``inputs_hash``; ``stdev`` is a function of those inputs and of time).
- ``T``: ``A`` with ``stdev`` on a declared 0.001 tick.
- ``mutant``: ``B`` without ``p_yes``; it must be caught by the equivalence check.

Fixture transforms: ``restamp`` re-emits the condition's latest view after each of its book records with
``as_of_utc`` = the record's capture time (an as_of-only change); ``drift`` also moves ``stdev`` as the NBP
path does (x(1 + 4 * age in days)); ``pjump`` is ``restamp`` where every 7th re-stamp of a condition
moves ``p_yes`` by 0.01 and keeps every other field (a meaningful change with the same ``inputs_hash``).
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import hashlib

from maker_core.contracts import OutcomeView, Unavailable
from maker_core.evidence.journal import canonical_bytes
from maker_core.replay.v2 import engine as engine_module
from maker_core.replay.v2 import kernel as kernel_module
from maker_core.replay.v2 import reference as reference_module

_ORIGINAL = kernel_module.record_signature


def _view_fields(view, drop):
    if view is None:
        return None
    if isinstance(view, Unavailable):
        return ("unavailable", view.reason, view.kind)
    if isinstance(view, OutcomeView):
        joint = None if view.joint is None else tuple(sorted(view.joint.items()))
        fields = dict(condition_id=view.condition_id, p_yes=view.p_yes, stdev=view.stdev, joint=joint,
                      valid_until_utc=view.valid_until_utc, inputs_hash=view.inputs_hash, model_id=view.model_id,
                      calibration_grade=view.calibration_grade)
        if "stdev_tick" in drop:
            fields["stdev"] = round(view.stdev / .001)
        for key in drop:
            fields.pop(key, None)
        return ("view", tuple(sorted(fields.items())))
    return ("other", repr(view))


VIEW_RULES = {
    "now": None,
    "A": (),
    "B": ("stdev",),
    "T": ("stdev_tick",),
    "mutant": ("stdev", "p_yes"),
}


def _signature(drop):
    def record_signature(state, informed):
        terms = state.latest.get("terms")
        body = (terms.min_size, terms.max_spread_cents, terms.rate_per_day) if terms is not None else None
        view = _view_fields(state.latest.get("outcome_view"), drop) if informed else None
        return (kernel_module.book_state(state.latest.get("book")), body, view,
                state.sha.get("info_event") if informed else None, state.last_fill)
    return record_signature


@contextmanager
def view_rule(name):
    """Swap rule 4's view state in the v2 engine and the reference schedule for the duration."""
    drop = VIEW_RULES[name]
    signature = _ORIGINAL if drop is None else _signature(drop)
    modules = (kernel_module, engine_module, reference_module)
    for module in modules:
        module.record_signature = signature
    try:
        yield
    finally:
        for module in modules:
            module.record_signature = _ORIGINAL


# -- fixture transforms -----------------------------------------------------------------------------------
def _ts(value):
    return datetime.fromisoformat(value)


def _row(template, captured_at, payload):
    return dict(template, captured_at=captured_at, kind="outcome_view", payload=payload,
                payload_sha256=hashlib.sha256(canonical_bytes(payload)).hexdigest())


def restamped(rows, mode="restamp"):
    """Exporter-ordered v0.1 rows with each condition's latest available view re-stamped after its books."""
    if mode not in ("restamp", "drift", "pjump"):
        raise ValueError("unknown mode")
    latest, issued, count = {}, {}, {}
    out = []
    for row in rows:
        out.append(row)
        cid = row["condition_id"]
        if row["kind"] == "outcome_view":
            value = row["payload"].get("value")
            if row["payload"].get("available") and isinstance(value, dict):
                latest[cid] = dict(value)
                issued[cid] = _ts(value["as_of_utc"])
            else:
                latest.pop(cid, None)
            continue
        if row["kind"] != "book" or cid not in latest:
            continue
        value, at = dict(latest[cid]), _ts(row["captured_at"])
        if not issued[cid] < at < _ts(value["valid_until_utc"]):
            continue
        value["as_of_utc"] = at.isoformat()
        if mode == "drift":
            age_days = (at - issued[cid]).total_seconds() / 86400
            value["stdev"] = round(float(latest[cid]["stdev"]) * (1 + 4 * age_days), 9)
        elif mode == "pjump":
            count[cid] = count.get(cid, 0) + 1
            if count[cid] % 7 == 0:
                p = float(latest[cid]["p_yes"])
                p = round(p + (.01 if p < .5 else -.01), 6)
                latest[cid]["p_yes"] = p
                value["p_yes"] = p
        out.append(_row(row, row["captured_at"], dict(available=True, value=value)))
    for number, row in enumerate(out):
        row["sequence"] = number
    return out
