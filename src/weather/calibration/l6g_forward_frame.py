"""Lane L2: the L6_G forward frame builder, MG-2's forward input layout -> the emitter's input frame (outcome-blind).

Clarification: ``docs/research/gefs-members-l11-2026-10-26/l6g_forward_frame_clarification_2026-10-29.md``;
pre-registration ``l6g_forward_prereg_DRAFT.md`` §3. Chain for one local date D (nothing here fetches):

1. MG-2's verified bundle -> the MG-2 input receiver's ``build`` -> the label-free per-date layout
   (``inputs_snapshots.parquet``, ``inputs_bands.parquet``, ``manifest.json``), re-hashed here against its manifest
   (``read_layout``; this module does not import the receiver, which no ``src`` module may reference);
2. ``mg2_composite captured-nowcast --prev-root`` -> ``nowcasts.parquet`` (``n_own``) and its manifest, accepted only
   under the binding's ``forward_nowcasts`` rules (bundle prev_day, file sha, season-matched L6 state 800072c7...),
   re-checked here (``read_nowcasts``);
3. the L6 part of the coefficients file at B's canonical part sha256 (07a67425...), re-checked here exactly as the
   binding's ``load_part`` does (``load_l6_part``). No ``src`` module may import the MG-2 binding, so neither check
   imports it; the tests prove both agree with it.
4. this module: the L6 arm's centre exactly as ``l6_stack.predict`` (mu = v2_mean + a_h + b_h (N - v2_mean) where
   N and v2_mean are finite, else v2_mean) and MG-1's usability mask (``covered_l6``), written as
   ``emit_snapshots.parquet`` / ``emit_bands.parquet`` with exclusive create, then handed to ``l6g_forward_emit``.

Outcome-blind: no label, market, settlement or price file is opened. Every input frame (layout snapshots, layout
bands, nowcasts) is screened first and refused if any column could carry a label, an outcome, a final observed or
settled high, or a price/market quote (``refuse_columns``: the emitter's markers, the dev scorecard's LABELISH set
and the final-high names). The PIT floor inputs (``high_so_far``, ``trusted_current_max``,
``guidance_physical_floor``) are inputs, not outcomes. ``run`` is the emission path: it screens the emitter's input
frame again with this module's wider list before ``l6g_forward_emit.emit_day``, which then applies its own screen.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path

from weather.calibration import l6g_forward_emit as emit
from weather.calibration import l6g_forward_look as look

NAME = "l6g_forward_frame"
SCHEMA = "l6g_forward_frame/1"
LAYOUT_FILES = ("inputs_snapshots.parquet", "inputs_bands.parquet")
PARSER_VERSION = 2  # the receiver stamps v2_parser_version = 2 on every layout row
L6_PART_SHA256 = "07a6742595f535d448569980af7e04dbf4a2a798c00c82fd52f5f01287ee17e9"  # B §1 L6 part (canonical)
L6_STATE_SHA256 = "800072c79af65394cc33134cbaae34af65c4428feb3934e35f8cd6cd153ee2db"  # B §1 season-matched state
SNAPSHOTS_OUT = "emit_snapshots.parquet"
BANDS_OUT = "emit_bands.parquet"
FRAME_MANIFEST = "frame_manifest.json"
SNAPSHOT_NEEDS = ("row_key", "date", "market", "local_hour", "captured_at_utc", "v2_mean", "v2_stddev",
                  "v2_available_at", "floor", "v2_parser_version")
BAND_NEEDS = ("row_key", "band_index", "kind", "low", "high")
_FINAL_HIGH_MARKERS = ("observed_high", "observed_max", "final_high", "final_max", "daily_high", "daily_max",
                       "day_high", "day_max", "settled", "settlement", "wu_high", "official_high", "is_winner",
                       "outcome", "label", "price", "market_mid", "market_yes", "best_bid", "best_ask", "orderbook")


class FrameError(RuntimeError):
    """A refusal: nothing was written."""


def module_sha256():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def refuse_columns(columns, what):
    """Refuse any column that could carry a label, outcome, final/settled high, or a price or market quote."""
    from weather.reporting.scorecards import dev_scorecard_data as data

    markers = tuple(look._PRICE_MARKERS) + tuple(emit._OUTCOME_MARKERS) + _FINAL_HIGH_MARKERS
    bad = sorted(c for c in columns
                 if any(k in str(c).lower() for k in markers) or str(c).lower() in emit._OUTCOME_EXACT
                 or str(c) in data.LABELISH)
    if bad:
        raise FrameError(f"{what} carries label/outcome/final-high/price columns {bad}; the frame is outcome-blind")


def read_layout(root, day):
    """One per-date layout, every file re-hashed against its manifest, for ``day`` only; screened before use."""
    import pandas as pd

    root = Path(root)
    path = root / "manifest.json"
    if not path.is_file():
        raise FrameError(f"layout {root} has no manifest.json")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("target_date") != day:
        raise FrameError(f"layout {root} is for {manifest.get('target_date')!r}, not {day}")
    files = manifest.get("files") or {}
    for name in LAYOUT_FILES:
        entry = files.get(name) or {}
        if not (root / name).is_file() or _sha(root / name) != entry.get("sha256"):
            raise FrameError(f"layout {root}: {name} does not match its manifest")
    snaps = pd.read_parquet(root / LAYOUT_FILES[0])
    bands = pd.read_parquet(root / LAYOUT_FILES[1])
    refuse_columns(snaps.columns, "layout snapshots")
    refuse_columns(bands.columns, "layout bands")
    for what, frame, need in (("layout snapshots", snaps, SNAPSHOT_NEEDS), ("layout bands", bands, BAND_NEEDS)):
        missing = set(need) - set(frame.columns)
        if missing:
            raise FrameError(f"{what} lack {sorted(missing)}")
    if len(snaps) != manifest.get("snapshots") or (len(snaps) and set(snaps["date"].astype(str).str[:10]) != {day}):
        raise FrameError(f"layout {root}: snapshot rows do not match its manifest or its target date {day}")
    if len(snaps) and set(pd.to_numeric(snaps["v2_parser_version"], errors="coerce")) != {PARSER_VERSION}:
        raise FrameError(f"layout {root}: rows not built by v2 parser version {PARSER_VERSION}")
    return _sha(path), snaps, bands


NOWCASTS_MANIFEST = "nowcasts_manifest.json"
FORWARD_PREV_DAY_SOURCE = "bundle prev_day"
L6_PART_KEY = "l6_stack"


def nowcasts_info(path):
    """The binding's forward-nowcast acceptance: bundle prev_day, the recorded file sha, the bound L6 state."""
    mpath = Path(path).parent / NOWCASTS_MANIFEST
    if not mpath.is_file():
        raise FrameError(f"forward emission needs {NOWCASTS_MANIFEST} beside the nowcasts")
    manifest = json.loads(mpath.read_text(encoding="utf-8"))
    if manifest.get("prev_day_source") != FORWARD_PREV_DAY_SOURCE:
        raise FrameError(f"forward nowcasts must come from captured_nowcast with --prev-root "
                         f"(prev_day_source {manifest.get('prev_day_source')!r})")
    if manifest.get("nowcasts_sha256") != _sha(path):
        raise FrameError("the nowcasts file is not the one its manifest records")
    if manifest.get("l6_state_sha256") != L6_STATE_SHA256:
        raise FrameError(f"the nowcasts were served by L6 state {manifest.get('l6_state_sha256')!r}, not the bound "
                         f"{L6_STATE_SHA256}")
    return {k: manifest.get(k) for k in ("nowcasts_sha256", "l6_state_sha256", "prev_day_source", "first", "last")}


