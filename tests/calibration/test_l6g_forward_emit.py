"""Lane L2: the outcome-blind daily L6 / L6_G emitter of the L6_G forward screen, on fabricated data only.

Guards: the emitter refuses a state file off its pinned sha256, a recorder manifest off its schema, date, recorder or
fetch-module pin, a date whose manifest is not written, a date before 2026-10-29 or not yet ended, a second emission
of a date, and any snapshot or band column that could carry a price, label or outcome. Only the LastModified-rule
table sets G (a fetched-rule value is never applied); s = a_h + b_h (G - N) moves only the centre, s = 0 reproduces
L6 exactly, mass is preserved, uncovered snapshots carry equal placeholders, the vectors are the look's input
contract and pass its own controls, and p_l6 equals MG-1 band probabilities at the L6 centre.
"""
import datetime as dt
import hashlib
import json

import numpy as np
import pandas as pd
import pytest

from weather.calibration import l6g_forward_emit as emit
from weather.calibration import l6g_forward_look as look
from weather.reporting.scorecards.free_source_candidates import mg1

DAY = "2026-10-30"
TODAY = dt.date(2026, 10, 31)
EDGES = [(  "lte", 0, 70), ("range", 71, 72), ("range", 73, 74), ("range", 75, 76), ("gte", 77, 0)]


def _inputs(tmp_path, *, uncovered=(), extra_col=None):
    rng = np.random.default_rng(3)
    snaps, bands = [], []
    for mk in look.MARKETS:
        for h in look.HOURS:
            sid = f"{DAY}-{mk}-{h}"
            snaps.append({"snapshot_id": sid, "date": DAY, "market": mk, "local_hour": h,
                          "l6_mu": 73.0 + rng.normal(), "v2_stddev": 1.5 + rng.random(), "v2_mean": 73.0 + rng.normal(),
                          "floor": 60.0 + h, "covered_l6": (mk, h) not in uncovered})
            bands += [{"snapshot_id": sid, "band_index": k, "kind": kd, "low": lo, "high": hi}
                      for k, (kd, lo, hi) in enumerate(EDGES)]
    sf, bf = pd.DataFrame(snaps), pd.DataFrame(bands)
    if extra_col:
        sf[extra_col] = 0.5
    sp, bp = tmp_path / "snaps.parquet", tmp_path / "bands.parquet"
    sf.to_parquet(sp)
    bf.to_parquet(bp)
    return sp, bp


def _manifest(root, day=DAY, *, lm_missing=(), fetched=99.0, **over):
    lm = {mk: {f"h{h:02d}": (None if (mk, h) in lm_missing else 75.0) for h in look.HOURS} for mk in look.MARKETS}
    fr = {mk: {f"h{h:02d}": fetched for h in look.HOURS} for mk in look.MARKETS}
    doc = {"schema": look.RECORDER_SCHEMA, "date": day, "recorder_sha256": emit.RECORDER_SHA256,
           "module_sha256": emit.FETCH_MODULE_SHA256, "ok": 217, look.DECIDING_TABLE: lm, look.REPORTED_TABLE: fr}
    doc.update(over)
    (root / day).mkdir(parents=True, exist_ok=True)
    (root / day / "manifest.json").write_text(json.dumps(doc))


@pytest.fixture
def env(tmp_path, monkeypatch):
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"state": {f"h{h:02d}": {"a": 0.1, "b": 0.2} for h in look.HOURS}}))
    monkeypatch.setattr(look, "STATE_SHA256", hashlib.sha256(state.read_bytes()).hexdigest())
    root = tmp_path / "gefs"
    return {"state": state, "recorder_root": root, "out_root": tmp_path / "ledger", "today": TODAY}


def _emit(env, sp, bp, **over):
    kw = dict(env, day=DAY, snapshots=sp, bands=bp)
    kw.update(over)
    return emit.emit_day(**kw)


def test_emits_shifted_vectors_that_pass_the_look_controls(tmp_path, env):
    sp, bp = _inputs(tmp_path, uncovered={("nyc", 7)})
    _manifest(env["recorder_root"], lm_missing={("austin", 9)})
    r = _emit(env, sp, bp)
    out = pd.read_parquet(env["out_root"] / "vectors" / f"{DAY}.parquet")
    assert tuple(out.columns) == look.VECTOR_COLUMNS and r["snapshots"] == 60 and len(out) == 300
    assert r["per_market"]["austin"]["g_present_lastmodified"] == 5 and r["per_market"]["nyc"]["covered_l6"] == 5
    assert r["recorder"]["fetched_rule_nonnull_cells_reported_only"] == 60 and r["deciding_g_table"] == look.DECIDING_TABLE
    assert r["controls"]["replay_max_abs_diff"] <= emit.REPLAY_TOL and r["controls"]["replay_snapshots"] == 20
    s0 = out[out.snapshot_id == f"{DAY}-austin-9"]
    assert np.array_equal(s0.p_l6.to_numpy(), s0.p_l6g.to_numpy())  # G absent: s = 0 exactly
    moved = out[out.snapshot_id == f"{DAY}-austin-8"]
    assert not np.allclose(moved.p_l6.to_numpy(), moved.p_l6g.to_numpy())
    unc = out[out.snapshot_id == f"{DAY}-nyc-7"]
    assert (~unc.covered_l6).all() and np.allclose(unc.p_l6, 0.2) and np.allclose(unc.p_l6g, 0.2)
    present, _, problems = look.forward_g_presence(env["recorder_root"], [DAY])
    lab = out[["date", "market", "band_index"]].drop_duplicates().assign(y=0)  # look's own controls, dummy labels
    _, voids = look.score(out, lab, present, [DAY])
    assert not problems and not [v for v in voids if "survive" not in v]
    receipts = (env["out_root"] / "input_receipts.jsonl").read_text().splitlines()
    assert len(receipts) == 1 and json.loads(receipts[0])["vectors_sha256"]


