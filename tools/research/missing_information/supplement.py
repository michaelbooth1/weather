"""Declared sensitivities, censored lag intervals, and a captured-feature trace.

The frozen primary outputs stay intact. These additions do not fit a candidate.
"""

from weather.projection_io import projection_source, read_projection_frame
from collections import Counter
import copy
import json
import math
from pathlib import Path
import pickle
import subprocess

import numpy as np
import pandas as pd

from weather.paths import REPO_ROOT, repo_path
from tools.research.missing_information.checks import cells, compare
from tools.research.missing_information.extract import read_csv, sha256, finite
from tools.research.missing_information.methods import crossed_weights, summary


def weighted_quantile(values, weights, quantile=.5):
    values, weights = np.asarray(values), np.asarray(weights)
    order = np.argsort(values, kind="stable")
    v, w = values[order], weights[..., order]
    totals = w.sum(axis=-1)
    positions = (w.cumsum(axis=-1) >= (quantile * totals)[..., None]).argmax(axis=-1)
    return np.where(totals > 0, v[positions], np.nan)


def empirical_interval(estimate, boot, effect):
    boot = np.asarray(boot)
    boot = boot[np.isfinite(boot)]
    if len(boot) < 1900:
        return {"status": "INSUFFICIENT_BOOTSTRAP_SUPPORT", "estimate": estimate}
    error = boot - estimate
    critical = np.quantile(abs(error), .95)
    power = lambda delta: float(np.mean(abs(error+delta) > critical))
    low, high = 0., max(critical*10, 1e-9)
    for _ in range(50):
        mid = (low+high)/2
        if power(mid) >= .8:
            high = mid
        else:
            low = mid
    return dict(estimate=float(estimate), ci95=np.quantile(boot, [.025, .975]).tolist(),
                alternative_effect=effect, power=power(effect), mde80=high,
                valid_draws=len(boot), status="DESCRIPTIVE")


def lag_intervals(hourly):
    rows = []
    for (date, market), day in hourly.groupby(["date", "market"]):
        day = day.sort_values("hour")
        for r in day.itertuples():
            future = day[(day.hour >= r.hour) & (day.model_loss <= r.market_loss)]
            rows.append(dict(date=date, market=market, hour=r.hour,
                             lag=float(future.hour.iloc[0]-r.hour) if len(future) else np.nan,
                             censored=float(not len(future)), followup=float(day.hour.max()-r.hour)))
    lf = pd.DataFrame(rows)
    result = {}
    for hour, g in lf.groupby("hour"):
        resolved = g.dropna(subset=["lag"])
        out = dict(censoring=summary(g, "censored", alternative=.1),
                   followup=summary(g, "followup", alternative=1.),
                   resolved=len(resolved), median_scope="resolved pairs only, never full-panel lag")
        if resolved.date.nunique() >= 2 and resolved.market.nunique() >= 2:
            w = crossed_weights(resolved.date, resolved.market)
            estimate = weighted_quantile(resolved.lag.to_numpy(), np.ones(len(resolved)))
            out["median"] = {**empirical_interval(estimate, weighted_quantile(resolved.lag.to_numpy(), w), 1.),
                             "date_clusters": resolved.date.nunique(), "market_clusters": resolved.market.nunique(),
                             "market_days": len(resolved)}
        result[int(hour)] = out
    return result


def ratio_rise(hourly, inclusive=False):
    am = cells(hourly[hourly.hour.between(6, 10 if inclusive else 9)], ["model_loss", "market_loss"])
    pm = cells(hourly[hourly.hour.between(13, 17 if inclusive else 16)], ["model_loss", "market_loss"])
    f = am.merge(pm, on=["date", "market"], suffixes=("_am", "_pm"))
    w = crossed_weights(f.date, f.market)
    def statistic(weights):
        return ((weights @ f.model_loss_pm)/(weights @ f.market_loss_pm)
                - (weights @ f.model_loss_am)/(weights @ f.market_loss_am))
    return {**empirical_interval(statistic(np.ones(len(f))), statistic(w), .3),
            "market_days": len(f), "date_clusters": f.date.nunique(), "market_clusters": f.market.nunique()}