def read_nowcasts(path, day, column):
    import pandas as pd

    info = nowcasts_info(path)
    if not (str(info.get("first")) <= day <= str(info.get("last"))):
        raise FrameError(f"the nowcasts cover {info.get('first')}..{info.get('last')}, not {day}")
    frame = pd.read_parquet(path)
    refuse_columns(frame.columns, "nowcasts")
    if "row_key" not in frame.columns or column not in frame.columns:
        raise FrameError(f"nowcasts lack row_key or {column}")
    if frame["row_key"].duplicated().any():
        raise FrameError("nowcasts repeat a row_key")
    return info, frame.set_index("row_key")[column]


def part_sha256(part):
    """The binding's canonical part sha256: sorted keys, compact separators, no NaN, UTF-8."""
    return hashlib.sha256(json.dumps(part, sort_keys=True, separators=(",", ":"), allow_nan=False)
                          .encode("utf-8")).hexdigest()


def load_l6_part(coefficients):
    payload = json.loads(Path(coefficients).read_bytes())
    if L6_PART_KEY not in payload:
        raise FrameError(f"{coefficients} has no {L6_PART_KEY} part")
    part = payload[L6_PART_KEY]
    sha = part_sha256(part)
    if sha != L6_PART_SHA256:
        raise FrameError(f"l6 coefficients sha {sha} != rule's {L6_PART_SHA256}")
    return part["column"], {int(h): (float(v[0]), float(v[1])) for h, v in part["coef"].items()}


