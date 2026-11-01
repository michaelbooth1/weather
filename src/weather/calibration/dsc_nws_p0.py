r"""DSC-NWS market-residual P0 at 07-12 (ruling R28a, lane L40, 2026-11-01; rule ``RULE_SHA256``).

Frozen rule ``docs/research/dsc-nws-p0-2026-11-01/rule_dsc_nws_p0.md`` (sha256 ``aaa8d5f3…``, freeze commit
``95b1c19fc7fb07de5f5b48ffd9b0c01da58b24b9``). Three arms (K = 3) on the dev scorecard layout, block 07-12, scored
2026-08-15..09-29; nothing later is read.

``stage1`` (outcome-free; rule section 5.3): verifies and reads ONLY ``inputs_snapshots``, ``inputs_bands`` and
``market`` from the layout (``labels.parquet`` is never opened), extracts ``nws_grid`` and the ``metar`` receipt
from the captured replay inputs by the S0 rules (each replay file read is checked against SHA256SUMS), joins the
L6 OWN nowcast by sha, builds the arm values and populations, and runs C0 (S0 parity). Writes
``stage1_arms.parquet`` and ``stage1.json`` (exclusive create). A C0 miss refuses.

``stage2``: requires the Stage 1 receipt sha, refuses a second look (exclusive marker), attaches the labels
(``mr_gate.build_tables``), checks parity with Stage 1, runs C1/C2 (``mr_gate.market_controls``), C3
(``w0_identity`` per arm), C5 (planted edge-reach control per arm), ``mr_sweep.p0_candidate`` per arm, the wider
(date-clustered + circular block-3) interval, the power gate, BH and the section 5.1 verdicts; the w gate for
survivors only. Writes ``stage2.json`` and ``stage2_rows.jsonl`` (exclusive create).

    python -m weather.calibration.loyo_screen dsc-nws-p0 stage1 --layout C:/swarm/v3layout --out <dir>
    python -m weather.calibration.loyo_screen dsc-nws-p0 stage2 --layout C:/swarm/v3layout --stage1 <dir> \
        --stage1-sha <sha256 of stage1.json> --out <dir>

Research only: offline, read-only inputs, no network, outputs outside the repository.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import re
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from weather.calibration import loyo_screen as ls
from weather.calibration import mr_gate as mg
from weather.calibration import mr_sweep as sw

SCHEMA = "dsc_nws_p0/1"
GATE = "DSC-NWS-P0"
RULE_SHA256 = "aaa8d5f36404d721d97984fb74afcb51cf1ef58233ad76476c62665ba1f0fe86"
RULE_PATH = "docs/research/dsc-nws-p0-2026-11-01/rule_dsc_nws_p0.md"
FREEZE_COMMIT = "95b1c19fc7fb07de5f5b48ffd9b0c01da58b24b9"
RUN_ENV_PIN = "8bb0f9563582885c4d01d34b67476f2563260e43"
LAYOUT_MANIFEST_SHA256 = "4d53fdbdc551f33e331fa3b51cc425e354eec4426c8c7b52910b2e7340915f22"
REPLAY_SUMS_SHA256 = "d9c2ed46a72442c68deb6f6b36784fcf081edc52e2a0d8f024cd6cc1a5a38b82"
NOWCAST_SHA256 = "3806687cd6ad8d38571fd5d17efa5405856300d2f0029ae644e3ad08db4a31f3"
DEFAULT_NOWCAST = r"C:\t\l3\l6cap\nowcasts.parquet"
DEFAULT_REPLAY = sw.DEFAULT_REPLAY
# git blob ids of the imported machinery at the pins named by the rule (sections 5 and 7)
PINNED_BLOBS = {"mr_sweep": "f49e38184d62264f9684922b02b4ca2e8923781b",
                "mr_gate": "153dd07c12cd20ca079cb4ee9647f9fce99e40e7",
                "market_blend": "4a35e35b04cab11b27dc33c68fc8b85c4b084337",
                "c3_kill_tier": "8f4f9d194dc62cb4cd481e20005ce6ae75d1f879"}
LAST = "2026-09-29"
HOURS = (7, 12)
BLOCK = "07-12"
EDGE = 0.2236           # rule 5.1: sqrt(0.05) as written in the rule
Z = 1.96                # rule 5.1: Phi(0.2236 / SE_wider - 1.96)
POWER_MIN = 0.5
SYN_SHRINK = 0.75       # rule 5.2 C5: s = 0.75, frozen
SYN_SEED = 20261101
SIGMA_FLOOR_NM = 0.25   # W1: ln max(|n - v|, 0.25)
ARMS = (("W1-0712", "S", 1), ("NWS-FADE-0712", "D", -1), ("NWS-GAP-0712", "D", 1))
C0_EXPECTED = {"W1-0712": {"fit_covered": 23729, "scored_covered": 17896, "population_snapshots": 9432,
                           "population_dates": 43},
               "NWS-FADE-0712": {"fit_covered": 28796, "scored_covered": 21693, "population_snapshots": 21391,
                                 "population_dates": 43},
               "NWS-GAP-0712": {"fit_covered": 28796, "scored_covered": 21693, "population_snapshots": 21391,
                                "population_dates": 43}}
C0_RHO_GAP_FADE = -0.49003
C0_RHO_TOL = 1e-4
SLUG = re.compile(r"^highest-temperature-in-(?P<market>.+)-on-(?P<mon>[a-z]+)-(?P<day>\d+)-(?P<year>\d{4})$")
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                       "september", "october", "november", "december"], 1)}
STAGE1_PARQUET, STAGE1_RECEIPT = "stage1_arms.parquet", "stage1.json"
STAGE2_RECEIPT, STAGE2_ROWS, LOOK_MARKER = "stage2.json", "stage2_rows.jsonl", "stage2_look.json"
LABEL_UNTESTABLE = "UNTESTABLE (coverage)"
LABEL_UNTESTABLE_C5 = "UNTESTABLE at edge (C5)"
LABEL_UNTESTABLE_POWER = "UNTESTABLE at edge (power)"
LABEL_KILL = "KILL at edge"
LABEL_SURVIVOR = "SURVIVOR"
LABEL_INCONCLUSIVE = "INCONCLUSIVE"


class DscError(mg.GateError):
    pass


# ----------------------------------------------------------------------------- small helpers

def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def git_blob(path):
    data = Path(path).read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def write_exclusive(path, text):
    with open(path, "x", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def check_out_dir(out):
    out = Path(out)
    if out.exists():
        raise DscError(f"refused: output directory {out} already exists (one run only)")
    repo = Path(ls.__file__).resolve().parents[3]
    if out.resolve().is_relative_to(repo):
        raise DscError("refused: outputs must lie outside the repository")
    return out


def check_machinery():
    """The imported machinery is byte-identical to the pins (git blob ids) and the rule file is the frozen one."""
    from weather.calibration import c3_kill_tier as c3
    from weather.calibration import market_blend as mb

    files = {"mr_sweep": sw.__file__, "mr_gate": mg.__file__, "market_blend": mb.__file__, "c3_kill_tier": c3.__file__}
    blobs = {k: git_blob(v) for k, v in files.items()}
    bad = {k: v for k, v in blobs.items() if v != PINNED_BLOBS[k]}
    if bad:
        raise DscError(f"refused: imported machinery differs from the pins: {bad}")
    rule = Path(ls.__file__).resolve().parents[3] / RULE_PATH
    rule_sha = sha256_bytes(rule.read_bytes()) if rule.exists() else None
    if rule_sha != RULE_SHA256:
        raise DscError(f"refused: rule file sha {rule_sha} != frozen {RULE_SHA256}")
    return {"git_blobs": blobs, "rule_sha256": rule_sha, "driver_sha256": ls.sha256_file(__file__),
            "driver_git_blob": git_blob(__file__)}


def _hash(arr):
    a = np.ascontiguousarray(np.asarray(arr))
    if a.dtype == object:
        return sha256_bytes("\n".join(map(str, a.tolist())).encode("utf-8"))
    return sha256_bytes(a.tobytes())


def spearman(a, b):
    ok = np.isfinite(a) & np.isfinite(b)
    if ok.sum() < 3:
        return None, int(ok.sum())
    return float(pd.Series(a[ok]).rank().corr(pd.Series(b[ok]).rank())), int(ok.sum())


# ----------------------------------------------------------------------------- label-free tables (stage 1)

class LabelFreeTable:
    """``dev_scorecard.Table``'s snapshot / band / market alignment, built without any label (no ``y``)."""

    def __init__(self, snaps_all, bands_all, market_all, dates):
        keep = snaps_all.date.astype(str).isin(dates)
        self.snaps = snaps_all[keep].reset_index(drop=True)
        keys = set(self.snaps.row_key)
        self.bands = bands_all[bands_all.row_key.isin(keys)].reset_index(drop=True)
        self.n = self.snaps.n_bands.to_numpy(int)
        self.offsets = np.concatenate([[0], np.cumsum(self.n)[:-1]]).astype(int)
        self.band_snap = np.repeat(np.arange(len(self.snaps)), self.n)
        self.snap_pos = pd.Series(np.arange(len(self.snaps)), index=self.snaps.row_key.to_numpy())
        market = market_all.set_index(["row_key", "band_index"]).p_market_yes
        self.p_market = market.reindex(pd.MultiIndex.from_arrays(
            [self.bands.row_key, self.bands.band_index])).to_numpy(float)
        if np.isnan(self.p_market).any():
            raise DscError(f"{int(np.isnan(self.p_market).sum())} bands have no market price")
        self.local_hour = self.snaps.local_hour.to_numpy(int)
        self.markets = self.snaps.market.astype(str).to_numpy()


