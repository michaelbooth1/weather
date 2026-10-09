"""Which shadow scoring may read a UTC day: the evidence embargo windows and the parity-day admission.

Domain-neutral (no ``weather`` import), so the diagnostic CLI, the future shadow gate, exporters and transfers
share one copy. Each window has a scope:

- ``full``: nothing about the day is scored, neither the 88a diagnostic nor parity.
- ``outcome``: outcome-bearing scoring (88a, paper fills, cash, markouts, settlement) is refused; the
  outcome-blind decision-parity path is admitted from the parity clock, and its report must carry no outcome field.

A day inside several windows takes the most restrictive scope. Lifting, shortening or re-scoping a window is a
reviewed change here. Contract: docs/operations/maker-shadow-runner.md (Embargo).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import re

from maker_core.shadow.score import tape_code

FULL, OUTCOME = "full", "outcome"
SCOPE_RANK = {OUTCOME: 1, FULL: 2}

# (first UTC day, last UTC day, scope, reason); inclusive. Each window comes from a signed or owner-approved plan.
EMBARGO_WINDOWS = (
    ("2026-09-30", "2026-10-15", FULL,
     "maker replay v2 panel (UTC 09-30..10-14) and settlement-only day 10-15 (DECISION_LOG 2026-10-03)"),
    ("2026-10-15", "2026-11-13", OUTCOME,
     "maker P&L desk-study decision panel: T+1/T+2 quote days for events 10-17..10-30 and its pre-registered "
     "extension to at most 28 event dates (pre-registration 2026-10-01, read only after the 10-31 look)"),
)
EMBARGOED_UTC_DAYS = tuple((start, end, reason) for start, end, _, reason in EMBARGO_WINDOWS)

PARITY_CLOCK_SCHEMA = "maker_core.shadow_parity_clock.v0.1"
PARITY_CLOCK_FIELDS = ("schema_version", "engine_commit", "freeze_utc", "shadow_commit", "restart_run_id",
                       "config_sha256")
COMMIT = re.compile(r"[0-9a-f]{40}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
RUN_ID = re.compile(r"(\d{8}T\d{6}Z)-[0-9a-f]{8}\Z")
# Keys a parity report must not carry on an ``outcome``-scoped day (at any depth).
OUTCOME_FIELDS = frozenset({"fills", "cash", "lots", "markouts", "strata", "net_pusd", "adverse_pusd", "pnl",
                            "settlement", "settlements", "prints", "paper_ledger"})


def utc_day(value):
    """The canonical ``YYYY-MM-DD`` of ``value``; anything that does not round-trip is refused."""
    text = value.isoformat() if isinstance(value, date) and not isinstance(value, datetime) else str(value)
    try:
        canonical = date.fromisoformat(text).isoformat()
    except ValueError:
        raise ValueError("utc_day_not_canonical") from None
    if canonical != text:
        raise ValueError("utc_day_not_canonical")
    return canonical


def _windows_for(day, windows):
    return [w for w in windows if w[0] <= day <= w[1]]


def embargo_reason(day, windows=EMBARGO_WINDOWS):
    """The reason any window embargoes ``day`` from outcome scoring, else None."""
    hits = _windows_for(utc_day(day), windows)
    return hits[0][3] if hits else None


def embargo_scope(day, windows=EMBARGO_WINDOWS):
    """``full``, ``outcome`` or None; the most restrictive scope of the windows containing ``day``."""
    hits = _windows_for(utc_day(day), windows)
    return max((w[2] for w in hits), key=SCOPE_RANK.__getitem__) if hits else None


def run_started(run_id):
    """The UTC start instant encoded in a runner ``run_id`` (``YYYYmmddTHHMMSSZ-<8 hex>``), else None."""
    match = RUN_ID.fullmatch(str(run_id))
    if not match:
        return None
    return datetime.strptime(match.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)


def _utc(text):
    try:
        value = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("parity_clock_time_invalid") from None
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("parity_clock_time_not_utc")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class ParityClock:
    """Explicit parity-clock inputs (gate wording 2d): engine commit E, freeze T_f, shadow commit S, restart run."""

    engine_commit: str
    freeze_utc: datetime
    shadow_commit: str
    restart_run_id: str
    config_sha256: str

    @property
    def restart_utc(self):
        return run_started(self.restart_run_id)

    @property
    def first_countable_day(self):
        """The restart day never counts: the first countable day starts after the restart run opened."""
        return (self.restart_utc.date() + timedelta(days=1)).isoformat()


def parity_clock_from(mapping):
    """Strict loader: exact field set, 40-hex commits, UTC freeze, a runner run id started at or after the freeze."""
    if not isinstance(mapping, dict) or set(mapping) != set(PARITY_CLOCK_FIELDS):
        raise ValueError("parity_clock_fields")
    if mapping["schema_version"] != PARITY_CLOCK_SCHEMA:
        raise ValueError("parity_clock_schema")
    for name in ("engine_commit", "shadow_commit"):
        if not isinstance(mapping[name], str) or not COMMIT.fullmatch(mapping[name]):
            raise ValueError(f"parity_clock_{name}_invalid")
    if not isinstance(mapping["config_sha256"], str) or not SHA256.fullmatch(mapping["config_sha256"]):
        raise ValueError("parity_clock_config_sha256_invalid")
    freeze = _utc(mapping["freeze_utc"])
    restart = run_started(mapping["restart_run_id"])
    if restart is None:
        raise ValueError("parity_clock_restart_run_id_invalid")
    if restart < freeze.replace(microsecond=0):
        raise ValueError("parity_clock_restart_before_freeze")
    return ParityClock(mapping["engine_commit"], freeze, mapping["shadow_commit"], mapping["restart_run_id"],
                       mapping["config_sha256"])


@dataclass(frozen=True)
class ParityAdmission:
    day: str
    refused: str | None
    reason: str | None = None
    withhold_outcomes: bool = False

    @property
    def admitted(self):
        return self.refused is None


def admit_parity_day(day, clock, *, today, windows=EMBARGO_WINDOWS):
    """Decide, before any tape is opened, whether the parity path may read UTC ``day``.

    ``today`` is the current UTC date (injected; the day must be closed). Order: canonical, closed, ``full``
    window, clock present, on or after the clock's first countable day. An ``outcome``-window day is admitted
    with ``withhold_outcomes`` set.
    """
    day = utc_day(day)
    if day >= utc_day(today):
        return ParityAdmission(day, "utc_day_not_closed")
    scope = embargo_scope(day, windows)
    if scope == FULL:
        return ParityAdmission(day, "embargoed_utc_day", embargo_reason(day, windows))
    if clock is None:
        return ParityAdmission(day, "parity_clock_not_started")
    if not isinstance(clock, ParityClock):
        raise TypeError("parity clock must be a ParityClock")
    if day < clock.first_countable_day:
        return ParityAdmission(day, "before_parity_clock")
    return ParityAdmission(day, None, embargo_reason(day, windows), withhold_outcomes=scope == OUTCOME)


def bind_parity_tapes(admission, tapes, unsealed, clock):
    """The code binding of an admitted day's sealed tapes (gate wording 2d ii-iii); None when bound.

    ``tapes``/``unsealed`` must come from ``sealed_tapes(root, admission.day)`` only. Returns a refusal code.
    """
    if not admission.admitted:
        raise ValueError("parity_day_not_admitted")
    if unsealed:
        return "unsealed_tape"
    if not tapes:
        return "no_sealed_tape"
    for tape in tapes:
        code = tape_code(tape)
        if not code["git_commit"] or code["git_dirty"] is not False or code["git_error"] is not None:
            return "code_unbound"
        if code["git_commit"] != clock.shadow_commit:
            return "not_parity_commit"
        scope = tape["rows"][0]["scope"]
        if scope.get("utc_day") != admission.day:
            return "tape_day_mismatch"
        if scope.get("config_sha256") != clock.config_sha256:
            return "not_parity_config"
        started = run_started(scope.get("run_id"))
        if started is None:
            return "run_unbound"
        if started < clock.restart_utc:
            return "run_before_restart"
    return None


def _outcome_keys(value, path=""):
    if isinstance(value, dict):
        for key, item in value.items():
            here = f"{path}.{key}" if path else str(key)
            if key in OUTCOME_FIELDS:
                yield here
            yield from _outcome_keys(item, here)
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            yield from _outcome_keys(item, f"{path}[{index}]")


def assert_outcome_blind(report, admission):
    """Refuse a parity report that carries an outcome field on an ``outcome``-window day."""
    if admission.withhold_outcomes:
        found = list(_outcome_keys(report))
        if found:
            raise ValueError("outcome_field_on_embargoed_day: " + ", ".join(found[:5]))
    return report


__all__ = ["EMBARGOED_UTC_DAYS", "EMBARGO_WINDOWS", "FULL", "OUTCOME", "OUTCOME_FIELDS", "PARITY_CLOCK_FIELDS",
           "PARITY_CLOCK_SCHEMA", "ParityAdmission", "ParityClock", "admit_parity_day", "assert_outcome_blind",
           "bind_parity_tapes", "embargo_reason", "embargo_scope", "parity_clock_from", "run_started", "utc_day"]