def l6_frame(snaps, bands, n, coef):
    """The emitter's (snapshots, bands) frames. Pure: no I/O. ``n`` is the nowcast Series indexed by row_key."""
    import numpy as np
    import pandas as pd

    s = snaps.reset_index(drop=True)
    if s["row_key"].duplicated().any():
        raise FrameError("the layout repeats a row_key")
    nn = n.reindex(s["row_key"]).to_numpy(float)
    v2 = pd.to_numeric(s["v2_mean"], errors="coerce").to_numpy(float)
    hours = s["local_hour"].to_numpy(int)
    mu = v2.copy()
    for h, (a, b) in coef.items():  # l6_stack.predict
        sel = (hours == h) & np.isfinite(nn) & np.isfinite(v2)
        mu[sel] = v2[sel] + a + b * (nn[sel] - v2[sel])
    sd = pd.to_numeric(s["v2_stddev"], errors="coerce").to_numpy(float)
    avail = pd.to_datetime(s["v2_available_at"], utc=True, errors="coerce")
    t = pd.to_datetime(s["captured_at_utc"], utc=True)
    covered = np.isfinite(mu) & np.isfinite(sd) & avail.notna().to_numpy() & (avail <= t).fillna(False).to_numpy()
    out_s = pd.DataFrame({"snapshot_id": s["row_key"].astype(str), "date": s["date"].astype(str).str[:10],
                          "market": s["market"].astype(str), "local_hour": hours, "l6_mu": mu, "v2_stddev": sd,
                          "v2_mean": v2, "floor": pd.to_numeric(s["floor"], errors="coerce").to_numpy(float),
                          "covered_l6": covered})
    b = bands[bands["row_key"].isin(set(s["row_key"]))]
    out_b = pd.DataFrame({"snapshot_id": b["row_key"].astype(str).to_numpy(),
                          "band_index": b["band_index"].astype(int).to_numpy(), "kind": b["kind"].to_numpy(),
                          "low": pd.to_numeric(b["low"], errors="coerce").to_numpy(float),
                          "high": pd.to_numeric(b["high"], errors="coerce").to_numpy(float)})
    missing = set(out_s["snapshot_id"]) - set(out_b["snapshot_id"])
    if missing:
        raise FrameError(f"{len(missing)} snapshot(s) have no bands")
    return out_s[list(emit.SNAPSHOT_COLUMNS)], out_b[list(emit.BAND_COLUMNS)]