def label_free_tables(layout):
    """``mr_gate.build_tables`` without the labels: the same files (manifest-verified), dates and folds."""
    from weather.calibration import market_blend as mb
    from weather.reporting.scorecards import dev_scorecard_data as data
    from weather.reporting.scorecards import loss_atlas as la

    la.screen_input_path(layout, "layout")
    start, end = data.check_range(*mb.RANGE)
    manifest, manifest_sha = data._read_manifest(layout)
    data._guard_manifest_dates(manifest)
    frames, shas = {}, {}
    for name in (data.SNAPSHOTS_FILE, data.BANDS_FILE, data.MARKET_FILE):  # labels.parquet is never opened
        frame, shas[name] = data._read_verified(layout, name, manifest)
        frames[name] = data._in_range(frame, data.DEV_FIRST, end, name)
    snaps, bands = frames[data.SNAPSHOTS_FILE], frames[data.BANDS_FILE]
    leaked = data.LABELISH & (set(snaps.columns) | set(bands.columns))
    if leaked:
        raise DscError(f"layout inputs carry label columns {sorted(leaked)}")
    if snaps.row_key.duplicated().any():
        raise DscError("duplicate row_key in inputs_snapshots")
    n = snaps.n_bands.to_numpy(int)
    offsets = np.concatenate([[0], np.cumsum(n)[:-1]]).astype(int)
    if len(bands) != int(n.sum()) or (len(snaps) and not (
            bands.row_key.to_numpy()[offsets] == snaps.row_key.to_numpy()).all()):
        raise DscError("inputs_bands is not contiguous per snapshot in snapshot order")
    dates = sorted(snaps.date.astype(str).unique())
    folds = data.make_folds(dates, start, end, 7, 1, 7)
    scored = sorted(d for f in folds if f.scored for d in f.dates)
    burn = [d for d in dates if d <= mb.BURN_IN[1]]
    if not burn or burn[-1] >= scored[0] or scored[-1] > LAST:
        raise DscError("burn-in must precede the scored dates, and nothing may be scored after 2026-09-29")
    fit_t = LabelFreeTable(snaps, bands, frames[data.MARKET_FILE], burn + scored)
    score_t = LabelFreeTable(snaps, bands, frames[data.MARKET_FILE], scored)
    return {"manifest_sha256": manifest_sha, "file_sha256": shas, "burn": burn, "scored": scored}, fit_t, score_t