def captured_feature_trace(raw):
    """Run the canonical selection/imputation method on an actual captured row.

    Artifact identity is proved against Git LFS, but historical active binding
    cannot be proved by a model-version string or an opaque model_identity_hash.
    """
    from weather.model.model_features import FeatureModelMixin
    pointer = repo_path("artifacts/models/hgb/feature_model_hgb_atlanta.pkl")
    content = pointer.read_bytes()
    if content.startswith(b"version https://git-lfs"):
        digest = content.decode().split("oid sha256:")[1].splitlines()[0]
        common = Path(subprocess.check_output(["git", "rev-parse", "--git-common-dir"], cwd=REPO_ROOT, text=True).strip())
        if not common.is_absolute():
            common = (REPO_ROOT/common).resolve()
        artifact = common / "lfs" / "objects" / digest[:2] / digest[2:4] / digest
    else:
        artifact, digest = pointer, sha256(pointer)
    if sha256(artifact) != digest:
        raise ValueError("local artifact differs from tracked LFS identity")
    with artifact.open("rb") as stream:
        bundles = pickle.load(stream)
    folder = raw / "highest-temperature-in-atlanta-on-august-1-2026"
    row = next(r for r in read_csv(projection_source(folder/"features_long.csv")) if finite(r.get("nbm_prob_tmax_p50")) is not None)
    feats = {k: finite(v) for k, v in row.items()}
    feats.update(wind_group=row.get("wind_group"), cloud_group=row.get("cloud_group"))
    cutoff = str(int(float(row["cutoff_hour"])))
    original = bundles[cutoff]
    class Trace(FeatureModelMixin):
        def extract_live_features(self, *args, **kwargs):
            return self.feats
    class Imputer:
        def transform(self, x):
            self.input = x.copy()
            return original["imputer"].transform(x)
    class Model:
        classes_ = original["model"].classes_
        def predict_proba(self, x):
            self.input = x.copy()
            return original["model"].predict_proba(x)
    outputs = []
    for missing in (False, True):
        imputer, model, runner = Imputer(), Model(), Trace()
        runner.feats = dict(feats)
        if missing:
            runner.feats.update({k: None for k in feats if k.startswith("nbm_")})
        payload = {**original, "model": model, "imputer": imputer}
        result, kind = runner._evaluate_feature_model_for_cutoff({}, int(cutoff), {cutoff: payload}, None)
        if kind != "hgb":
            raise ValueError("canonical trace failed to reach HGB prediction")
        outputs.append(dict(nbm_missing=missing, selected_columns=list(imputer.input.columns),
                            selected_input=imputer.input.iloc[0].to_dict(), model_input=model.input[0].tolist(),
                            prediction=result))
    records = [r for r in read_csv(folder/"observation_payloads_long.csv") if r["snapshot_id"] == row["snapshot_id"]]
    inventories = {}
    for hour, bundle in bundles.items():
        if isinstance(bundle, dict) and "feature_names" in bundle:
            inventories[hour] = dict(features=list(bundle["feature_names"]),
                                     importance_keys=[k for k in bundle if "importan" in k.lower()],
                                     selected_guidance=[k for k in bundle["feature_names"] if any(s in k for s in ("nbm", "nws_grid", "hrrr"))])
    return dict(artifact_sha256=digest, artifact_bytes=artifact.stat().st_size, cutoff=cutoff,
                artifact_top_keys=list(bundles),
                snapshot_id=row["snapshot_id"], market="atlanta", date="2026-08-01",
                captured_nbm_p50=feats["nbm_prob_tmax_p50"], model_version=row["model_version"],
                captured_model_identity_hashes=sorted({r.get("model_identity_hash", "") for r in records}),
                captured_release_statuses=sorted({r.get("release_identity_status", "") for r in records}),
                historical_active_binding="UNPROVED: export has opaque identity hashes, not per-artifact fingerprints",
                permutation_importance_status="Report retained importance keys only; no held-out permutation fit was authorized",
                bundles=inventories, traces=outputs,
                nbm_removal_changes_input=not np.allclose(outputs[0]["model_input"], outputs[1]["model_input"], equal_nan=True))


