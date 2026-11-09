"""Strict, bounded raw METAR parsing for the expansion settlement rule."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

UTC = timezone.utc


def aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timezone-aware UTC window required")
    return value.astimezone(UTC)


@dataclass(frozen=True)
class MetarReport:
    raw: str
    station: str | None
    observation_time: datetime | None
    report_kind: str
    routine: bool
    corrected: bool
    automatic: bool
    t_group_c: Decimal | None
    body_temperature_c: int | None
    flags: tuple[str, ...]
    receipt_time: datetime | None = None

    @property
    def temperature_c(self) -> Decimal | None:
        fatal = {"malformed_station", "malformed_or_ambiguous_time", "malformed_receipt_time",
                 "ambiguous_t_group", "ambiguous_source_revision"}
        if self.observation_time is None or self.station is None or fatal.intersection(self.flags):
            return None
        if self.t_group_c is None and "ambiguous_body_temperature" in self.flags:
            return None
        return self.t_group_c if self.t_group_c is not None else (
            Decimal(self.body_temperature_c) if self.body_temperature_c is not None else None)

    @property
    def value_basis(self) -> str | None:
        if self.temperature_c is None:
            return None
        if self.t_group_c is not None:
            return "t_group"
        return "body_t_group_malformed" if "malformed_t_group" in self.flags else "body"

    @property
    def has_parse_defect(self) -> bool:
        """A missing value is not itself a defect; unusable malformed/ambiguous data is."""
        return "outside_fetch_window" not in self.flags and self.temperature_c is None and any(
            flag.startswith(("malformed_", "ambiguous_")) for flag in self.flags)


def normalized_report_tokens(report: MetarReport) -> tuple[str, ...]:
    return tuple(report.raw.strip().rstrip("=").split())


def routine_revision_conflicts(reports) -> set[tuple[str, datetime]]:
    """Routine keys with unordered revisions or a conflicting latest-receipt tie.

    Callers filter station/date, as-of and publication cutoff before using this
    helper. SPECI and whitespace differences cannot constitute a revision.
    """
    groups = {}
    for report in reports:
        if report.routine and report.observation_time is not None:
            groups.setdefault((report.station, report.observation_time), []).append(report)
    conflicts = set()
    for key, candidates in groups.items():
        if len({normalized_report_tokens(r) for r in candidates}) < 2:
            continue
        if any(r.receipt_time is None for r in candidates):
            conflicts.add(key)
            continue
        latest = max(r.receipt_time for r in candidates)
        if len({normalized_report_tokens(r) for r in candidates if r.receipt_time == latest}) > 1:
            conflicts.add(key)
    return conflicts


def observation_time_candidates(group: str, start: datetime, end: datetime, *, within_window=True) -> tuple[datetime, ...]:
    """Possible instants in the fetch window; distinguish outside-window from ambiguity."""
    start, end = aware_utc(start), aware_utc(end)
    if end < start or end - start > timedelta(days=31):
        raise ValueError("fetch window must be ordered and at most 31 days")
    match = re.fullmatch(r"(\d{2})(\d{2})(\d{2})Z", group)
    if not match:
        return ()
    day, hour, minute = map(int, match.groups())
    candidates = []
    month = start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    while month <= end:
        try:
            candidate = month.replace(day=day, hour=hour, minute=minute)
        except ValueError:
            candidate = None
        if candidate is not None and (not within_window or start <= candidate <= end):
            candidates.append(candidate)
        month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
    return tuple(candidates)


def resolve_observation_time(group: str, start: datetime, end: datetime) -> datetime | None:
    """Resolve DDHHMMZ only when exactly one instant is in the inclusive fetch window."""
    candidates = observation_time_candidates(group, start, end)
    return candidates[0] if len(candidates) == 1 else None


def parse_metar(raw: str, start: datetime, end: datetime, *, receipt_time=None) -> MetarReport:
    tokens = raw.strip().rstrip("=").split()
    flags = []
    if "RMK" in tokens:
        split = tokens.index("RMK")
        body, remarks = tokens[:split], tokens[split + 1:]
    else:
        body, remarks = tokens, []
    # Only the report header carries station/time/indicators; remarks cannot change kind.
    header = body[:6]
    special = bool(tokens and tokens[0] == "SPECI")
    corrected, automatic = "COR" in header, "AUTO" in header
    kind = ("SPECI" if special else "COR" if corrected else "AUTO" if automatic else
            "METAR" if tokens and tokens[0] == "METAR" else "unlabelled")
    cursor = 1 if tokens and tokens[0] in {"METAR", "SPECI"} else 0
    if cursor < len(body) and body[cursor] == "COR":
        cursor += 1
    station = body[cursor] if cursor < len(body) and re.fullmatch(r"[A-Z]{4}", body[cursor]) else None
    if station is None:
        flags.append("malformed_station")
    cursor += 1
    if cursor < len(body) and body[cursor] == "COR":
        cursor += 1
    stamp = body[cursor] if cursor < len(body) else ""
    candidates = observation_time_candidates(stamp, start, end)
    observed = candidates[0] if len(candidates) == 1 else None
    if observed is None:
        valid_stamp = observation_time_candidates(stamp, start, end, within_window=False)
        flags.append("ambiguous_observation_time" if len(candidates) > 1 else
                     "outside_fetch_window" if valid_stamp else "malformed_or_ambiguous_time")
    t_tokens = [token for token in remarks if re.match(r"T\d", token)]
    t_values = []
    for token in t_tokens:
        # Exactly eight digits; the following four dew-point digits are unused.
        match = re.fullmatch(r"T([01])(\d{3})\d{4}", token)
        if match:
            t_values.append(Decimal(int(match[2]) * (-1 if match[1] == "1" else 1)) / 10)
        else:
            flags.append("malformed_t_group")
    if len(t_values) > 1:
        flags.append("ambiguous_t_group")
    if not t_tokens:
        flags.append("t_group_missing")
    t_value = t_values[0] if len(t_values) == 1 else None
    temps = []
    for token in body[cursor + 1:]:
        match = re.fullmatch(r"(M?)(\d{2})/(?:M?\d{2}|//)?", token)
        if match:
            temps.append(int(match[2]) * (-1 if match[1] else 1))
        elif "/" in token and re.match(r"M?\d", token) and not token.endswith(("SM", "KT", "FT")):
            flags.append("malformed_body_temperature")
    if len(temps) > 1:
        flags.append("ambiguous_body_temperature")
    body_value = temps[0] if len(temps) == 1 else None
    if body_value is None:
        flags.append("body_temperature_missing")
    if receipt_time is not None:
        receipt_time = aware_utc(receipt_time)
        if observed is not None and receipt_time < observed:
            flags.append("malformed_receipt_time")
    return MetarReport(raw.strip(), station, observed, kind, not special, corrected, automatic,
                       t_value, body_value, tuple(flags), receipt_time)


def parse_metar_text(text: str, start: datetime, end: datetime) -> tuple[list[MetarReport], dict[str, int]]:
    reports = [parse_metar(line, start, end) for line in text.splitlines() if line.strip()]
    return reports, dict(Counter(flag for report in reports for flag in report.flags))
