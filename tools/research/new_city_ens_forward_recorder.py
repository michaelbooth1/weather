"""Lane L3: new-city ECMWF ENS forward recorder (DRAFT, not registered): L13's ENS recorder at five new stations.

This reuses L13's ``ecmwf_ens_forward_recorder`` unchanged: the same free ECMWF open data, byte-range reads, CCSDS
decoder, receipts, manifests, guards and forward-only rule. It only rebinds the station set, the schema and the
identity, and runs as its own instance with its own output root, lock, STOP and pause files:

* **Stations.** The settlement stations of the thin markets chosen by the 2026-10-30 survey
  (``docs/research/new-city-thin-markets-2026-10-30.md`` on ``claude/new-city-recorders-20261030``). Each ICAO is the
  one the venue rules text names (``resolutionSource`` METAR id, events of 2026-11-01, read 2026-10-30T21:00Z).
  The coordinates are ``config/locations.json``'s, and a test checks them. The venue publishes no coordinates.
* **Output.** ``--out`` defaults to ``C:\\t\\new_city_ens\\forward``, never L13's ``C:\\t\\ecmwf_ens\\forward``. The
  wrapper refuses that root.
* **Identity.** The schema is ``l3_new_city_ens_forward/1``. The recorder sha256 combines this file and L13's module.

Highest-temperature only: L13's recorder knows ``mx2t3`` and ``2t``, not a 3-hour minimum, so the lowest-temperature
events of these cities get no ENS minimum here. That is flagged in the note.
Research / shadow only: nothing imports this module and nothing is served.
"""
from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("ecmwf_ens_forward_recorder", _HERE / "ecmwf_ens_forward_recorder.py")
ens = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ens)

SCHEMA = "l3_new_city_ens_forward/1"
DEFAULT_OUT = str(Path("C:/t/new_city_ens/forward"))
L13_OUT = str(Path("C:/t/ecmwf_ens/forward"))
# market, venue ICAO, lat, lon (config/locations.json coordinates; the test checks them)
NEW_CITY_STATIONS = (
    ("panama-city", "MPMG", 8.967, -79.555),
    ("sao-paulo", "SBGR", -23.432, -46.469),
    ("qingdao", "ZSQD", 36.362, 120.087),
    ("ankara", "LTAC", 40.128, 32.995),
    ("moscow", "UUWW", 55.592, 37.261),
)


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def code_identity():
    out = {}
    for p in (Path(__file__), _HERE / "ecmwf_ens_forward_recorder.py"):
        raw = p.read_bytes()
        out[p.name] = {"git_blob_lf": ens.git_blob_id(raw.replace(b"\r\n", b"\n")), "sha256": _sha256(raw)}
    return out


def combined_sha256():
    return _sha256(Path(__file__).read_bytes() + b"\0" + (_HERE / "ecmwf_ens_forward_recorder.py").read_bytes())


class NewCityRecorder(ens.Recorder):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.code_sha256 = combined_sha256()


def configure():
    """Rebind the reused module's station set, schema, identity and recorder class (globals read at run time)."""
    ens.STATIONS = NEW_CITY_STATIONS
    ens.CORNERS = {s[1]: ens.station_corners(s[2], s[3]) for s in NEW_CITY_STATIONS}
    ens.WANTED = sorted({i for c in ens.CORNERS.values() for i in c["idx"]})
    ens.SCHEMA = SCHEMA
    ens.code_identity = code_identity
    ens.Recorder = NewCityRecorder


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not any(a == "--out" or a.startswith("--out=") for a in argv):
        argv = ["--out", DEFAULT_OUT] + argv
    out = argv[argv.index("--out") + 1] if "--out" in argv else next(a for a in argv if a.startswith("--out="))[6:]
    if Path(out).resolve() == Path(L13_OUT).resolve():
        raise SystemExit("refusing L13's ENS output root; use the new-city root")
    configure()
    return ens.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
