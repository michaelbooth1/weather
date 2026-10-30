"""Lane L3: new-city price forward recorder (DRAFT, not registered): the T+1 price recorder for thin new markets.

This reuses ``t1_price_forward_recorder`` unchanged: the same two public, read-only International Polymarket
reads, URL allowlist, cycle and manifest integrity, guards and no-backfill rule. Only these differ:

* **Markets.** The thin markets chosen by the 2026-10-30 survey
  (``docs/research/new-city-thin-markets-2026-10-30.md``): the highest-temperature events of Panama City, Sao
  Paulo, Qingdao, Ankara and Moscow, plus the lowest-temperature events of the four that list them (Panama City
  has none). Each id maps to (event slug prefix, IANA time zone). Slug prefixes and time zones match
  ``config/locations.json``, and a test checks that. The station each event settles on comes from the venue rules
  text (METAR ICAO in ``resolutionSource``). It is recorded in ``STATIONS`` for the record only; the recorder never
  reads a station.
* **Horizons.** T+0 and T+1 by default (``--horizons 0,1``); T+2 is allowed, but the venue lists some T+2 events
  only later in the UTC day (404 in the 2026-10-30 21:00Z dry run), which would mark those cycles incomplete.
  A T+0 price is a current price of an open event; the recorder never reads a settlement or resolution field.
* **Identity.** The rows carry the schema ``l3_new_city_price_forward/1``. The recorder sha256 combines this file
  and the reused module, so a change to either shows in every cycle record and manifest.

Research / shadow only: nothing imports this module and nothing is served.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("t1_price_forward_recorder", _HERE / "t1_price_forward_recorder.py")
t1 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(t1)

SCHEMA = "l3_new_city_price_forward/1"
HORIZONS = (0, 1, 2)
# id -> (event slug prefix, IANA time zone); config/locations.json agrees (test).
NEW_CITY_MARKETS = {
    "panama-city": ("highest-temperature-in-panama-city-on", "America/Panama"),
    "sao-paulo": ("highest-temperature-in-sao-paulo-on", "America/Sao_Paulo"),
    "qingdao": ("highest-temperature-in-qingdao-on", "Asia/Shanghai"),
    "ankara": ("highest-temperature-in-ankara-on", "Europe/Istanbul"),
    "moscow": ("highest-temperature-in-moscow-on", "Europe/Moscow"),
    "sao-paulo-lowest": ("lowest-temperature-in-sao-paulo-on", "America/Sao_Paulo"),
    "qingdao-lowest": ("lowest-temperature-in-qingdao-on", "Asia/Shanghai"),
    "ankara-lowest": ("lowest-temperature-in-ankara-on", "Europe/Istanbul"),
    "moscow-lowest": ("lowest-temperature-in-moscow-on", "Europe/Moscow"),
}
# Record only: the station named by the venue rules text for the 2026-11-01 events (read 2026-10-30T21:00Z).
STATIONS = {
    "panama-city": "MPMG", "sao-paulo": "SBGR", "qingdao": "ZSQD", "ankara": "LTAC", "moscow": "UUWW",
}


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def code_identity():
    out = {}
    for p in (Path(__file__), _HERE / "t1_price_forward_recorder.py"):
        raw = p.read_bytes()
        out[p.name] = {"git_blob_lf": t1.git_blob_id(raw.replace(b"\r\n", b"\n")), "sha256": _sha256(raw)}
    return out


def combined_sha256():
    return _sha256((Path(__file__).read_bytes() + b"\0" + (_HERE / "t1_price_forward_recorder.py").read_bytes()))


def configure():
    """Point the reused module at this recorder's schema, horizons and identity (module globals read at run time)."""
    t1.SCHEMA = SCHEMA
    t1.HORIZONS = HORIZONS
    t1.code_identity = code_identity


class NewCityRecorder(t1.Recorder):
    def __init__(self, out, http, markets=None, **kw):
        configure()
        super().__init__(out, http, markets=dict(markets if markets is not None else NEW_CITY_MARKETS), **kw)
        self.code_sha256 = combined_sha256()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=r"C:\t\new_city_prices\forward")
    ap.add_argument("--horizons", default="0,1", help="0,1 by default; 2 is allowed, but some T+2 events are listed only later in the day")
    ap.add_argument("--top-of-hour-only", action="store_true", help="skip the :15/:30/:45 points")
    ap.add_argument("--pause-file", default=None, help="default <out>/RECORDER_PAUSE")
    ap.add_argument("--stop-file", default=None, help="default <out>/STOP")
    ap.add_argument("--wait-lock-seconds", type=float, default=0.0)
    ap.add_argument("--poll-seconds", type=int, default=20)
    ap.add_argument("--min-interval-seconds", type=float, default=0.2)
    ap.add_argument("--hourly-requests", type=int, default=4000)
    ap.add_argument("--net-cap-gb", type=float, default=20.0, help="network byte cap for this process")
    ap.add_argument("--cap-gb", type=float, default=2.0, help="output directory size cap")
    ap.add_argument("--min-free-gb", type=float, default=20.0)
    ap.add_argument("--max-steps", type=int, default=None)
    ap.add_argument("--once", action="store_true", help="one foreground cycle for the current slot, then exit")
    args = ap.parse_args(argv)
    horizons = tuple(int(h) for h in args.horizons.split(",") if h.strip())
    out = Path(args.out)
    repo = _HERE.parents[1]
    if repo in out.resolve().parents or out.resolve() == repo:
        raise SystemExit("output must be outside the repository")
    out.mkdir(parents=True, exist_ok=True)
    lock = t1.acquire_lock(out / "recorder.lock", args.wait_lock_seconds)  # noqa: F841 - held until exit
    prio = t1.set_below_normal_priority()
    rec = NewCityRecorder(out, t1.Http(int(args.net_cap_gb * 1e9)), horizons=horizons, pause_file=args.pause_file,
                          stop_file=args.stop_file, min_interval_s=args.min_interval_seconds,
                          hourly_requests=args.hourly_requests, min_free_gb=args.min_free_gb, cap_gb=args.cap_gb,
                          quarter_hours=not args.top_of_hour_only)
    rec.log_event("priority", below_normal=prio)
    if args.once:
        slot = t1.slot_floor(rec.clock())
        rec.log_event("once", slot=t1._iso(slot), code=code_identity(), stations=STATIONS)
        cycle = rec.run_slot(slot)
        result = {k: cycle[k] for k in ("slot_utc", "complete", "events_expected", "events_rows", "events_complete",
                                        "events_sum_in_range", "reasons")}
        result.update(bytes=rec.http.used, requests=rec.http.requests)
        rec.status("once_done", result)
        print(json.dumps(result))
        return 0
    (out / "recorder.pid").write_text(str(os.getpid()), encoding="ascii")
    rec.run(args.poll_seconds, args.max_steps)
    return 0


if __name__ == "__main__":
    sys.exit(main())
