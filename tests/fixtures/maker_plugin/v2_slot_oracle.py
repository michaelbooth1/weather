# Synthetic-fixture oracle: exact v2 selector from abd648c7c.
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

NBM_NBP_STATION_TIMEZONES = {
    "KLGA": "America/New_York", "KATL": "America/New_York",
    "KMIA": "America/New_York", "KAUS": "America/Chicago",
    "KORD": "America/Chicago", "KDAL": "America/Chicago",
    "KHOU": "America/Chicago", "KBKF": "America/Denver",
    "KLAX": "America/Los_Angeles", "KSFO": "America/Los_Angeles",
    "KSEA": "America/Los_Angeles",
}

def _slot_for_target_v2(rows: dict, issue: datetime, target: date, station_id: str):
    zone_name = NBM_NBP_STATION_TIMEZONES.get(station_id)
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
            # NOAA's 12Z..06Z window is named by its daytime date, not by
            # its ending date. Its start and 00Z label must agree locally.
            local_day = (valid - timedelta(hours=12)).astimezone(zone).date()
            if valid.astimezone(zone).date() != local_day:
                return None, "station_max_date_ambiguous"
            if local_day == target:
                matches.append((group, token, lead, valid))
    if len(matches) != 1:
        return None, "target_max_not_in_cycle" if not matches else "target_max_ambiguous"
    return matches[0], None
