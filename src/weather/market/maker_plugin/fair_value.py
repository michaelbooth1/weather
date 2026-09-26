"""Frozen zero-fit T+1/T+2 CDF and captured served T+0 probabilities."""
from datetime import timedelta
import math
from statistics import NormalDist

from maker_core.contracts import OutcomeView, Unavailable, utc_time
from weather.market.maker_plugin.inputs import digest, event_identity, latest, records, timestamp
from weather.market.maker_plugin import nbp


def percentile_cdf(knots, x):
    qs = (.10, .25, .50, .75, .90)
    if not math.isfinite(x):
        return 0.0 if x < 0 else 1.0
    index = next((i for i in range(4) if x <= knots[i + 1]), 3)
    value = qs[index] + (x - knots[index]) * (qs[index + 1] - qs[index]) / (knots[index + 1] - knots[index])
    return max(0., min(1., value))


def integrate(bands, cdf):
    ordered = sorted(bands.items(), key=lambda item: item[1])
    if not ordered or ordered[0][1][0] != -math.inf or ordered[-1][1][1] != math.inf:
        raise ValueError("event_missing_open_tails")
    if any(left[1][1] != right[1][0] for left, right in zip(ordered, ordered[1:])):
        raise ValueError("event_partition_gap_or_overlap")
    masses = {cid: cdf(hi) - cdf(lo) for cid, (lo, hi) in ordered}
    total = math.fsum(masses.values())
    if total <= 0 or any(not math.isfinite(v) or v < 0 for v in masses.values()):
        raise ValueError("invalid_event_probability_mass")
    return {cid: value / total for cid, value in masses.items()}


