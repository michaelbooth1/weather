"""Fixture tests for the L14 rung R-P module (NBH remaining-hours maximum as a 13-16 centre shift).

Guards: weather.calibration.nbh_centre_shift contracts pre-registered in the lane rule_rp.md - the translation
keeps total mass, is the identity at delta 0, moves whole and split buckets by the overlap rule, sends edge mass
to the span ends and floor mass onto F; the (a, b) grid is tie-ordered so (0, 0), the incumbent, wins ties; the
NBH cycle is the newest one with S3 LastModified + 10 min <= t and issue time > t - 12 h; the remaining-hours
maximum needs every local hour t..23:00; x = max(f_rem, F) - A; block bytes are verified against the manifest
and SHA256SUMS.
"""
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

nbh = pytest.importorskip("weather.calibration.nbh_centre_shift")


def test_translation_identity_shift_split_and_mass():
    space = [70, 72, 73, 75]
    dist = {70: 0.1, 72: 0.2, 73: 0.3, 75: 0.4}
    same = nbh.translate(dist, space, 0.0, 60)
    assert same[71] == 0.0 and same[74] == 0.0
    assert all(same[k] == pytest.approx(v, abs=1e-15) for k, v in dist.items())
    up = nbh.translate(dist, space, 1.0, 60)
    assert up[71] == pytest.approx(0.1) and up[73] == pytest.approx(0.2) and up[74] == pytest.approx(0.3)
    assert up[75] == pytest.approx(0.4)  # 75 + 1 is beyond the span: kept on the end integer
    half = nbh.translate({72: 1.0}, space, 0.5, 60)
    assert half[72] == pytest.approx(0.5) and half[73] == pytest.approx(0.5)
    down = nbh.translate(dist, space, -2.0, 60)
    assert down[70] == pytest.approx(0.1 + 0.2) and down[71] == pytest.approx(0.3) and down[73] == pytest.approx(0.4)
    for d in (same, up, half, down):
        assert sum(d.values()) == pytest.approx(1.0, abs=1e-12)


def test_arm_keys_outside_the_space_widen_the_span():
    from weather.calibration import feature_model as fm

    space = [70, 72, 73]
    dist = {69: 0.1, 72: 0.5, 73: 0.2, 74: 0.2}  # R-A kernel keys beyond the market space (clarification RP-2)
    same = nbh.translate(dist, space, 0.0, 60)
    assert min(same) == 69 and max(same) == 74
    assert all(same[k] == pytest.approx(v, abs=1e-15) for k, v in dist.items())
    v = nbh.grid_briers(dist, space, 1.0, 60, 72)
    assert v[nbh.GRID.index((0.0, 0.0))] == pytest.approx(fm.brier_score(dist, 72), abs=1e-12)
    with pytest.raises(nbh.RPError):
        nbh.grid_briers(dist, space, 1.0, 60, 80)


def test_translation_floor_moves_mass_onto_F():
    space = [70, 71, 72, 73, 74]
    out = nbh.translate({72: 0.5, 73: 0.5}, space, -1.0, 72)
    assert out[71] == 0.0 and out[70] == 0.0
    assert out[72] == pytest.approx(1.0)
    above = nbh.translate({72: 1.0}, space, 0.0, 99)  # F beyond the span: onto the top end
    assert above[74] == pytest.approx(1.0)


def test_grid_ties_prefer_the_incumbent():
    assert nbh.GRID[0] == (0.0, 0.0)
    assert len(nbh.GRID) == 21 * 61
    flat = [1.0] * len(nbh.GRID)
    assert nbh.pick_ab(flat)[("a")] == 0.0 and nbh.pick_ab(flat)["b"] == 0.0
    sums = [1.0] * len(nbh.GRID)
    sums[nbh.GRID.index((-0.3, 0.5))] = 0.5
    sums[nbh.GRID.index((0.3, 0.5))] = 0.5
    pick = nbh.pick_ab(sums)
    assert (pick["a"], pick["b"]) == (-0.3, 0.5)


def test_grid_briers_identity_matches_feature_model():
    from weather.calibration import feature_model as fm

    space = [70, 72, 73, 75]
    dist = {70: 0.1, 72: 0.2, 73: 0.3, 75: 0.4}
    v = nbh.grid_briers(dist, space, 2.0, 60, 73)
    assert v[nbh.GRID.index((0.0, 0.0))] == pytest.approx(fm.brier_score(dist, 73), abs=1e-12)
    shifted = nbh.translate(dist, space, 0.4 + 0.25 * 2.0, 60)
    assert v[nbh.GRID.index((0.4, 0.25))] == pytest.approx(fm.brier_score(shifted, 73), abs=1e-12)


def test_feature_x_uses_the_observed_floor():
    assert nbh.feature_x(84.0, 88.0, 86.0) == 2.0
    assert nbh.feature_x(90.0, 85.0, 86.0) == 4.0
    assert nbh.feature_x(None, 85.0, 86.0) is None