def build(*, day, layout_root, nowcasts, coefficients, out_dir):
    """Write ``<out_dir>/<D>/`` (exclusive create) and return its manifest."""
    day = dt.date.fromisoformat(str(day)).isoformat()
    if dt.date.fromisoformat(day) < emit.FORWARD_FIRST:
        raise FrameError(f"{day} is before {emit.FORWARD_FIRST}: never backfilled")
    target = Path(out_dir) / day
    if target.exists():
        raise FrameError(f"{target} exists: one frame per date, never rewritten")
    column, coef = load_l6_part(coefficients)
    layout_manifest_sha, snaps, bands = read_layout(layout_root, day)
    now_info, n = read_nowcasts(nowcasts, day, column)
    s, b = l6_frame(snaps, bands, n, coef)
    target.mkdir(parents=True)
    for name, frame in ((SNAPSHOTS_OUT, s), (BANDS_OUT, b)):
        with open(target / name, "xb") as handle:
            frame.to_parquet(handle, index=False)
    manifest = {"schema": SCHEMA, "date": day, "module_sha256": module_sha256(),
                "inputs": {"layout_manifest_sha256": layout_manifest_sha, "nowcasts": now_info,
                           "l6_part_sha256": L6_PART_SHA256, "l6_state_sha256": L6_STATE_SHA256,
                           "coefficients_sha256": _sha(coefficients)},
                "snapshots": int(len(s)), "covered_l6": int(s["covered_l6"].sum()), "bands": int(len(b)),
                "files": {name: _sha(target / name) for name in (SNAPSHOTS_OUT, BANDS_OUT)},
                "outcome_files_opened": []}
    with open(target / FRAME_MANIFEST, "x", encoding="utf-8") as handle:
        handle.write(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    return manifest


def run(*, day, layout_root, nowcasts, coefficients, frame_root, state, recorder_root, out_root, today=None):
    """The emission path: build the frame, screen it again, then ``l6g_forward_emit.emit_day``."""
    manifest = build(day=day, layout_root=layout_root, nowcasts=nowcasts, coefficients=coefficients,
                     out_dir=frame_root)
    return emit_frame_files(day=manifest["date"], frame_dir=Path(frame_root) / manifest["date"], state=state,
                            recorder_root=recorder_root, out_root=out_root, today=today)


def emit_frame_files(*, day, frame_dir, state, recorder_root, out_root, today=None):
    """Screen an emitter input frame with this module's wider list, then hand it to the emitter."""
    import pandas as pd

    snaps, bands = Path(frame_dir) / SNAPSHOTS_OUT, Path(frame_dir) / BANDS_OUT
    for what, path in (("emitter snapshots", snaps), ("emitter bands", bands)):
        refuse_columns(pd.read_parquet(path).columns, what)
    try:
        return emit.emit_day(day=day, snapshots=snaps, bands=bands, state=state, recorder_root=recorder_root,
                             out_root=out_root, today=today)
    except emit.EmitError as exc:
        raise FrameError(f"emitter refused: {exc}") from exc


def main(argv=None):
    p = argparse.ArgumentParser(prog=f"python -m weather.calibration.{NAME}", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    r = sub.add_parser("run")
    for q in (b, r):
        for flag in ("--date", "--layout-root", "--nowcasts", "--coefficients", "--frame-root"):
            q.add_argument(flag, required=True)
    for flag in ("--state", "--recorder-root", "--out-root"):
        r.add_argument(flag, required=True)
    a = p.parse_args(argv)
    if a.cmd == "build":
        m = build(day=a.date, layout_root=a.layout_root, nowcasts=a.nowcasts, coefficients=a.coefficients,
                  out_dir=a.frame_root)
        print(json.dumps({"date": m["date"], "snapshots": m["snapshots"], "covered_l6": m["covered_l6"]}))
    else:
        rec = run(day=a.date, layout_root=a.layout_root, nowcasts=a.nowcasts, coefficients=a.coefficients,
                  frame_root=a.frame_root, state=a.state, recorder_root=a.recorder_root, out_root=a.out_root)
        print(json.dumps({"date": rec["date"], "snapshots": rec["snapshots"],
                          "coverage": rec["coverage_fraction_covered_and_g"]}))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
