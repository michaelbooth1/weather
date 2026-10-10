"""Which shadow scoring may read a UTC day: the evidence embargo windows and the parity-day admission.

Domain-neutral (no ``weather`` import), so the diagnostic CLI, the future shadow gate, exporters and transfers
share one copy. Each window has a scope:

- ``full``: nothing about the day is scored, neither the 88a diagnostic nor parity.
- ``outcome``: outcome-bearing scoring (88a, paper fills, cash, markouts, settlement) is refused; the
  outcome-blind decision-parity path is admitted from the parity clock, and its report must carry no outcome field.

A day inside several windows takes the most restrictive scope. Windows are permanent day ranges: a day stays
embargoed until a reviewed edit here lifts, shortens or re-scopes its window. The parity path ingests the tape's
outcome-bearing rows (paper fills, cash, portfolio) in memory, because decisions are conditioned on them; on an
``outcome`` day it withholds them from its output, enforced by the parity-report allowlist. Contract: docs/operations/maker-shadow-runner.md (Embargo).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import re

from maker_core.shadow.score import tape_code
from maker_core.shadow.tape import sealed_tapes

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

# Parity-report allowlist for ``outcome``-scoped days (gate parity wording §3 counters). Each entry is a value
# spec: a closed enum (frozenset), a compiled pattern, a counter tag, a nested mapping or ``[list item spec]``.
# Anything not listed (key, type, container or value) is refused. No free-text field exists.
_COUNT, _TICKS, _FLAG, _DAY = "count", "ticks", "flag", "day"
MAX_COUNT = 10 ** 7  # far above any day's condition-minute count; a larger number is a channel, not a count
PARITY_REPORT_SCHEMA = "maker_core.shadow_parity.v0"
PARITY_LABEL = "PARITY_OUTCOME_BLIND"
PARITY_VERDICTS = frozenset({"PASS", "FAIL", "NOT_RUN", "REFUSED"})
PARITY_REFUSALS = frozenset({
    "utc_day_not_closed", "embargoed_utc_day", "parity_clock_not_started", "before_parity_clock",
    "unsealed_tape", "no_sealed_tape", "code_unbound", "not_parity_commit", "tape_day_mismatch",
    "not_parity_config", "run_unbound", "run_before_restart", "profile_mismatch"})
# ``tape_code`` codes (``not_recorded``) and the runner's ``code_identity`` codes.
TAPE_GIT_ERRORS = frozenset({"not_recorded", "git_unavailable", "git_failed", "git_output_invalid",
                             "git_status_failed", "git_timeout"})
TAPE_NAME = re.compile(r"\d{4}-\d{2}-\d{2}-\d{8}T\d{6}Z-[0-9a-f]{8}\.tape\.jsonl\Z")
PARITY_COUNTERS = ("paired", "unevaluated", "shadow_only", "replay_only", "decision_mismatch", "price_mismatch",
                   "parity", "exact_equal")
PARITY_FIELD_DISAGREEMENTS = ("action", "reasons", "sizes", "leg_order", "centre", "share_many", "net_per_minute")
PARITY_REPORT_ALLOWLIST = {
    "schema_version": frozenset({PARITY_REPORT_SCHEMA}), "label": frozenset({PARITY_LABEL}), "utc_day": _DAY,
    "verdict": PARITY_VERDICTS, "refused": PARITY_REFUSALS,
    "engine_commit": COMMIT, "shadow_commit": COMMIT, "config_sha256": SHA256, "cohort_id": SHA256,
    "parity": {**{name: _COUNT for name in PARITY_COUNTERS}, "max_price_diff_ticks": _TICKS,
               "field_disagreements": {name: _COUNT for name in PARITY_FIELD_DISAGREEMENTS}},
    "tapes": [{"tape": TAPE_NAME, "sha256": SHA256, "git_commit": COMMIT, "git_dirty": _FLAG,
               "git_error": TAPE_GIT_ERRORS}],
    "code": {"git_commits": [COMMIT], "tapes": _COUNT, "dirty_tapes": _COUNT, "unbound_tapes": _COUNT},
}


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
    try:
        return datetime.strptime(match.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:  # an impossible calendar instant, e.g. month 13
        return None


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
    # A run id has whole seconds; it must not be earlier than the freeze instant itself (no sub-second grace).
    if restart < freeze:
        raise ValueError("parity_clock_restart_before_freeze")
    return ParityClock(mapping["engine_commit"], freeze, mapping["shadow_commit"], mapping["restart_run_id"],
                       mapping["config_sha256"])


_MINT = object()  # only ``admit_parity_day`` holds it


def _windows_with_defaults(windows):
    """The permanent windows, then the caller's: a test or caller may add windows, never remove one.

    Always prepended, with no membership test (a caller's entry could override ``__eq__``); a duplicate is harmless.
    """
    return tuple(EMBARGO_WINDOWS) + tuple(windows)


def _scope(day, windows):
    """The most restrictive scope of ``day`` over the caller's windows and, independently, ``EMBARGO_WINDOWS``."""
    scopes = [s for s in (embargo_scope(day, EMBARGO_WINDOWS), embargo_scope(day, _windows_with_defaults(windows)))
              if s is not None]
    return max(scopes, key=SCOPE_RANK.__getitem__) if scopes else None


@dataclass(frozen=True)
class ParityAdmission:
    """Minted only by ``admit_parity_day``; direct construction (or ``dataclasses.replace``) is refused.

    An admitted token is re-validated on construction: canonical day, no ``full`` window, a ``ParityClock`` whose
    first countable day is not after the day, and ``withhold_outcomes`` equal to the day's ``outcome`` scope.
    """

    day: str
    refused: str | None
    reason: str | None = None
    withhold_outcomes: bool = False
    clock: ParityClock | None = field(default=None, compare=False)
    windows: tuple = field(default=EMBARGO_WINDOWS, compare=False, repr=False)
    mint: object = field(default=None, compare=False, repr=False)

    def __post_init__(self):
        if self.mint is not _MINT:
            raise TypeError("parity_admission_not_minted: use admit_parity_day")
        if self.refused is None:
            _admitted_scope(self)

    @property
    def admitted(self):
        return self.refused is None


def _admitted_scope(admission):
    """Re-derive an admitted token from its day; the scope, or ``ValueError`` with the refusal code."""
    day = utc_day(admission.day)
    scope = _scope(day, admission.windows)
    if scope == FULL:
        raise ValueError("embargoed_utc_day")
    if not isinstance(admission.clock, ParityClock):
        raise ValueError("parity_clock_not_started")
    if day < admission.clock.first_countable_day:
        raise ValueError("before_parity_clock")
    if admission.withhold_outcomes is not (scope == OUTCOME):
        raise ValueError("parity_withholding_differs_from_scope")
    return scope


def _utc_now():
    return datetime.now(timezone.utc)


def admit_parity_day(day, clock, *, now=_utc_now, windows=EMBARGO_WINDOWS):
    """Decide, before any tape is opened, whether the parity path may read UTC ``day``.

    Today is computed here in UTC from ``now`` (a zero-argument callable returning an aware datetime; injectable
    only for tests). Order: canonical, closed, ``full`` window, clock present, on or after the clock's first
    countable day. An ``outcome``-window day is admitted with ``withhold_outcomes`` set. The admission carries
    its clock; ``bind_parity_tapes`` refuses any other.
    """
    day = utc_day(day)
    windows = _windows_with_defaults(windows)
    current = now()
    if not isinstance(current, datetime) or current.tzinfo is None:
        raise ValueError("parity_now_not_aware")

    def minted(refused, reason=None, **kw):
        return ParityAdmission(day, refused, reason, windows=windows, mint=_MINT, **kw)

    if day >= current.astimezone(timezone.utc).date().isoformat():
        return minted("utc_day_not_closed")
    scope = _scope(day, windows)
    if scope == FULL:
        return minted("embargoed_utc_day", embargo_reason(day, windows))
    if clock is None:
        return minted("parity_clock_not_started")
    if not isinstance(clock, ParityClock):
        raise TypeError("parity clock must be a ParityClock")
    if day < clock.first_countable_day:
        return minted("before_parity_clock", clock=clock)
    return minted(None, embargo_reason(day, windows), withhold_outcomes=scope == OUTCOME, clock=clock)


def bind_parity_tapes(admission, tapes, unsealed, clock):
    """The code binding of an admitted day's sealed tapes (gate wording 2d ii-iii); None when bound.

    ``tapes``/``unsealed`` must come from ``sealed_tapes(root, admission.day)`` only. Returns a refusal code.
    """
    if not isinstance(admission, ParityAdmission) or not admission.admitted:
        raise ValueError("parity_day_not_admitted")
    if not isinstance(clock, ParityClock) or clock != admission.clock:
        raise ValueError("parity_clock_differs_from_admission")
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


def open_parity_tapes(root, admission):
    """The only sanctioned way for the parity path to open tapes: D's sealed tapes, bound to the admission clock.

    Refuses (``ValueError``) anything but an admitted ``ParityAdmission``, and a day whose tapes do not bind.
    Re-derives the day, its window and its clock from the token before the glob; never opens another day's tape.
    """
    if not isinstance(admission, ParityAdmission) or not admission.admitted:
        raise ValueError("parity_day_not_admitted")
    _admitted_scope(admission)
    tapes, unsealed = sealed_tapes(root, utc_day(admission.day))
    refused = bind_parity_tapes(admission, tapes, unsealed, admission.clock)
    if refused:
        raise ValueError(refused)
    return tapes


def _refuse(path, what):
    raise ValueError(f"parity_report_not_allowlisted: {path or '<root>'} {what}")


def _allowed_scalar(value, spec):
    if isinstance(spec, frozenset):
        return type(value) is str and value in spec
    if isinstance(spec, re.Pattern):
        return type(value) is str and value.isascii() and bool(spec.fullmatch(value))
    if spec == _COUNT:
        return type(value) is int and 0 <= value <= MAX_COUNT
    if spec == _TICKS:
        return ((type(value) is Decimal and value.is_finite() and 0 <= value <= MAX_COUNT)
                or (type(value) is int and 0 <= value <= MAX_COUNT))
    if spec == _FLAG:
        return type(value) is bool
    if spec == _DAY:
        try:
            return type(value) is str and utc_day(value) == value
        except ValueError:
            return False
    return False


def _check(value, spec, path):
    if isinstance(spec, dict):
        if type(value) is not dict:
            _refuse(path, f"is {type(value).__name__}")
        for key, item in value.items():
            if type(key) is not str or key not in spec:
                _refuse(path, f"key {key!r}")
            _check(item, spec[key], f"{path}.{key}" if path else key)
    elif isinstance(spec, list):
        if type(value) is not list:
            _refuse(path, f"is {type(value).__name__}")
        for index, item in enumerate(value):
            _check(item, spec[0], f"{path}[{index}]")
    elif value is not None and not _allowed_scalar(value, spec):
        _refuse(path, f"value of type {type(value).__name__}")


def assert_outcome_blind(report, admission):
    """On an ``outcome``-window day, refuse any parity report not inside ``PARITY_REPORT_ALLOWLIST``.

    Exact keys at every level (``str`` keys only), and only dict, list, enumerated or pattern-exact ``str``
    (canonical day, 40-hex commit, 64-hex digest, runner tape name), bounded non-negative ``int``, bounded finite
    ``Decimal``, ``bool`` where listed, and None. Objects, dataclasses, tuples, sets, floats and free text are
    refused. The window is re-derived from the token's day (with the permanent windows): the flag alone never
    turns withholding off.
    """
    if not isinstance(admission, ParityAdmission):
        raise ValueError("parity_day_not_admitted")
    scope = _scope(utc_day(admission.day), admission.windows)
    if admission.withhold_outcomes or scope == OUTCOME:
        _check(report, PARITY_REPORT_ALLOWLIST, "")
    return report


__all__ = ["EMBARGOED_UTC_DAYS", "EMBARGO_WINDOWS", "FULL", "MAX_COUNT", "OUTCOME", "PARITY_CLOCK_FIELDS",
           "PARITY_CLOCK_SCHEMA", "PARITY_COUNTERS", "PARITY_FIELD_DISAGREEMENTS", "PARITY_LABEL", "PARITY_REFUSALS",
           "PARITY_REPORT_ALLOWLIST", "PARITY_REPORT_SCHEMA", "PARITY_VERDICTS", "ParityAdmission", "ParityClock",
           "TAPE_GIT_ERRORS", "TAPE_NAME",
           "admit_parity_day", "assert_outcome_blind", "bind_parity_tapes", "embargo_reason", "embargo_scope",
           "open_parity_tapes", "parity_clock_from", "run_started", "utc_day"]