class WeatherFairValue:
    def __init__(self, universe, *, bulletins=(), forecasts=(), snapshots=(), explanations=(), source_rows=()):
        self.universe = universe
        self.bulletins = records(bulletins)
        self.forecasts = records(forecasts)
        self.snapshots = records(snapshots)
        self.explanations = records(explanations)
        self.source_rows = records(source_rows)

    def evaluate(self, market, as_of_utc):
        utc_time(as_of_utc)
        try:
            spec, target = event_identity(market.event_id)
            if market.domain_id != "weather" or market.native_unit != spec.unit:
                raise ValueError("market_identity_or_unit_mismatch")
            lead = (target - as_of_utc.astimezone(spec.tz).date()).days
            if lead == 0:
                return self._served(market, as_of_utc)
            if lead not in (1, 2):
                raise ValueError("unsupported_local_lead")
            bands = self.universe.bands(market.event_id, as_of_utc)
            candidates = []
            for raw in self.bulletins:
                if (raw.get("station_id") != spec.icao or raw.get("target_date") != target.isoformat()
                        or timestamp(raw["fetched_at"]) > as_of_utc):
                    continue
                try:
                    issue, knots, slot = nbp.parse(raw, spec.icao, target)
                except ValueError as exc:
                    if str(exc) in {"target_max_not_in_cycle", "target_max_incomplete_rows"}:
                        continue  # Older complete maxima can still be eligible.
                    raise  # Corrupt or ambiguous evidence must not become fallback.
                if issue <= as_of_utc < nbp.valid_until(issue):
                    candidates.append((issue, raw, knots, slot))
            if candidates:
                newest = max(c[0] for c in candidates)
                chosen = [c for c in candidates if c[0] == newest]
                if len({c[1]["payload_hash"] for c in chosen}) != 1:
                    raise ValueError("conflicting_nbp_issue")
                issue, raw, knots, slot = min(chosen, key=lambda c: timestamp(c[1]["fetched_at"]))
                joint = integrate(bands, lambda x: percentile_cdf(knots, x))
                return self._view(market, as_of_utc, issue, nbp.valid_until(issue), joint,
                                  {"payload": raw["payload_hash"], "fetched_at": raw["fetched_at"],
                                   "slot": list(slot[:3]), "bands": {k: [str(v) for v in b] for k, b in bands.items()}},
                                  "nbp-v2-piecewise-linear")
            return self._fallback(market, spec, target, as_of_utc, bands)
        except (ValueError, KeyError, TypeError, StopIteration, OverflowError) as exc:
            return Unavailable(str(exc) or "malformed_captured_input", as_of_utc)

    @staticmethod
    def _view(market, as_of, issue, expiry, joint, inputs, model):
        p = joint[market.condition_id]
        stdev = math.sqrt(p * (1 - p)) * ((as_of - issue).total_seconds() / 86400 + .25)
        if stdev <= 0:
            raise ValueError("zero_uncertainty_not_representable")
        return OutcomeView(market.condition_id, p, stdev, joint, as_of, expiry, digest(inputs), model, "none")

    def _fallback(self, market, spec, target, as_of, bands):
        candidates = []
        for row in self.forecasts:
            if row.get("target_date") != target.isoformat() or row.get("event_slug") != market.event_id:
                continue
            if row.get("forecast_kind") != "daily_high" or timestamp(row["captured_at_utc"]) > as_of:
                continue
            issue_text = row.get("provider_issue_time") or row.get("provider_update_time")
            if not issue_text:
                continue
            issue = timestamp(issue_text)
            if (target - issue.astimezone(spec.tz).date()).days != 1:
                continue
            if issue <= timestamp(row["captured_at_utc"]) <= as_of < issue + timedelta(hours=24):
                candidates.append({"issue": issue.isoformat(), "row": row})
        selected = latest(candidates, as_of, "issue")
        row, issue = selected["row"], timestamp(selected["issue"])
        mean = float(row["forecast_high_c"])
        if not math.isfinite(mean):
            raise ValueError("invalid_forecast_high")
        distribution = NormalDist(mean, 3.6 if spec.unit == "F" else 2.)
        joint = integrate(bands, distribution.cdf)
        inputs = {key: row.get(key) for key in ("event_slug", "target_date", "source", "forecast_kind",
                  "captured_at_utc", "provider_issue_time", "provider_update_time", "forecast_high_c")}
        inputs["bands"] = {k: [str(v) for v in b] for k, b in bands.items()}
        return self._view(market, as_of, issue, issue + timedelta(hours=24), joint, inputs,
                          "pit-lead1-normal-fixed-2C-equivalent")

    def _served(self, market, as_of):
        row = latest([r for r in self.snapshots if r.get("condition_id") == market.condition_id
                      and r.get("event_slug") == market.event_id], as_of)
        captured = timestamp(row["captured_at_utc"])
        expiry = captured + timedelta(minutes=15)
        if as_of >= expiry:
            raise ValueError("served_snapshot_expired")
        def matching(rows):
            return [r for r in rows if r.get("snapshot_id") == row["snapshot_id"]
                    and r.get("event_slug") == market.event_id
                    and timestamp(r["captured_at_utc"]) == captured]
        explanation = latest(matching(self.explanations), as_of)
        stage = explanation["explanations"]["probability_calibration_context"]["afternoon_residual_centering"]
        if not isinstance(stage, dict) or not stage:
            raise ValueError("missing_afternoon_stage_context")
        sources = matching(self.source_rows)
        lineage = {(r.get("release_id"), r.get("release_manifest_sha256"), r.get("release_identity_status")) for r in sources}
        if len(lineage) != 1:
            raise ValueError("missing_or_ambiguous_release_lineage")
        release, manifest, status = lineage.pop()
        if not release or not manifest or status != "verified_variant_serving_bundle":
            raise ValueError("served_snapshot_release_unbound")
        p = float(row["model_probability"])
        # Keep the captured marginal exactly; no normalization or re-serving.
        return OutcomeView(market.condition_id, p, math.sqrt(p * (1 - p)) * .25, None,
                           captured, expiry, digest({"snapshot": row["snapshot_id"], "probability": p,
                           "release": release, "manifest": manifest, "stage": stage,
                           "model_version": row["model_version"], "captured_at_utc": row["captured_at_utc"]}),
                           f"served:{release}:afternoon_residual_centering:{digest(stage)}", "none")