# ----------------------------------------------------------------------------- replay extraction (S0 rules)

def _num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return math.nan
    return x if math.isfinite(x) else math.nan


def head_value(line, key):
    head = line[:line.find('"sources":')] if '"sources":' in line else line
    at = head.find(f'"{key}":')
    if at < 0:
        return None
    pos = at + len(key) + 3
    while head[pos] == " ":
        pos += 1
    return json.JSONDecoder().raw_decode(head, pos)[0]


def record_fields(rec):
    """``extract_s0.py`` (c70dee7b) nws_grid fields and ``extract_metar_v1.py`` (188dab67) metar receipt fields."""
    src = rec.get("sources") or {}
    g = src.get("nws_grid") or {}
    d = g.get("data") or {}
    rows = d.get("day_rows") or []
    mx = [_num(r.get("max_temp_native")) for r in rows if "max_temp_native" in r]
    mx_f = [x for x in mx if not math.isnan(x)]
    m = src.get("metar") or {}
    md = m.get("data") or {}
    return {"nws_present": bool(g), "nws_ok": g.get("ok") is True, "nws_fetched_at": g.get("fetched_at"),
            "nws_stale": g.get("stale"), "nws_cache_status": g.get("cache_status"),
            "nws_maxt_rows": len(mx), "nws_maxt_finite": len(mx_f), "nws_max": max(mx_f) if mx_f else math.nan,
            "metar_present": bool(m), "metar_ok": m.get("ok") is True, "metar_fetched_at": m.get("fetched_at"),
            "metar_report_time": md.get("report_time"), "metar_tdm": md.get("target_date_match")}


def _sums_listing(replay_root):
    path = Path(replay_root) / "SHA256SUMS"
    raw = path.read_bytes()
    if sha256_bytes(raw) != REPLAY_SUMS_SHA256:
        raise DscError(f"refused: replay SHA256SUMS sha {sha256_bytes(raw)} != {REPLAY_SUMS_SHA256}")
    listed = {}
    for line in raw.decode("utf-8").splitlines():
        if line.strip():
            h, rel = line.split(None, 1)
            listed[rel.strip().lstrip("*")] = h
    return listed


def extract_replay(replay_root, snaps):
    """One pass over the replay files of the given (07-12) snapshots' markets; S0 matching and keep-last rule.
    Every file read is hashed and must equal its SHA256SUMS entry. Returns (frame, stats)."""
    listed = _sums_listing(replay_root)
    root = Path(replay_root) / "snapshots"
    wanted = {}
    for mk, sid, rk in zip(snaps.market.astype(str), snaps.snapshot_id.astype(str), snaps.row_key.astype(str)):
        wanted.setdefault(mk, {})[sid] = rk
    out, malformed, folders, lines_read, hashed = [], [], 0, 0, {}
    for folder in sorted(root.iterdir()):
        hit = SLUG.match(folder.name)
        if not hit or hit["market"] not in wanted:
            continue
        tgt = date(int(hit["year"]), MONTHS[hit["mon"]], int(hit["day"])).isoformat()
        if tgt > LAST:
            continue
        f = folder / "replay_inputs.jsonl"
        if not f.exists():
            continue
        rel = f"snapshots/{folder.name}/replay_inputs.jsonl"
        if rel not in listed:
            raise DscError(f"refused: {rel} is not listed in SHA256SUMS")
        folders += 1
        want = wanted[hit["market"]]
        h = hashlib.sha256()
        with f.open("rb") as fh:
            for lineno, raw in enumerate(fh, 1):
                h.update(raw)
                lines_read += 1
                line = raw.decode("utf-8")
                try:
                    sid = head_value(line, "snapshot_id")
                except Exception as exc:  # noqa: BLE001 - a truncated line carries no value (S0 rule)
                    malformed.append({"file": folder.name, "line": lineno, "error": str(exc)[:80]})
                    continue
                rk = want.get(str(sid))
                if rk is None:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError as exc:
                    malformed.append({"file": folder.name, "line": lineno, "error": str(exc)[:80]})
                    continue
                out.append({"row_key": rk, "replay_captured_at_utc": rec.get("captured_at_utc"),
                            "folder_target": tgt, **record_fields(rec)})
        hashed[rel] = h.hexdigest()
        if hashed[rel] != listed[rel]:
            raise DscError(f"refused: {rel} sha256 differs from SHA256SUMS")
    frame = pd.DataFrame(out)
    if frame.empty:
        raise DscError("no replay record matched")
    n_records = len(frame)
    frame = frame.drop_duplicates("row_key", keep="last").reset_index(drop=True)
    return frame, {"folders_read": folders, "lines_read": lines_read, "records_matched": n_records,
                   "row_keys_matched": int(len(frame)), "wanted": int(len(snaps)), "malformed_lines": malformed,
                   "files_hashed": len(hashed), "files_sha256_of_listing": sha256_bytes(
                       json.dumps(hashed, sort_keys=True).encode("utf-8"))}


# ----------------------------------------------------------------------------- arms (rule sections 2-3)

