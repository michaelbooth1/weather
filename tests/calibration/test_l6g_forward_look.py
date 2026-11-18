"""Lane L2: the single look of the L6_G forward screen, on fabricated data only.

Guards: the look refuses before 2026-12-13 or before the 45th date has passed, without MG-1's or B's look receipt,
with an existing receipt (single look, also enforced by exclusive create), with a D0 after 2026-11-02, with other than
45 countable dates, with a state file off its pinned sha256, and with any price/market column in its inputs; every
refusal comes before the label file is opened. Only the recorder's LastModified-rule table decides G presence (the
fetched-rule table is counted and reported only); vector G presence must match it; L6_G must equal L6 where G is
absent and mass must be preserved, else VOID; dates under 90% coverage are dropped and fewer than 40 survivors is
VOID; an informative shift gives PASS and a harmful one FAIL.
"""
import datetime as dt
import hashlib
import json

import numpy as np
import pandas as pd
import pytest

from weather.calibration import l6g_forward_look as look

from tests.host_guard import import_or_skip_on_capture_host

# The look's interval code imports r0_ols_floor_challenger, which refuses the capture host by design.
import_or_skip_on_capture_host("weather.calibration.r0_ols_floor_challenger")

D0 = dt.date(2026, 10, 30)
DATES = [(D0 + dt.timedelta(days=k)).isoformat() for k in range(45)]
TODAY = dt.date(2026, 12, 20)


def _fabricate(tmp_path, *, gain=0.1, fetched=None, lm_missing=(), seed=5):
    rng = np.random.default_rng(seed)
    rows, labels = [], []
    for d in DATES:
        for m in look.MARKETS:
            y = int(rng.integers(0, 3))
            labels += [{"date": d, "market": m, "band_index": b, "y": int(b == y)} for b in range(3)]
            for h in look.HOURS:
                base = rng.dirichlet(np.ones(3))
                onehot = np.eye(3)[y]
                g_ok = (d, m) not in lm_missing
                shifted = (1 - gain) * base + gain * onehot if gain >= 0 else (1 + gain) * base - gain * \
                    np.roll(onehot, 1)
                p_g = shifted if g_ok else base
                for b in range(3):
                    rows.append({"date": d, "market": m, "snapshot_id": f"{d}-{m}-{h}", "local_hour": h,
                                 "band_index": b, "p_l6": base[b], "p_l6g": p_g[b], "covered_l6": True,
                                 "g_present": g_ok, "state_sha256": look.STATE_SHA256})
    vec, lab = tmp_path / "vectors.parquet", tmp_path / "labels.parquet"
    pd.DataFrame(rows).to_parquet(vec)
    pd.DataFrame(labels).to_parquet(lab)
    root = tmp_path / "gefs"
    for d in DATES:
        (root / d).mkdir(parents=True)
        lm = {m: {f"h{h:02d}": (None if (d, m) in lm_missing else 80.0) for h in look.HOURS} for m in look.MARKETS}
        fr = {m: {f"h{h:02d}": fetched for h in look.HOURS} for m in look.MARKETS}
        (root / d / "manifest.json").write_text(json.dumps({"schema": look.RECORDER_SCHEMA, "date": d,
                                                            look.DECIDING_TABLE: lm, look.REPORTED_TABLE: fr}))
    return vec, lab, root


@pytest.fixture
def env(tmp_path, monkeypatch):
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"state": {f"h{h:02d}": {"a": 0.1, "b": 0.2} for h in look.HOURS}}))
    sha = hashlib.sha256(state.read_bytes()).hexdigest()
    monkeypatch.setattr(look, "STATE_SHA256", sha)
    for name in ("mg1.json", "b.json"):
        (tmp_path / name).write_text("{}")
    return {"state": state, "mg1_look_receipt": tmp_path / "mg1.json", "b_look_receipt": tmp_path / "b.json",
            "out": tmp_path / "look_receipt.json", "countable_dates": DATES, "today": TODAY}


def _run(env, vec, lab, root, **over):
    kw = dict(env, vectors=vec, labels=lab, recorder_root=root)
    kw.update(over)
    return look.run_look(**kw)


def test_informative_shift_passes_and_writes_one_receipt(tmp_path, env):
    vec, lab, root = _fabricate(tmp_path, gain=0.1)
    receipt = _run(env, vec, lab, root)
    r = receipt["result"]
    assert r["verdict"] == "PASS" and r["primary_07_12"]["ci95"][1] < 0 and r["surviving_dates"] == 45
    assert r["primary_07_12"]["n_cells"] == 450 and len(r["hours"]) == 6
    assert receipt["deciding_g_table"] == "g_lastmodified_rule"
    assert json.loads(env["out"].read_text())["result"]["verdict"] == "PASS"
    with pytest.raises(look.LookError, match="single look"):
        _run(env, vec, lab, root)