def _block(station, issued, temps):
    hours = [(issued + timedelta(hours=i + 1)).hour for i in range(len(temps))]
    lines = [f" {station}    NBM V4.1 NBH GUIDANCE    {issued.month}/{issued.day}/{issued.year}  "
             f"{issued:%H%M} UTC",
             " UTC " + "".join(f"{h:3d}" for h in hours),
             " TMP " + "".join(f"{t:3d}" for t in temps)]
    return ("\n".join(lines) + "\n").encode("ascii")


def _corpus(tmp_path, cycles):
    root = tmp_path / "nbh"
    manifest, sums = [], []
    for issued, lm, temps in cycles:
        rel = f"raw/nbh/{issued:%Y%m%d}/nbh.t{issued:%H}z.blocks"
        data = _block("KATL", issued, temps)
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(data)
        sha = hashlib.sha256(data).hexdigest()
        sums.append(f"{sha}  {rel}")
        manifest.append(json.dumps({
            "product": "nbh", "utc_date": f"{issued:%Y-%m-%d}", "cycle": f"{issued:%H}", "status": "ok",
            "last_modified": lm.strftime("%Y-%m-%dT%H:%M:%S.000Z"), "blocks_file": rel,
            "stations": {"KATL": {"status": "ok", "file_offset": 0, "length": len(data), "sha256": sha}}}))
    (root / "manifest.jsonl").write_text("\n".join(manifest) + "\n", encoding="utf-8")
    (root / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="utf-8")
    return root


def test_nbh_feature_point_in_time_and_window(tmp_path):
    utc = timezone.utc
    c15 = datetime(2023, 8, 15, 15, tzinfo=utc)
    c16 = datetime(2023, 8, 15, 16, tzinfo=utc)
    temps15 = [80 + (i % 7) for i in range(25)]  # valid 16Z .. 16Z+24
    temps16 = [99] * 25
    root = _corpus(tmp_path, [(c15, c15 + timedelta(minutes=50), temps15),
                              (c16, c16 + timedelta(minutes=55), temps16)])  # 16:55 + 10 min > 17:00
    corpus = nbh.NBHCorpus(root, ["KATL"])
    tz = ZoneInfo("America/New_York")
    f_rem, cycle, reason = nbh.nbh_feature(corpus, "KATL", date(2023, 8, 15), 13, tz)  # t = 17:00Z
    assert reason == "ok" and cycle == c15
    window = [temps15[(17 + k) - 16] for k in range(11)]  # 17Z .. 03Z (13:00 .. 23:00 EDT)
    assert f_rem == float(max(window))
    # at 14:00 EDT (18Z) the 16Z cycle is eligible
    f2, cycle2, _ = nbh.nbh_feature(corpus, "KATL", date(2023, 8, 15), 14, tz)
    assert cycle2 == c16 and f2 == 99.0


def test_nbh_feature_missing_cases(tmp_path):
    utc = timezone.utc
    c03 = datetime(2023, 8, 15, 3, tzinfo=utc)
    c17 = datetime(2023, 8, 15, 16, tzinfo=utc)
    root = _corpus(tmp_path, [(c03, c03 + timedelta(minutes=40), [80] * 25),
                              (c17, c17 + timedelta(minutes=40), [80] * 3)])
    corpus = nbh.NBHCorpus(root, ["KATL"])
    tz = ZoneInfo("America/New_York")
    _, _, reason = nbh.nbh_feature(corpus, "KATL", date(2023, 8, 15), 13, tz)
    assert reason == "window_incomplete"  # the 16Z block stops after three columns
    corpus.cycles["KATL"] = [c03]
    _, cycle, reason = nbh.nbh_feature(corpus, "KATL", date(2023, 8, 15), 16, tz)  # t = 20Z; 03Z is > 12 h old
    assert reason == "no_cycle" and cycle is None


def test_corrupt_block_is_refused(tmp_path):
    utc = timezone.utc
    c15 = datetime(2023, 8, 15, 15, tzinfo=utc)
    root = _corpus(tmp_path, [(c15, c15 + timedelta(minutes=50), [80] * 25)])
    path = next((root / "raw").rglob("*.blocks"))
    path.write_bytes(path.read_bytes().replace(b"80", b"81", 1))
    corpus = nbh.NBHCorpus(root, ["KATL"])
    _, _, reason = nbh.nbh_feature(corpus, "KATL", date(2023, 8, 15), 13, ZoneInfo("America/New_York"))
    assert reason == "file_sha256sums_mismatch"


def test_unfinalised_corpus_is_refused(tmp_path):
    (tmp_path / "manifest.jsonl").write_text("", encoding="utf-8")
    with pytest.raises(nbh.RPError):
        nbh.NBHCorpus(tmp_path, ["KATL"])