def arm_values(snaps, feats, nowcast, mu):
    """Per arm: values on ``snaps`` (NaN where uncovered), and the input-validity diagnostics."""
    f = feats.set_index("row_key").reindex(snaps.row_key.to_numpy())
    n = nowcast.n_own.reindex(snaps.row_key.to_numpy()).to_numpy(float)
    cap = sw._utc(snaps.captured_at_utc)
    hour = snaps.local_hour.to_numpy(int)
    blk = (hour >= HOURS[0]) & (hour <= HOURS[1])
    nws_rc = sw._utc(f.nws_fetched_at)
    nws_ok = f.nws_ok.fillna(False).to_numpy(bool)
    nws_rc_ok = ~np.isnat(nws_rc) & ~np.isnat(cap) & (nws_rc <= cap)
    nws_max = f.nws_max.to_numpy(float)
    nws_cov = blk & nws_ok & nws_rc_ok & np.isfinite(nws_max)
    v = pd.to_numeric(snaps.v2_mean, errors="coerce").to_numpy(float)
    v_ok = ((snaps.v2_status.astype(str).to_numpy() == "available")
            & (snaps.v2_available_basis.astype(str).to_numpy() == "response_received_at"))
    v_rc = np.where(v_ok, sw._utc(snaps.v2_available_at), np.datetime64("NaT", "ns"))
    v_cov = blk & ~np.isnat(v_rc) & ~np.isnat(cap) & (v_rc <= cap) & np.isfinite(v)
    m_fa, m_rt = sw._utc(f.metar_fetched_at), sw._utc(f.metar_report_time)
    m_ok = f.metar_ok.fillna(False).to_numpy(bool)
    m_tdm = f.metar_tdm.to_numpy(object) == True  # noqa: E712 - strictly the boolean True
    m_fa_ok = ~np.isnat(m_fa) & ~np.isnat(cap) & (m_fa <= cap)
    m_rt_ok = ~np.isnat(m_rt) & ~np.isnat(cap) & (m_rt <= cap)
    metar_rc = m_ok & m_fa_ok & m_rt_ok & m_tdm
    base_w1 = blk & np.isfinite(n) & v_cov
    with np.errstate(invalid="ignore", divide="ignore"):
        values = {
            "W1-0712": np.where(base_w1 & metar_rc, np.log(np.maximum(np.abs(n - v), SIGMA_FLOOR_NM)), np.nan),
            "NWS-FADE-0712": np.where(nws_cov & np.isfinite(mu), nws_max - mu, np.nan),
            "NWS-GAP-0712": np.where(nws_cov & v_cov, v - nws_max, np.nan),
        }
    inputs = pd.DataFrame({"row_key": snaps.row_key.to_numpy(), "nws_max": nws_max, "nws_cov": nws_cov,
                           "v": v, "v_cov": v_cov, "n_own": n, "metar_rc": metar_rc, "blk": blk})
    diag = {"blk_snapshots": int(blk.sum()), "nws_cov": int(nws_cov.sum()), "v_cov": int(v_cov.sum()),
            "n_finite_blk": int((blk & np.isfinite(n)).sum()),
            "w1_before_metar_gate": int(base_w1.sum()),
            "w1_metar_gate_drops": {"any": int((base_w1 & ~metar_rc).sum()), "not_ok": int((base_w1 & ~m_ok).sum()),
                                    "fetched_after_cap": int((base_w1 & ~m_fa_ok).sum()),
                                    "report_after_cap": int((base_w1 & ~m_rt_ok).sum()),
                                    "tdm_not_true": int((base_w1 & ~m_tdm).sum())},
            "nws_stale_true_on_covered": int(np.sum(nws_cov & (f.nws_stale.to_numpy(object) == True))),  # noqa: E712
            "nws_maxt_multi_rows_on_ok": int(np.sum(blk & nws_ok & (f.nws_maxt_rows.fillna(0).to_numpy(float) > 1)))}
    return values, inputs, diag


def donor_ok_mask(fit_t, covered, donors):
    cov_float = np.repeat(covered.astype(float), fit_t.n)
    ok = np.ones(len(fit_t.snaps), bool)
    fails = {}
    for seed in sw.PLACEBO_SEEDS:
        good = np.bincount(fit_t.band_snap, weights=cov_float[donors[seed][0]], minlength=len(fit_t.snaps)) == fit_t.n
        fails[str(seed)] = int((covered & ~good).sum())
        ok &= good
    return ok, fails


def populations(fit_t, score_t, values, donors):
    from weather.calibration import market_blend as mb

    sd = score_t.snaps.date.astype(str).to_numpy()
    out, masks = {}, {}
    for arm, _, _ in ARMS:
        covered = np.isfinite(values[arm])
        dok, fails = donor_ok_mask(fit_t, covered, donors)
        pop_fit = covered & dok
        pop = mb.restrict_snap(fit_t, score_t, pop_fit)
        masks[arm] = pop_fit
        out[arm] = {"fit_covered": int(covered.sum()),
                    "scored_covered": int(mb.restrict_snap(fit_t, score_t, covered).sum()),
                    "population_snapshots": int(pop.sum()), "population_dates": int(len(np.unique(sd[pop]))),
                    "donor_failures_by_seed_max": max(fails.values()), "donor_failures_sum": sum(fails.values())}
    return out, masks


def control_c0(pops, values):
    rho, n = spearman(values["NWS-GAP-0712"], values["NWS-FADE-0712"])
    per_arm = {}
    for arm, exp in C0_EXPECTED.items():
        got = {k: pops[arm][k] for k in exp}
        per_arm[arm] = {"expected": exp, "observed": got, "match": got == exp}
    rho_ok = rho is not None and abs(rho - C0_RHO_GAP_FADE) <= C0_RHO_TOL
    ok = all(v["match"] for v in per_arm.values()) and rho_ok
    return {"per_arm": per_arm, "rho_gap_fade": {"expected": C0_RHO_GAP_FADE, "observed": rho, "n": n,
                                                  "tol": C0_RHO_TOL, "match": bool(rho_ok)},
            "verdict": "PASS" if ok else "FAIL"}


# ----------------------------------------------------------------------------- stage 1