def guidance_sensitivities(baseline):
    scores = read_projection_frame(baseline/"guidance_paired_snapshot_scores.csv")
    result = {}
    for stratum, f in scores.groupby("stratum"):
        s = {}
        for name, lo, hi in (("morning_inclusive10", 0, 10), ("morning_after07", 7, 9), ("afternoon_inclusive17",13,17)):
            out = {}
            for variant, g in f[f.hour.between(lo,hi)].groupby("variant"):
                c = cells(g, ["candidate_loss","model_loss","market_loss"], ["hour"])
                c["delta_model"] = c.candidate_loss-c.model_loss
                out[variant] = dict(ratio=summary(c,"candidate_loss","market_loss",null=1.1,alternative=.1),
                                    vs_model=summary(c,"delta_model",alternative=.01))
            s[name] = out
        nbm = f[f.variant.isin(["nbm_raw","nbm_floor"]) & f.hour.between(7,9)]
        pair = nbm.pivot(index=["date","market","hour","snapshot_id"], columns="variant",values="candidate_loss").dropna().reset_index()
        pair["delta"] = pair.nbm_floor-pair.nbm_raw
        s["floor_vs_raw_identical_snapshots_after07"] = summary(cells(pair,["delta"],["hour"]),"delta",alternative=.01)
        result[stratum] = s
    return result


def supplement(frame, raw, extracted, output, baseline=None):
    audits = json.loads((extracted/"extraction_audit.json").read_text())
    excluded = [dict(folder=a["folder"], date=a.get("date"), market=a.get("market"), reason=a.get("reason", "no_admissible_snapshots"))
                for a in audits if not a.get("snapshots")]
    reasons = Counter()
    for a in audits:
        reasons.update(a.get("excluded_snapshots", {}))
    out = dict(population=dict(folders=len(audits), admitted_market_days=len(audits)-len(excluded),
                              excluded=excluded, excluded_snapshot_reasons=dict(reasons),
                              days_with_max_decreases=sum(a.get("max_decreases", 0)>0 for a in audits)), strata={})
    cols = ["model_loss", "market_loss", "market_normalized_loss", "excess"]
    for stratum, f in frame.groupby("stratum"):
        hour = cells(f, cols, ["hour"])
        s = dict(all_hours=compare(hour), ratio_rise=ratio_rise(hour),
                 ratio_rise_inclusive=ratio_rise(hour, True),
                 inclusive_am=compare(hour[hour.hour.between(6, 10)]),
                 inclusive_pm=compare(hour[hour.hour.between(13, 17)]),
                 lag=lag_intervals(hour), last_capture_by_market={})
        safe = f[f.hour >= 7]
        # Exclude yesterday's pre-07 station window; missing is never zero.
        s["floor_after07"] = {name: summary(cells(safe, [name], ["hour"]), name, alternative=.1)
                              for name in ("model_impossible_mass", "market_impossible_mass")}
        for market, g in f.groupby("market"):
            s["last_capture_by_market"][market] = g.groupby("date").decimal_hour.max().describe().to_dict()
        peak_rows = []
        for (date, market), day in safe.groupby(["date", "market"]):
            day = day.sort_values("captured_at_utc").dropna(subset=["station_max_since_7am_c"])
            if day.empty:
                continue
            final = day.iloc[-1]
            envelope = day.station_max_since_7am_c.max()
            first = day[day.station_max_since_7am_c == envelope].iloc[0]
            peak_rows.append(dict(date=date, market=market, peak_hour=first.decimal_hour,
                                  delta=final.settlement_bucket-math.floor(envelope+.5),
                                  off_zero=float(final.settlement_bucket != math.floor(envelope+.5))))
        p = pd.DataFrame(peak_rows)
        p.to_csv(output/f"target_day_peak_{stratum}.csv", index=False)
        s["target_day_envelope_off_zero"] = summary(p, "off_zero", alternative=.1)
        # The original envelope-relative output is available per snapshot.
        for label, field in (("literal", "hours_from_peak"), ("envelope", "hours_from_envelope_peak")):
            pframe = f.copy()
            pframe["peak_bin"] = pd.cut(pframe[field], [-np.inf,-6,-3,-1,0,1,3,np.inf])
            s[f"peak_{label}"] = {str(k): compare(cells(g, cols, ["hour"])) for k,g in pframe.groupby("peak_bin", observed=True)}
        out["strata"][stratum] = s
    out["artifact_trace"] = captured_feature_trace(raw)
    if baseline is not None:
        out["guidance_sensitivities"] = guidance_sensitivities(baseline)
    return out
