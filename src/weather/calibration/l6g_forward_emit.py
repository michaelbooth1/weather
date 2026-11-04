"""Lane L2: the daily, outcome-blind L6 / L6_G vector and receipt emitter of the L6_G forward screen (accrual only).

Pre-registration: ``docs/research/gefs-members-l11-2026-10-26/l6g_forward_prereg_DRAFT.md`` (§1-§3). For one local
date D it reads (1) the frozen (a_h, b_h) state, refused unless its sha256 is the pin; (2) the GEFS forward recorder's
manifest for D, refused unless its schema, date, recorder and fetch-module sha256 are the pins, and of which only the
``g_lastmodified_rule`` table is used (the ``g_fetched_rule`` table is counted for the receipt, never applied);
(3) the L6 arm's as-of-capture snapshot inputs for D (centre ``l6_mu``, ``v2_stddev``, ``v2_mean`` = N, ``floor``,
``covered_l6``) and the bands, from MG-2's bound forward input bundle. It never reads a label, an outcome or a price:
any input column that looks like one is refused, and nothing it writes is derived from an outcome.

Per snapshot: s = a_h + b_h (G - N) where G is present under the LastModified rule and N is finite, else s = 0;
p_l6 = MG-1 band probabilities at mu, p_l6g = the same at mu + s (``mg1.band_probs``, B = floor(floor + 0.5),
sigma = max(v2_stddev, 1)). Snapshots the L6 arm does not cover are written with covered_l6 = False and equal
uniform placeholders in both arms (never scored). Output, both exclusive-create (no overwrite, no backfill):
``<out_root>/vectors/<D>.parquet`` and one appended row in ``<out_root>/input_receipts.jsonl``.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path

from weather.calibration import l6g_forward_look as look

NAME = "l6g_forward_emit"
RECEIPT_SCHEMA = "l6g_forward_input_receipt/1"
RECORDER_SHA256 = "3328e1a0c3421ec3f98e3291cc5d8fddb0d88e835f95e8ae1a3eeff54407afc9"  # gefs_forward_recorder.py
FETCH_MODULE_SHA256 = "c898d94ae10264839cdddab5072b72c7821411acb402e03c262a7106206680a8"  # gefs_member_point_fetch.py
FORWARD_FIRST = dt.date(2026, 10, 29)  # no date before the earliest possible D0 is ever emitted
SNAPSHOT_COLUMNS = ("snapshot_id", "date", "market", "local_hour", "l6_mu", "v2_stddev", "v2_mean", "floor",
                    "covered_l6")
BAND_COLUMNS = ("snapshot_id", "band_index", "kind", "low", "high")
_OUTCOME_MARKERS = ("label", "outcome", "settle", "resolv", "winner", "actual", "brier", "result", "verified")
_OUTCOME_EXACT = ("y", "won", "truth")
REPLAY_TOL = 1e-12
REPLAY_SAMPLE = 20


class EmitError(RuntimeError):
    """A refusal: nothing was written."""


def module_sha256():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def refuse_blind_columns(columns, what):
    """Refuse any column that could carry a price, a quote, a label or an outcome."""
    bad = sorted(c for c in columns
                 if any(k in str(c).lower() for k in look._PRICE_MARKERS + _OUTCOME_MARKERS)
                 or str(c).lower() in _OUTCOME_EXACT)
    if bad:
        raise EmitError(f"{what} carries price/label/outcome columns {bad}; the emitter is outcome-blind")


def load_state(path):
    try:
        return look.load_state(path)
    except look.LookError as exc:
        raise EmitError(str(exc)) from exc


def load_recorder_manifest(root, day):
    """The deciding table {market: {hour: G or None}} for ``day`` and the receipt fields; refused off its pins."""
    path = Path(root) / day / "manifest.json"
    if not path.is_file():
        raise EmitError(f"{day}: the recorder manifest is not written yet (the date is not finished)")
    m = json.loads(path.read_bytes())
    for key, want in (("schema", look.RECORDER_SCHEMA), ("date", day), ("recorder_sha256", RECORDER_SHA256),
                      ("module_sha256", FETCH_MODULE_SHA256)):
        if m.get(key) != want:
            raise EmitError(f"{day}: recorder manifest {key} {m.get(key)!r} != pinned {want!r}")
    deciding = m.get(look.DECIDING_TABLE)
    if not isinstance(deciding, dict):
        raise EmitError(f"{day}: recorder manifest lacks {look.DECIDING_TABLE}")
    g = {(mk, h): deciding.get(mk, {}).get(f"h{h:02d}") for mk in look.MARKETS for h in look.HOURS}
    reported = m.get(look.REPORTED_TABLE, {})
    fetched = sum(reported.get(mk, {}).get(f"h{h:02d}") is not None for mk in look.MARKETS for h in look.HOURS)
    info = {"manifest_sha256": _sha(path), "rows_ok": m.get("ok"), "max_available_utc": m.get("max_available_utc"),
            "parser_version": m.get("schema"), "fetched_rule_nonnull_cells_reported_only": int(fetched)}
    return g, info


def band_vectors(snaps, bands, shift):
    """(p at mu, p at mu + shift) per band row of ``bands``, aligned to it; ``snaps`` indexed by snapshot_id."""
    import numpy as np

    from weather.reporting.scorecards.free_source_candidates import mg1

    i = snaps.index.get_indexer(bands["snapshot_id"])
    mu = snaps["l6_mu"].to_numpy(float)[i]
    sd = np.maximum(snaps["v2_stddev"].to_numpy(float)[i], 1.0)
    floor = snaps["floor"].to_numpy(float)[i]
    B = np.where(np.isfinite(floor), np.floor(floor + 0.5), -np.inf)
    kind, low, high = bands["kind"].to_numpy(), bands["low"].to_numpy(float), bands["high"].to_numpy(float)
    s = np.asarray(shift, float)[i]
    return (np.asarray(mg1.band_probs(kind, low, high, B, mu, sd), float),
            np.asarray(mg1.band_probs(kind, low, high, B, mu + s, sd), float))


def emit_frame(snaps, bands, g_table, state, state_sha256):
    """The day's vector frame (look.VECTOR_COLUMNS) and per-snapshot facts. Pure: no I/O, no clock."""
    import numpy as np
    import pandas as pd

    s = snaps.set_index("snapshot_id", verify_integrity=True)
    hours = s["local_hour"].to_numpy(int)
    g = np.array([np.nan if g_table.get((mk, int(h))) is None else float(g_table[(mk, int(h))])
                  for mk, h in zip(s["market"], hours)])
    n = pd.to_numeric(s["v2_mean"], errors="coerce").to_numpy(float)
    a = np.array([state.get(int(h), (np.nan, np.nan))[0] for h in hours])
    b = np.array([state.get(int(h), (np.nan, np.nan))[1] for h in hours])
    g_present = np.isfinite(g)
    shift = np.where(g_present & np.isfinite(n) & np.isfinite(a) & np.isfinite(b),
                     a + b * np.where(np.isfinite(g) & np.isfinite(n), g - n, 0.0), 0.0)
    covered = s["covered_l6"].astype(bool).to_numpy() & np.isfinite(s["l6_mu"].to_numpy(float)) \
        & np.isfinite(pd.to_numeric(s["v2_stddev"], errors="coerce").to_numpy(float))
    s = s.assign(l6_mu=pd.to_numeric(s["l6_mu"], errors="coerce"), floor=pd.to_numeric(s["floor"], errors="coerce"),
                 v2_stddev=pd.to_numeric(s["v2_stddev"], errors="coerce"))
    bd = bands[bands["snapshot_id"].isin(s.index)].sort_values(["snapshot_id", "band_index"]).reset_index(drop=True)
    p6, pg = band_vectors(s, bd, shift)
    i = s.index.get_indexer(bd["snapshot_id"])
    width = bd.groupby("snapshot_id")["band_index"].transform("size").to_numpy(float)
    cov_b = covered[i]
    p6 = np.where(cov_b, p6, 1.0 / width)
    pg = np.where(cov_b, pg, 1.0 / width)
    out = pd.DataFrame({"date": s["date"].astype(str).str[:10].to_numpy()[i], "market": s["market"].to_numpy()[i],
                        "snapshot_id": bd["snapshot_id"].to_numpy(), "local_hour": hours[i],
                        "band_index": bd["band_index"].to_numpy(int), "p_l6": p6, "p_l6g": pg,
                        "covered_l6": cov_b, "g_present": g_present[i], "state_sha256": state_sha256})
    facts = pd.DataFrame({"market": s["market"].to_numpy(), "local_hour": hours, "covered": covered,
                          "g_present": g_present, "n_present": np.isfinite(n), "shift": shift}, index=s.index)
    return out[list(look.VECTOR_COLUMNS)], facts