def stage1(*, layout, out_dir, replay_root=DEFAULT_REPLAY, nowcast=DEFAULT_NOWCAST, allow_dirty=False):
    code = ls.require_clean(ls.code_state(), allow_dirty)
    machinery = check_machinery()
    out = check_out_dir(out_dir)
    meta, fit_t, score_t = label_free_tables(layout)
    if meta["manifest_sha256"] != LAYOUT_MANIFEST_SHA256:
        raise DscError(f"refused: layout manifest sha {meta['manifest_sha256']} != {LAYOUT_MANIFEST_SHA256}")
    if fit_t.snaps.date.astype(str).max() > LAST:
        raise DscError("refused: a fit snapshot is dated after 2026-09-29")
    if set(fit_t.markets) & {"toronto"}:
        raise DscError("the population is the US markets; toronto is not in the rule")
    nc_bytes = Path(nowcast).read_bytes()
    if sha256_bytes(nc_bytes) != NOWCAST_SHA256:
        raise DscError(f"refused: nowcast sha {sha256_bytes(nc_bytes)} != {NOWCAST_SHA256}")
    nc = pd.read_parquet(io.BytesIO(nc_bytes))
    if nc.row_key.duplicated().any():
        raise DscError("duplicate row_key in the nowcast parquet")
    nc = nc.set_index("row_key")

    snaps = fit_t.snaps
    blk = (fit_t.local_hour >= HOURS[0]) & (fit_t.local_hour <= HOURS[1])
    feats, ex_stats = extract_replay(replay_root, snaps[blk])
    geo = sw.band_geometry(fit_t)
    values, inputs, diag = arm_values(snaps, feats, nc, geo["mu"])
    donors = {seed: sw.donor_positions(fit_t, seed) for seed in sw.PLACEBO_SEEDS}
    pops, masks = populations(fit_t, score_t, values, donors)
    c0 = control_c0(pops, values)

    frame = inputs.assign(market=fit_t.markets, date=snaps.date.astype(str).to_numpy(), local_hour=fit_t.local_hour,
                          captured_at_utc=snaps.captured_at_utc.astype(str).to_numpy(),
                          mu_m=geo["mu"], var_m=geo["var"])
    for arm, _, _ in ARMS:
        frame[f"value__{arm}"] = values[arm]
        frame[f"pop_fit__{arm}"] = masks[arm]
    out.mkdir(parents=True)
    buf = io.BytesIO()
    frame.to_parquet(buf, index=False)
    with open(out / STAGE1_PARQUET, "xb") as fh:
        fh.write(buf.getvalue())
    receipt = {"schema": SCHEMA, "gate": GATE, "stage": "stage1", "rule_sha256": RULE_SHA256,
               "freeze_commit": FREEZE_COMMIT, "run_env_pin": RUN_ENV_PIN, "code": code, "machinery": machinery,
               "evidence_class": "development (dev window, provisional)", "labels_opened": False,
               "layout": {"path": str(layout), **meta}, "replay_sha256sums_sha256": REPLAY_SUMS_SHA256,
               "nowcast_sha256": NOWCAST_SHA256, "extraction": ex_stats, "inputs": diag,
               "table_parity": {"row_key_sha256": _hash(snaps.row_key.astype(str).to_numpy()),
                                "n_sha256": _hash(fit_t.n), "p_market_sha256": _hash(fit_t.p_market),
                                "score_row_key_sha256": _hash(score_t.snaps.row_key.astype(str).to_numpy()),
                                "fit_snapshots": int(len(snaps)), "score_snapshots": int(len(score_t.snaps))},
               "populations": pops, "c0": c0,
               "stage1_parquet_sha256": sha256_bytes(buf.getvalue())}
    write_exclusive(out / STAGE1_RECEIPT, json.dumps(receipt, indent=1, sort_keys=True, default=mg._default))
    receipt["stage1_receipt_sha256"] = ls.sha256_file(out / STAGE1_RECEIPT)
    if c0["verdict"] != "PASS":
        raise DscError(f"refused: C0 failed {json.dumps(c0, default=mg._default)}")
    return receipt


# ----------------------------------------------------------------------------- stage 2 statistics

def _delta_sd(sums_c, sums_pl, counts):
    """SD (ddof 1) of the paired Delta replicates (rodc d4ebc9576 ``_delta_sd``)."""
    rho_c = mg._rho(*(counts @ sums_c.T).T)
    j_b = np.arange(len(counts)) % len(sums_pl)
    pl = np.empty(len(counts))
    for j, s in enumerate(sums_pl):
        pl[j_b == j] = mg._rho(*(counts[j_b == j] @ s.T).T)
    d = rho_c - pl
    d = d[np.isfinite(d)]
    return float(np.std(d, ddof=1)) if len(d) > 1 else None


def wider_interval(sums_c, sums_pl, dc_counts):
    """Date-clustered (``p0_candidate``'s 10,000 draws over every score date) and REV-2 circular block-3
    (``c3_kill_tier.block_counts``, 2,000 draws, seed 20261024, over the PRESENT dates in order) intervals of Delta;
    lower = min, upper = max, SE = the larger bootstrap SD (ddof 1); power = Phi(0.2236 / SE - 1.96)."""
    from weather.calibration import c3_kill_tier as c3

    dc = sw.paired_delta(sums_c, sums_pl, dc_counts)
    present = sums_c[0] > 0
    sc_p, sp_p = sums_c[:, present], [s[:, present] for s in sums_pl]
    b3_counts = c3.block_counts(int(present.sum()))
    b3 = sw.paired_delta(sc_p, sp_p, b3_counts)
    se_dc, se_b3 = _delta_sd(sums_c, sums_pl, dc_counts), _delta_sd(sc_p, sp_p, b3_counts)
    lo = None if None in (dc["ci95"][0], b3["ci95"][0]) else min(dc["ci95"][0], b3["ci95"][0])
    hi = None if None in (dc["ci95"][1], b3["ci95"][1]) else max(dc["ci95"][1], b3["ci95"][1])
    se = None if None in (se_dc, se_b3) else max(se_dc, se_b3)
    pw = None if not se or se <= 0 else 0.5 * (1.0 + math.erf((EDGE / se - Z) / math.sqrt(2.0)))
    return {"delta": dc["delta"], "p_one_sided": dc["p_one_sided"], "ci95_date_clustered": dc["ci95"],
            "ci95_block3": b3["ci95"], "ci95_wider": [lo, hi], "se_date_clustered": se_dc, "se_block3": se_b3,
            "se_wider": se, "power_at_edge": pw, "power_at_edge_c3": c3.power_at(c3.DELTA_EDGE, se),
            "p_one_sided_block3": b3["p_one_sided"], "present_dates": int(present.sum()),
            "valid_draws_dc": dc["valid_draws"], "valid_draws_block3": b3["valid_draws"],
            "rho_c": dc["rho_c"], "rho_pl_mean": dc["rho_pl_mean"], "rho_pl_by_seed": dc["rho_pl_by_seed"]}