def test_p_l6_is_mg1_at_the_l6_centre_and_shift_is_a_plus_b_g_minus_n(tmp_path, env):
    sp, bp = _inputs(tmp_path)
    _manifest(env["recorder_root"])
    _emit(env, sp, bp)
    out = pd.read_parquet(env["out_root"] / "vectors" / f"{DAY}.parquet")
    sn = pd.read_parquet(sp).set_index("snapshot_id").loc[f"{DAY}-miami-10"]
    kind, low, high = zip(*EDGES)
    B = np.floor(sn.floor + 0.5)
    sd = max(sn.v2_stddev, 1.0)
    s = 0.1 + 0.2 * (75.0 - sn.v2_mean)
    got = out[out.snapshot_id == f"{DAY}-miami-10"].sort_values("band_index")
    assert np.allclose(got.p_l6, mg1.band_probs(kind, low, high, B, sn.l6_mu, sd), atol=1e-15)
    assert np.allclose(got.p_l6g, mg1.band_probs(kind, low, high, B, sn.l6_mu + s, sd), atol=1e-15)


def test_fetched_rule_is_never_applied(tmp_path, env):
    sp, bp = _inputs(tmp_path)
    _manifest(env["recorder_root"], lm_missing={("chicago", 11)}, fetched=75.0)
    _emit(env, sp, bp)
    out = pd.read_parquet(env["out_root"] / "vectors" / f"{DAY}.parquet")
    row = out[out.snapshot_id == f"{DAY}-chicago-11"]
    assert not row.g_present.any() and np.array_equal(row.p_l6.to_numpy(), row.p_l6g.to_numpy())


@pytest.mark.parametrize("col", ["p_market_yes", "best_bid", "y", "winner", "label_band", "settled_high",
                                 "actual_high", "outcome"])
def test_refuses_price_label_or_outcome_columns(tmp_path, env, col):
    sp, bp = _inputs(tmp_path, extra_col=col)
    _manifest(env["recorder_root"])
    with pytest.raises(emit.EmitError, match="outcome-blind"):
        _emit(env, sp, bp)
    assert not (env["out_root"] / "vectors").exists()


@pytest.mark.parametrize("over", [{"schema": "other/1"}, {"date": "2026-10-31"}, {"recorder_sha256": "0" * 64},
                                  {"module_sha256": "0" * 64}])
def test_refuses_a_manifest_off_its_pins(tmp_path, env, over):
    sp, bp = _inputs(tmp_path)
    _manifest(env["recorder_root"], **over)
    with pytest.raises(emit.EmitError, match="pinned"):
        _emit(env, sp, bp)


def test_refuses_state_off_its_pin_and_missing_manifest(tmp_path, env, monkeypatch):
    sp, bp = _inputs(tmp_path)
    with pytest.raises(emit.EmitError, match="not written yet"):
        _emit(env, sp, bp)
    _manifest(env["recorder_root"])
    monkeypatch.setattr(look, "STATE_SHA256", "0" * 64)
    with pytest.raises(emit.EmitError, match="state sha256"):
        _emit(env, sp, bp)
    assert not (env["out_root"] / "input_receipts.jsonl").exists()


@pytest.mark.parametrize("day, today, match", [("2026-10-28", TODAY, "never backfilled"),
                                               (DAY, dt.date(2026, 10, 30), "not ended")])
def test_refuses_backfill_and_unfinished_dates(tmp_path, env, day, today, match):
    sp, bp = _inputs(tmp_path)
    _manifest(env["recorder_root"], day=day)
    with pytest.raises(emit.EmitError, match=match):
        _emit(env, sp, bp, day=day, today=today)


def test_one_emission_per_date_and_assemble(tmp_path, env):
    sp, bp = _inputs(tmp_path)
    _manifest(env["recorder_root"])
    _emit(env, sp, bp)
    with pytest.raises(emit.EmitError, match="never rewritten"):
        _emit(env, sp, bp)
    sha = emit.assemble(out_root=env["out_root"], dates=[DAY], out=tmp_path / "all.parquet")
    assert len(sha) == 64 and len(pd.read_parquet(tmp_path / "all.parquet")) == 300
    with pytest.raises(emit.EmitError, match="exists"):
        emit.assemble(out_root=env["out_root"], dates=[DAY], out=tmp_path / "all.parquet")