def test_harmful_shift_fails(tmp_path, env):
    vec, lab, root = _fabricate(tmp_path, gain=-0.1)
    assert _run(env, vec, lab, root)["result"]["verdict"] == "FAIL"


@pytest.mark.parametrize("over, match", [
    ({"today": dt.date(2026, 12, 12)}, "no look before"),
    ({"countable_dates": DATES[:44]}, "exactly 45"),
    ({"countable_dates": [(dt.date(2026, 11, 3) + dt.timedelta(days=k)).isoformat() for k in range(45)],
      "today": dt.date(2027, 1, 30)}, "after the cap"),
])
def test_guards_refuse_before_labels_are_read(tmp_path, env, over, match):
    vec, _, root = _fabricate(tmp_path)
    with pytest.raises(look.LookError, match=match):
        _run(env, vec, tmp_path / "no_labels_here.parquet", root, **over)
    assert not env["out"].exists()


@pytest.mark.parametrize("receipt", ["mg1_look_receipt", "b_look_receipt"])
def test_refuses_without_mg1_or_b_look_receipt(tmp_path, env, receipt):
    vec, _, root = _fabricate(tmp_path)
    env[receipt].unlink()
    with pytest.raises(look.LookError, match="strictly after"):
        _run(env, vec, tmp_path / "no_labels_here.parquet", root)


def test_refuses_state_off_its_pin_and_price_columns(tmp_path, env, monkeypatch):
    vec, lab, root = _fabricate(tmp_path)
    monkeypatch.setattr(look, "STATE_SHA256", "0" * 64)
    with pytest.raises(look.LookError, match="state sha256"):
        _run(env, vec, tmp_path / "no_labels_here.parquet", root)
    monkeypatch.setattr(look, "STATE_SHA256", hashlib.sha256(env["state"].read_bytes()).hexdigest())
    frame = pd.read_parquet(vec)
    frame["p_market_yes"] = 0.5
    frame.to_parquet(vec)
    with pytest.raises(look.LookError, match="never reads a price"):
        _run(env, vec, tmp_path / "no_labels_here.parquet", root)


def test_fetched_rule_table_never_decides(tmp_path, env):
    vec, lab, root = _fabricate(tmp_path, fetched=None)  # fetched rule all missing: no effect on the decision
    receipt = _run(env, vec, lab, root)
    assert receipt["result"]["verdict"] == "PASS" and receipt["reported_only"]["fetched_rule_nonnull_cells"] == 0
    assert receipt["result"]["surviving_dates"] == 45


def test_vector_g_must_match_the_lastmodified_table(tmp_path, env):
    vec, lab, root = _fabricate(tmp_path)
    m = json.loads((root / DATES[3] / "manifest.json").read_text())
    m[look.DECIDING_TABLE]["austin"]["h09"] = None  # the deciding table says absent; the vectors say present
    m[look.REPORTED_TABLE]["austin"]["h09"] = 80.0  # a present fetched-rule value cannot rescue it
    (root / DATES[3] / "manifest.json").write_text(json.dumps(m))
    r = _run(env, vec, lab, root)
    assert r["result"]["verdict"] == "VOID" and any("LastModified" in v for v in r["void_conditions"])


def test_positive_control_and_mass(tmp_path, env):
    vec, lab, root = _fabricate(tmp_path, lm_missing={(DATES[0], "nyc")})
    frame = pd.read_parquet(vec)
    off = (frame["date"] == DATES[0]) & (frame["market"] == "nyc")
    frame.loc[off & (frame["band_index"] == 0), "p_l6g"] += 0.01  # s != 0 where G is absent, and mass broken
    frame.to_parquet(vec)
    r = _run(env, vec, lab, root)
    assert r["result"]["verdict"] == "VOID"
    assert any("positive control" in v for v in r["void_conditions"]) and any("mass" in v for v in r["void_conditions"])


def test_coverage_drop_and_void_floor(tmp_path, env):
    low = {(d, m) for d in DATES[:6] for m in look.MARKETS[:2]}  # 6 dates at 80% coverage: dropped, 39 survive
    vec, lab, root = _fabricate(tmp_path, lm_missing=low)
    r = _run(env, vec, lab, root)
    assert r["result"]["dropped_dates"] == DATES[:6] and r["result"]["surviving_dates"] == 39
    assert r["result"]["verdict"] == "VOID" and any("survive" in v for v in r["void_conditions"])


def test_decide_rule():
    hours = [{"ci95": [-0.02, 0.01]}] * 6
    assert look.decide({"ci95": [-0.02, -0.001]}, hours) == "PASS"
    assert look.decide({"ci95": [-0.02, -0.001]}, hours[:5] + [{"ci95": [0.001, 0.02]}]) == "INCONCLUSIVE"
    assert look.decide({"ci95": [0.001, 0.02]}, hours) == "FAIL"
    assert look.decide({"ci95": [-0.01, 0.01]}, hours) == "INCONCLUSIVE"