def sums_for_vector(c_fit, covered, fit_t, score_t, score_dates, donors):
    """``p0_candidate`` from the placebo step on, for a given band vector and its snapshot coverage."""
    from weather.calibration import market_blend as mb

    placebos = [sw.disagreement_placebo(fit_t, c_fit, seed, donors[seed])[0] for seed in sw.PLACEBO_SEEDS]
    dok, _ = donor_ok_mask(fit_t, covered, donors)
    pop = mb.restrict_snap(fit_t, score_t, covered & dok)
    band = pop[score_t.band_snap]
    m = score_t.p_market
    e = score_t.y - m
    didx = np.searchsorted(score_dates, score_t.snaps.date.astype(str).to_numpy())[score_t.band_snap]
    c = mb.restrict(fit_t, score_t, c_fit)
    nd = len(score_dates)
    sums_c = sw.date_sums((c - m)[band], e[band], didx[band], nd)
    sums_pl = [sw.date_sums((mb.restrict(fit_t, score_t, p) - m)[band], e[band], didx[band], nd) for p in placebos]
    return sums_c, sums_pl, int(pop.sum()), int((sums_c[0] > 0).sum())


def planted(fit_t, geo, mask, sign, seed=SYN_SEED):
    """C5 CONTROL only (rule 5.2): Gaussian bands centred at mu_m + sign * 0.75 * (y_mid - mu_m) + eps, width
    sigma_m, eps ~ N(0, sd(y_mid - mu_m)) over the arm's covered fit snapshots (same eps for both signs); clipped
    to [EPS, 1], impossible bands 0, renormalised to sum(m) (row 94's single-member log pool)."""
    from scipy.stats import norm

    from weather.calibration import market_blend as mb

    ny = np.bincount(fit_t.band_snap, weights=fit_t.y, minlength=len(fit_t.snaps))
    zy = np.bincount(fit_t.band_snap, weights=fit_t.y * geo["z"], minlength=len(fit_t.snaps))
    with np.errstate(invalid="ignore", divide="ignore"):
        y_mid = np.where(ny > 0, zy / ny, np.nan)
    gap = y_mid - geo["mu"]
    ok = np.asarray(mask, bool) & np.isfinite(gap)
    sd = float(np.std(gap[ok])) if ok.any() else 1.0
    eps = np.random.default_rng(seed).normal(0.0, sd if sd > 0 else 1.0, len(gap))
    centre = geo["mu"] + sign * SYN_SHRINK * np.where(ok, gap, 0.0) + eps
    sig = np.sqrt(geo["var"])
    b = fit_t.bands
    kind, lo, hi = b.kind.astype(str).to_numpy(), b.low.to_numpy(float), b.high.to_numpy(float)
    left = np.where(kind == "lte", -np.inf, lo - 0.5)
    right = np.where(kind == "gte", np.inf, hi + 0.5)
    cb, sb = np.repeat(centre, fit_t.n), np.repeat(sig, fit_t.n)
    p = norm.cdf((right - cb) / sb) - norm.cdf((left - cb) / sb)
    g = np.where(fit_t.impossible, 0.0, np.clip(p, mb.EPS, 1.0))
    s_m = np.bincount(fit_t.band_snap, weights=fit_t.p_market, minlength=len(fit_t.snaps))
    s_g = np.bincount(fit_t.band_snap, weights=g, minlength=len(fit_t.snaps))
    scale = np.divide(s_m, s_g, out=np.zeros_like(s_m), where=s_g > 0)
    vec = g * np.repeat(scale, fit_t.n)
    return np.where(np.repeat(ok, fit_t.n), vec, fit_t.p_market), ok, {"sd_gap": sd, "covered": int(ok.sum())}


def control_c5(arm, covered, fit_t, score_t, geo, score_dates, donors, dc_counts):
    rec = {"label": "CONTROL (planted; not a candidate)", "arm": arm, "shrink": SYN_SHRINK, "seed": SYN_SEED}
    for name, sign in (("SYN+", 1.0), ("SYN-", -1.0)):
        vec, ok, meta = planted(fit_t, geo, covered, sign)
        sums_c, sums_pl, n_snaps, n_dates = sums_for_vector(vec, ok, fit_t, score_t, score_dates, donors)
        r = {"population_snapshots": n_snaps, "population_dates": n_dates, **meta}
        if n_dates < sw.MIN_DATES or n_snaps < sw.MIN_SNAPS:
            r.update(testable=False)
        else:
            r.update(testable=True, **wider_interval(sums_c, sums_pl, dc_counts))
        rec[name] = r
    sp, sm = rec["SYN+"], rec["SYN-"]
    plus = bool(sp.get("testable") and sp["ci95_wider"][0] is not None and sp["ci95_wider"][0] > 0
                and sp["ci95_wider"][1] is not None and sp["ci95_wider"][1] >= EDGE)
    minus = bool(sm.get("testable") and sm["ci95_wider"][1] is not None and sm["ci95_wider"][1] < 0)
    rec.update(syn_plus_pass=plus, syn_minus_pass=minus, verdict="PASS" if plus and minus else "FAIL")
    return rec


