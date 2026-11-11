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
    fetch_start: datetime
    fetch_end: datetime
    receipt_time: datetime | None = None

    @property
    def temperature_c(self) -> Decimal | None:
        fatal = {"malformed_station", "malformed_or_ambiguous_time", "malformed_receipt_time",
                 "ambiguous_t_group", "ambiguous_source_revision", "malformed_report_type",
                 "malformed_correction_marker"}
        if self.observation_time is None or self.station is None or fatal.intersection(self.flags):
            return None
        if self.t_group_c is None and {"ambiguous_body_temperature", "malformed_body_temperature"}.intersection(self.flags):
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
        """Unusable settlement fields; station/time attribution is handled separately."""
        critical = {"malformed_body_temperature", "ambiguous_body_temperature",
                    "malformed_t_group", "ambiguous_t_group", "malformed_report_type",
                    "malformed_correction_marker", "ambiguous_source_revision",
                    "malformed_receipt_time"}
        return "outside_fetch_window" not in self.flags and self.temperature_c is None and bool(
            critical.intersection(self.flags))

    @property
    def has_unreadable_time(self) -> bool:
        return self.observation_time is None and bool(
            {"malformed_or_ambiguous_time", "ambiguous_observation_time"}.intersection(self.flags))


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


def header_station(raw: str, station_ids=None) -> tuple[str | None, int | None, int | None]:
    """Recover a header ICAO, preferring exact requested ids over token shape.

    Only the first four tokens before the observation-time token or RMK may
    identify a station. Unknown type/COR tokens must not shift its identity.
    """
    body = raw.strip().rstrip("=").split()
    body = body[:body.index("RMK")] if "RMK" in body else body
    stamp_index = next((i for i, token in enumerate(body[:6])
                        if re.fullmatch(r"[A-Z0-9]{6}Z", token)), None)
    limit = min(4, stamp_index) if stamp_index is not None else 4
    requested = set(station_ids) if station_ids is not None else None
    candidates = [(i, token) for i, token in enumerate(body[:limit])
                  if (token in requested if requested is not None else
                      re.fullmatch(r"[A-Z]{4}", token) and token not in {"AUTO"})]
    if not candidates:
        return None, None, stamp_index
    index, station = candidates[-1]
    return station, index, stamp_index


def non_temperature_body_token(token: str) -> bool:
    """Explicit exclusions for slash-bearing non-temperature METAR/TAF groups."""
    return any(re.fullmatch(pattern, token) for pattern in (
        r"\d{4}/\d{4}",                          # TAF validity, e.g. 0703/0803
        r"[MP]?\d+(?:/\d+)?SM",                 # statute-mile visibility
        r"R\d{2}[LCR]?/[A-Z0-9/]+",             # runway visual range/state
        r"\d{2}[LCR]?/[MP]?\d+(?:V[MP]?\d+)?FT", # runway visibility without R, in feet
        r"(?:FEW|SCT|BKN|OVC|VV)(?:\d{3}|///)(?:CB|TCU|///)?", # automated cloud groups
        r"T[XN]M?\d{2}/\d{4}Z",                 # forecast maximum/minimum
        r"(?:\d{3}|VRB|///)(?:P?\d{2,3}|//)(?:G(?:P?\d{2,3}|//))?(?:KT|MPS)",
        r"W(?:M?\d{2}|//)/(?:S\d|H\d{1,3})",  # sea temperature with state/height
    ))


def parse_metar(raw: str, start: datetime, end: datetime, *, receipt_time=None, station_ids=None) -> MetarReport:
    start, end = aware_utc(start), aware_utc(end)
    tokens = raw.strip().rstrip("=").split()
    flags = []
    if "RMK" in tokens:
        split = tokens.index("RMK")
        body, remarks = tokens[:split], tokens[split + 1:]
    else:
        body, remarks = tokens, []
    # Recover attribution before validating header order/type/correction markers.
    station, station_index, stamp_index = header_station(raw, station_ids)
    cursor = station_index + 1 if station_index is not None else 0
    if stamp_index is None:
        while cursor < len(body) and body[cursor] in {"COR", "AUTO"}:
            cursor += 1
        stamp_index = cursor
    header = body[:stamp_index + 3]
    special = bool(tokens and tokens[0] == "SPECI")
    corrected, automatic = "COR" in header, "AUTO" in header
    kind = ("SPECI" if special else "COR" if corrected else "AUTO" if automatic else
            "METAR" if tokens and tokens[0] == "METAR" else "unlabelled")
    if station is None:
        flags.append("malformed_station")
    else:
        prefix = body[:station_index]
        if prefix and prefix[0] in {"METAR", "SPECI"}:
            prefix = prefix[1:]
        elif prefix and prefix[0] not in {"COR", "AUTO"} and not re.fullmatch(r"C[O0]R\w*", prefix[0]):
            flags.append("malformed_report_type")
            prefix = prefix[1:]
        modifiers = prefix + body[station_index + 1:stamp_index]
        if any(token not in {"COR", "AUTO"} for token in modifiers) or any(
                token != "COR" and re.fullmatch(r"C[O0]R\w*", token) for token in body[stamp_index + 1:stamp_index + 3]):
            flags.append("malformed_correction_marker")
    cursor = stamp_index
    stamp = body[cursor] if cursor < len(body) else ""
    candidates = observation_time_candidates(stamp, start, end)
    observed = candidates[0] if len(candidates) == 1 else None
    if observed is None:
        valid_stamp = observation_time_candidates(stamp, start, end, within_window=False)
        flags.append("ambiguous_observation_time" if len(candidates) > 1 else
                     "outside_fetch_window" if valid_stamp else "malformed_or_ambiguous_time")
    t_tokens = [token for token in remarks if re.match(r"T(?:\d|[OX](?=\d))", token)]
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
        elif not non_temperature_body_token(token) and (
                "/" in token and (re.search(r"\d", token) or re.fullmatch(r"[MX]{2}/[MX]{2}", token))
                or re.fullmatch(r"M?\d{1,3}-M?\d{1,3}", token)):
            # Broader corruption guard: extra digits/slashes must not become
            # true absence. Keep the explicit non-temperature exclusions above.
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
                       t_value, body_value, tuple(flags), start, end, receipt_time)


def parse_metar_text(text: str, start: datetime, end: datetime, *, station_ids=None) -> tuple[list[MetarReport], dict[str, int]]:
    station_ids = tuple(station_ids) if station_ids is not None else None
    reports = [parse_metar(line, start, end, station_ids=station_ids) for line in text.splitlines() if line.strip()]
    counts = Counter(flag for report in reports for flag in report.flags)
    for report in reports:
        if report.station is None:
            counts["unattributed_lines"] += 1
        if report.has_unreadable_time:
            counts["unreadable_time_lines"] += 1
            if report.receipt_time is None:
                counts["unreadable_time_without_receipt"] += 1
    return reports, dict(counts)