def replay_check(snaps, bands, out, facts, sample=REPLAY_SAMPLE):
    """Recompute a fixed (first-by-id) sample snapshot by snapshot and compare both arms; returns max |diff|."""
    import numpy as np

    s = snaps.set_index("snapshot_id")
    ids = sorted(facts.index[facts["covered"]])[:sample]
    worst = 0.0
    for sid in ids:
        bd = bands[bands["snapshot_id"] == sid].sort_values("band_index").reset_index(drop=True)
        one = s.loc[[sid]]
        p6, pg = band_vectors(one, bd, np.array([facts.loc[sid, "shift"]]))
        got = out[out["snapshot_id"] == sid].sort_values("band_index")
        worst = max(worst, float(np.max(np.abs(got["p_l6"].to_numpy() - p6))),
                    float(np.max(np.abs(got["p_l6g"].to_numpy() - pg))))
    return worst, len(ids)


def emit_day(*, day, snapshots, bands, state, recorder_root, out_root, today=None):
    import numpy as np
    import pandas as pd

    day = dt.date.fromisoformat(str(day)).isoformat()
    today = today or dt.date.today()
    if dt.date.fromisoformat(day) < FORWARD_FIRST:
        raise EmitError(f"{day} is before {FORWARD_FIRST}: never backfilled")
    if dt.date.fromisoformat(day) >= today:
        raise EmitError(f"{day} has not ended yet ({today}); emit only finished dates")
    out_root = Path(out_root)
    vec_path = out_root / "vectors" / f"{day}.parquet"
    if vec_path.exists():
        raise EmitError(f"{vec_path} exists: one emission per date, never rewritten")
    state_map = load_state(state)
    state_sha = _sha(state)
    g_table, rec = load_recorder_manifest(recorder_root, day)
    snaps = pd.read_parquet(snapshots)
    bd = pd.read_parquet(bands)
    refuse_blind_columns(snaps.columns, "snapshots")
    refuse_blind_columns(bd.columns, "bands")
    for what, frame, need in (("snapshots", snaps, SNAPSHOT_COLUMNS), ("bands", bd, BAND_COLUMNS)):
        missing = set(need) - set(frame.columns)
        if missing:
            raise EmitError(f"{what} lack {sorted(missing)}")
    snaps = snaps[list(SNAPSHOT_COLUMNS)]
    snaps = snaps[(snaps["date"].astype(str).str[:10] == day) & snaps["market"].isin(look.MARKETS)
                  & snaps["local_hour"].astype(int).isin(look.HOURS)].reset_index(drop=True)
    if snaps.empty:
        raise EmitError(f"{day}: no in-scope snapshots")
    bd = bd[list(BAND_COLUMNS)]
    if not set(snaps["snapshot_id"]) <= set(bd["snapshot_id"]):
        raise EmitError(f"{day}: a snapshot has no bands")
    out, facts = emit_frame(snaps, bd, g_table, state_map, state_sha)
    mass = out.groupby("snapshot_id")[["p_l6", "p_l6g"]].sum().to_numpy()
    mass_err = float(np.max(np.abs(mass - 1.0)))
    off = ~out["g_present"]
    control = float(np.max(np.abs((out.loc[off, "p_l6g"] - out.loc[off, "p_l6"]).to_numpy()), initial=0.0))
    replay, n_replay = replay_check(snaps, bd, out, facts)
    if mass_err > look.MASS_TOL or control > look.CONTROL_TOL or replay > REPLAY_TOL:
        raise EmitError(f"{day}: control failed (mass {mass_err:.3g}, s=0 {control:.3g}, replay {replay:.3g})")
    per_market = {mk: {"snapshots": int(len(f)), "covered_l6": int(f["covered"].sum()),
                       "g_present_lastmodified": int(f["g_present"].sum()),
                       "covered_and_g": int((f["covered"] & f["g_present"]).sum()),
                       "n_present": int(f["n_present"].sum())}
                  for mk, f in facts.groupby("market", sort=True)}
    tot = len(facts)
    vec_path.parent.mkdir(parents=True, exist_ok=True)
    with open(vec_path, "xb") as handle:  # exclusive create
        out.to_parquet(handle, index=False)
    receipt = {"schema": RECEIPT_SCHEMA, "date": day, "emitted_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
               "per_market": per_market, "snapshots": tot,
               "coverage_fraction_covered_and_g": float((facts["covered"] & facts["g_present"]).sum() / tot),
               "recorder": rec, "deciding_g_table": look.DECIDING_TABLE,
               "controls": {"state_sha256_ok": True, "mass_max_abs_err": mass_err, "s0_max_abs_diff": control,
                            "replay_max_abs_diff": replay, "replay_snapshots": n_replay},
               "inputs": {"state_sha256": state_sha, "snapshots_sha256": _sha(snapshots), "bands_sha256": _sha(bands),
                          "module_sha256": module_sha256()},
               "vectors_file": vec_path.name, "vectors_sha256": _sha(vec_path)}
    with open(out_root / "input_receipts.jsonl", "a", encoding="utf-8") as handle:
        handle.write(json.dumps(receipt, sort_keys=True) + "\n")
    return receipt