def verdict_for(testable, c5_pass, power, upper, lower, bh_reject):
    """Rule 5.1, first match decides."""
    if not testable:
        return LABEL_UNTESTABLE
    if not c5_pass:
        return LABEL_UNTESTABLE_C5
    if power is None or power < POWER_MIN:
        return LABEL_UNTESTABLE_POWER
    if upper is not None and upper < EDGE:
        return LABEL_KILL
    if bh_reject and lower is not None and lower > 0:
        return LABEL_SURVIVOR
    return LABEL_INCONCLUSIVE


# ----------------------------------------------------------------------------- stage 2

def _load_stage1(stage1_dir, stage1_sha):
    d = Path(stage1_dir)
    rec_path, pq_path = d / STAGE1_RECEIPT, d / STAGE1_PARQUET
    got = ls.sha256_file(rec_path)
    if got != stage1_sha:
        raise DscError(f"refused: stage1 receipt sha {got} != --stage1-sha {stage1_sha}")
    rec = json.loads(rec_path.read_text(encoding="utf-8"))
    if rec.get("c0", {}).get("verdict") != "PASS":
        raise DscError("refused: stage 1 C0 did not pass")
    pq = pq_path.read_bytes()
    if sha256_bytes(pq) != rec["stage1_parquet_sha256"]:
        raise DscError("refused: stage1 parquet sha differs from its receipt")
    return rec, pd.read_parquet(io.BytesIO(pq))


