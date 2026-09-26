"""Offline NBP parsing; v2 slot rule vendored from abd648c7c (110b).

Only the station block parser and target-period selector are carried here;
no archive, provider, networking or source-module import is needed.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import re
from zoneinfo import ZoneInfo

from weather.market.maker_plugin.inputs import timestamp

STATION_TIMEZONES = {
    "KLGA": "America/New_York", "KATL": "America/New_York", "KMIA": "America/New_York",
    "KAUS": "America/Chicago", "KORD": "America/Chicago", "KDAL": "America/Chicago",
    "KHOU": "America/Chicago", "KBKF": "America/Denver", "KLAX": "America/Los_Angeles",
    "KSFO": "America/Los_Angeles", "KSEA": "America/Los_Angeles",
}
CYCLES = (1, 7, 13, 19)
PERCENTILE_ROWS = ("TXNP1", "TXNP2", "TXNP5", "TXNP7", "TXNP9")


def slot_for_target_v2(rows, issue, target, station_id):
    zone_name = STATION_TIMEZONES.get(station_id)
    if zone_name is None:
        return None, "station_max_date_ambiguous"
    zone = ZoneInfo(zone_name)
    matches = []
    for group, pair in enumerate(rows.get("FHR") or []):
        for token, lead in enumerate(pair):
            if lead is None or lead < 0 or not lead.is_integer():
                continue
            valid = issue + timedelta(hours=lead)
            if valid.hour != 0 or valid.minute != 0:
                continue
            local_day = (valid - timedelta(hours=12)).astimezone(zone).date()
            if valid.astimezone(zone).date() != local_day:
                return None, "station_max_date_ambiguous"
            if local_day == target:
                matches.append((group, token, lead, valid))
    if len(matches) != 1:
        return None, "target_max_not_in_cycle" if not matches else "target_max_ambiguous"
    return matches[0], None


def parse_pair_row(line):
    """Fixed-width row code and pipe-separated pairs; extra tokens fail closed."""
    pairs = []
    for group in line[6:].split("|"):
        tokens = [float(v) for v in re.findall(r"-?\d+(?:\.\d+)?", group)]
        if len(tokens) > 2:
            raise ValueError("ambiguous_nbp_pair")
        pairs.append(tuple((tokens + [None, None])[:2]))
    return pairs


def parse(raw, station, target):
    text = raw["text"]
    if hashlib.sha256(text.encode()).hexdigest() != raw["payload_hash"]:
        raise ValueError("nbp_payload_hash_mismatch")
    if raw["station_id"] != station or raw["target_date"] != target.isoformat():
        raise ValueError("nbp_extraction_identity_mismatch")
    blocks = []
    active = None
    for line in text.splitlines():
        if re.match(r"^\s*\w+\s+NBM\s+V\S+\s+NBP\s+GUIDANCE", line):
            active = [] if re.match(rf"^\s*{re.escape(station)}\s+NBM\b", line) else None
            if active is not None:
                blocks.append(active)
        if active is not None:
            active.append(line)
    if len(blocks) != 1:
        raise ValueError("missing_or_ambiguous_station_block")
    match = re.search(r"GUIDANCE\s+(\d{1,2}/\d{1,2}/\d{4})\s+(\d{4})\s+UTC", blocks[0][0])
    if match is None:
        raise ValueError("nbp_issue_time_not_found")
    issue = datetime.strptime(" ".join(match.groups()), "%m/%d/%Y %H%M").replace(tzinfo=timezone.utc)
    if timestamp(raw["fetched_at"]) < issue:
        raise ValueError("nbp_capture_precedes_issue")
    rows = {}
    for line in blocks[0][1:]:
        code = line[:6].strip().upper()
        if code not in ("FHR", *PERCENTILE_ROWS, "TXNMN", "TXNSD"):
            continue
        if code in rows:
            raise ValueError("duplicate_nbp_row")
        rows[code] = parse_pair_row(line)
    slot, reason = slot_for_target_v2(rows, issue, target, station)
    if slot is None:
        raise ValueError(reason)
    group, token, _, _ = slot
    values = []
    for code in (*PERCENTILE_ROWS, "TXNMN", "TXNSD"):
        pairs = rows.get(code, [])
        value = pairs[group][token] if group < len(pairs) else None
        if value is None or value == -99 or (code == "TXNSD" and value < 0):
            raise ValueError("target_max_incomplete_rows")
        values.append(value)
    if any(a >= b for a, b in zip(values[:4], values[1:5])):
        raise ValueError("nonincreasing_percentile_knots")
    return issue, tuple(values[:5]), slot


def valid_until(issue):
    availability = [issue.replace(hour=h, minute=0, second=0, microsecond=0)
                    + timedelta(days=d, hours=1) for d in (0, 1) for h in CYCLES
                    if issue.replace(hour=h, minute=0, second=0, microsecond=0)
                    + timedelta(days=d) > issue]
    return min(min(availability), issue + timedelta(hours=24))