def assemble(*, out_root, dates, out):
    """Concatenate the emitted per-date vectors of ``dates`` into one look input (no outcome is read)."""
    import pandas as pd

    if Path(out).exists():
        raise EmitError(f"{out} exists")
    frames = []
    for d in dates:
        p = Path(out_root) / "vectors" / f"{d}.parquet"
        if not p.is_file():
            raise EmitError(f"{d}: no emitted vectors")
        frames.append(pd.read_parquet(p))
    with open(out, "xb") as handle:
        pd.concat(frames, ignore_index=True).to_parquet(handle, index=False)
    return _sha(out)


def main(argv=None):
    p = argparse.ArgumentParser(prog=f"python -m weather.calibration.{NAME}", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("emit")
    for flag in ("--date", "--snapshots", "--bands", "--state", "--recorder-root", "--out-root"):
        e.add_argument(flag, required=True)
    a_ = sub.add_parser("assemble")
    for flag in ("--out-root", "--countable-dates", "--out"):
        a_.add_argument(flag, required=True)
    a = p.parse_args(argv)
    if a.cmd == "emit":
        r = emit_day(day=a.date, snapshots=a.snapshots, bands=a.bands, state=a.state, recorder_root=a.recorder_root,
                     out_root=a.out_root)
        print(json.dumps({"date": r["date"], "snapshots": r["snapshots"],
                          "coverage": r["coverage_fraction_covered_and_g"]}))
    else:
        dates = [x.strip() for x in Path(a.countable_dates).read_text(encoding="utf-8").splitlines() if x.strip()]
        print(assemble(out_root=a.out_root, dates=dates, out=a.out))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