def stage2(*, layout, stage1_dir, stage1_sha, out_dir, allow_dirty=False):
    code = ls.require_clean(ls.code_state(), allow_dirty)
    machinery = check_machinery()
    out = check_out_dir(out_dir)
    s1, frame = _load_stage1(stage1_dir, stage1_sha)
    if s1["code"]["git_head"] != code["git_head"]:
        raise DscError(f"refused: stage 2 HEAD {code['git_head']} != stage 1 HEAD {s1['code']['git_head']}")
    # one look only: the marker is created exclusively before any label is attached
    write_exclusive(Path(stage1_dir) / LOOK_MARKER, json.dumps({"stage1_receipt_sha256": stage1_sha,
                                                                 "stage2_out": str(out), "git_head": code["git_head"]}))
    out.mkdir(parents=True)

    from weather.calibration import c3_kill_tier as c3
    from weather.calibration import market_blend as mb
    from weather.reporting.scorecards import dev_scorecard as sc

    lay, folds, burn, scored, fit_t, score_t = mg.build_tables(layout)  # labels attached here (step 1)
    par = s1["table_parity"]
    parity = {"manifest": lay.manifest_sha256 == s1["layout"]["manifest_sha256"] == LAYOUT_MANIFEST_SHA256,
              "row_key": _hash(fit_t.snaps.row_key.astype(str).to_numpy()) == par["row_key_sha256"],
              "n": _hash(fit_t.n) == par["n_sha256"], "p_market": _hash(fit_t.p_market) == par["p_market_sha256"],
              "score_row_key": _hash(score_t.snaps.row_key.astype(str).to_numpy()) == par["score_row_key_sha256"],
              "frame_row_key": bool((frame.row_key.to_numpy() == fit_t.snaps.row_key.astype(str).to_numpy()).all()),
              "burn_scored": burn == s1["layout"]["burn"] and scored == s1["layout"]["scored"]}
    if not all(parity.values()):
        raise DscError(f"refused: stage 2 tables differ from stage 1 {parity}")
    values = {arm: frame[f"value__{arm}"].to_numpy(float) for arm, _, _ in ARMS}

    # step 2: C1, C2 (served R, MG-1 07-12 excess, w0 on MG-1), C3 per arm tilt, C5 per arm
    controls = mg.market_controls(fit_t, score_t)
    geo = sw.band_geometry(fit_t)
    tilts = {}
    for arm, kind, sign in ARMS:
        cov = np.isfinite(values[arm])
        s = sw.band_signal(kind, sign, np.where(cov, values[arm], np.nan), fit_t, geo)
        c_fit, _ = sw.tilt(fit_t, geo, s, cov)
        tilts[arm] = c_fit
        controls[f"c3_w0_identity_{arm}"] = mb.w0_identity(score_t, mb.restrict(fit_t, score_t, c_fit))
    failed = [k for k, v in controls.items() if v["verdict"] != "PASS"]
    if failed:
        raise mb.ControlFailed(f"refused: controls failed {failed}")
    score_dates = np.array(sorted({str(d) for d in score_t.snaps.date.astype(str)}))
    counts = sw.boot_counts(len(score_dates))
    donors = {seed: sw.donor_positions(fit_t, seed) for seed in sw.PLACEBO_SEEDS}
    c5 = {arm: control_c5(arm, np.isfinite(values[arm]), fit_t, score_t, geo, score_dates, donors, counts)
          for arm, _, _ in ARMS}

    # step 3: p0_candidate per arm, the wider interval, BH and the section 5.1 verdicts
    results, kept, rows = {}, {}, []
    for arm, kind, sign in ARMS:
        res, vecs = sw.p0_candidate(arm, kind, sign, values[arm], fit_t, score_t, geo, counts, score_dates, donors)
        arm_rows = res.pop("_rows", [])
        res.pop("placebo_meta", None)
        res["coverage_matches_stage1"] = (
            res["coverage"]["population_snapshots"] == s1["populations"][arm]["population_snapshots"]
            and res["coverage"]["fit_covered_snapshots"] == s1["populations"][arm]["fit_covered"])
        if not res["coverage_matches_stage1"]:
            raise DscError(f"refused: {arm} p0_candidate population differs from stage 1")
        if res["testable"]:
            if not np.array_equal(vecs["c_fit"], tilts[arm]):
                raise DscError(f"refused: {arm} p0_candidate tilt differs from the C3 tilt")
            sums_c = np.array([r["sums_c"] for r in arm_rows], float).T
            sums_pl = [np.array([r["sums_pl"][j] for r in arm_rows], float).T for j in range(len(sw.PLACEBO_SEEDS))]
            iv = wider_interval(sums_c, sums_pl, counts)
            if iv["delta"] != res["p0"]["delta"] or iv["ci95_date_clustered"] != res["p0"]["ci95"] \
                    or iv["p_one_sided"] != res["p0"]["p_one_sided"]:
                raise DscError(f"refused: {arm} rebuilt sums do not reproduce p0_candidate")
            res["wider"] = iv
            kept[arm] = vecs
        else:
            res["wider"] = None
        results[arm] = res
        rows += arm_rows
    ids = [a for a, _, _ in ARMS]
    pvals = [results[a]["p0"]["p_one_sided"] if results[a]["testable"] else 1.0 for a in ids]
    adj, reject = sw.bh_adjust(pvals)
    if [bool(r) for r in reject] != [bool(r) for r in c3.bh(pvals)]:
        raise DscError("refused: the two BH implementations disagree")
    lines = []
    for arm, p, q, rj in zip(ids, pvals, adj, reject):
        r = results[arm]
        iv = r["wider"] or {}
        lo, hi = (iv.get("ci95_wider") or [None, None])
        r.update(bh_p=float(p), bh_q=float(q), bh_reject=bool(rj), c5_verdict=c5[arm]["verdict"])
        r["verdict"] = verdict_for(r["testable"], c5[arm]["verdict"] == "PASS", iv.get("power_at_edge"), hi, lo,
                                   bool(rj))
        r["edge_boundary_note"] = bool(hi is not None and EDGE <= hi < math.sqrt(0.05))
        lines.append(line_for(arm, r))

    # survivors only: the w gate (rule section 6) with the j = 0 disagreement placebo
    for arm in [a for a in ids if results[a]["verdict"] == LABEL_SURVIVOR]:
        vec = kept[arm]
        g = mg.gate_candidate(arm, BLOCK, fit_t, score_t, vec["c_fit"], vec["covered"], p_placebo_fit=vec["pl0_fit"])
        results[arm]["w_gate"] = {"verdict": "PASS (w)" if g["w"]["pass"] else "KILL (w)", "w": g["w"],
                                  "rows": g["rows"], "per_hour": g["per_hour"], "coverage": g["coverage"]}
        for row in rows:
            if row["candidate"] == arm:
                row["w"] = g["w"]["w_by_date"].get(row["date"])
                row["paired_brier"] = g["per_date"].get(row["date"])

    rows_text = "".join(json.dumps(r, sort_keys=True, default=mg._default) + "\n" for r in rows)
    write_exclusive(out / STAGE2_ROWS, rows_text)
    receipt = {"schema": SCHEMA, "gate": GATE, "stage": "stage2", "rule_sha256": RULE_SHA256,
               "freeze_commit": FREEZE_COMMIT, "run_env_pin": RUN_ENV_PIN, "code": code, "machinery": machinery,
               "evidence_class": "development (dev window, provisional)",
               "stage1_receipt_sha256": stage1_sha, "stage1_parquet_sha256": s1["stage1_parquet_sha256"],
               "scorecard_code_sha256": sc.code_sha256(), "layout_manifest_sha256": lay.manifest_sha256,
               "replay_sha256sums_sha256": REPLAY_SUMS_SHA256, "nowcast_sha256": NOWCAST_SHA256,
               "replay_malformed_lines": s1["extraction"]["malformed_lines"], "parity": parity,
               "population": {"burn_in_dates": burn, "scored_first": scored[0], "scored_last": scored[-1],
                              "n_scored_dates": len(scored), "markets": sorted(set(score_t.markets))},
               "constants": {"draws": sw.DRAWS, "seed": sw.SEED, "placebo_seeds": list(sw.PLACEBO_SEEDS),
                             "bh_q": sw.BH_Q, "min_dates": sw.MIN_DATES, "min_snapshots": sw.MIN_SNAPS,
                             "block3_b": c3.BOOT_B, "block3_seed": c3.BOOT_SEED, "block3_len": c3.BLOCK_LEN,
                             "edge": EDGE, "z": Z, "power_min": POWER_MIN, "syn_shrink": SYN_SHRINK,
                             "syn_seed": SYN_SEED, "eps": mb.EPS},
               "c0": s1["c0"], "controls": controls, "c5": c5, "results": results, "bh": {
                   "ids": ids, "p": pvals, "q": [float(x) for x in adj], "reject": [bool(x) for x in reject]},
               "lines": lines, "rows_sha256": sha256_bytes(rows_text.encode("utf-8"))}
    write_exclusive(out / STAGE2_RECEIPT, json.dumps(receipt, indent=1, sort_keys=True, default=mg._default))
    return receipt


def line_for(arm, r):
    iv = r.get("wider")
    if not iv:
        c = r["coverage"]
        return f"{r['verdict']}: {arm} population {c['population_snapshots']} / {c['population_dates']} dates; " \
               f"BH q {r['bh_q']:.3f}"
    lo, hi = iv["ci95_wider"]
    return (f"{r['verdict']}: {arm} delta {iv['delta']:+.4f} wider [{lo:+.4f}, {hi:+.4f}] SE {iv['se_wider']:.4f} "
            f"power {iv['power_at_edge']:.4f}; C5 {r['c5_verdict']}; p {r['bh_p']:.4f} BH q {r['bh_q']:.3f}; "
            f"population {r['coverage']['population_snapshots']} / {r['coverage']['population_dates']}")
