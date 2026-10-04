"""Frozen zero-fit T+1/T+2 CDF and captured served T+0 probabilities."""
from datetime import timedelta
import math
from statistics import NormalDist

from maker_core.contracts import OutcomeView, Unavailable, utc_time
from weather.market.maker_plugin.inputs import digest, event_identity, latest, records, timestamp
from weather.market.maker_plugin import nbp


def percentile_cdf(knots, x):
    """Right-continuous piecewise-linear CDF through p10/p25/p50/p75/p90.

    Equal knots are atoms (the 79a reading, ``quantile_cdf``). The first and
    last segments extend linearly to probability zero and one. NBP prints
    whole degrees, so a tied end pair is read one degree apart (T+1
    Amendment 2): its 10% tail falls at the frozen .15 per degree and ends
    2/3 degree beyond the knot. Band edges are half degrees and NBP knots
    whole degrees, so no edge meets an atom.
    """
    qs = (.10, .25, .50, .75, .90)
    if knots[0] == knots[4]:
        raise ValueError("degenerate_percentile_knots")
    if not math.isfinite(x):
        return 0.0 if x < 0 else 1.0
    if x < knots[0]:
        if knots[1] == knots[0]:
            return max(0., qs[0] - (knots[0] - x) * (qs[1] - qs[0]))
        index = 0
    elif x >= knots[4]:
        if knots[4] == knots[3]:
            return min(1., qs[4] + (x - knots[4]) * (qs[4] - qs[3]))
        index = 3
    else:
        index = max(i for i in range(4) if knots[i] <= x)
    value = qs[index] + (x - knots[index]) * (qs[index + 1] - qs[index]) / (knots[index + 1] - knots[index])
    return max(0., min(1., value))


def model_id(knots):
    """Strictly increasing knots keep the frozen 110b estimator's identity.

    Only a tied end pair changes value under Amendment 2, so only it takes
    the new identity; interior-only ties keep Amendment 1's.
    """
    if all(a < b for a, b in zip(knots, knots[1:])):
        return "nbp-v2-piecewise-linear"
    if knots[0] == knots[1] or knots[3] == knots[4]:
        return "nbp-v2-piecewise-linear-atoms-resolution-tails"
    return "nbp-v2-piecewise-linear-atoms"


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
        self._daily_high_rows = {}
        self._parsed = {}
        self.last_nbp_read = None

    def _parse(self, raw, station, target):
        """``nbp.parse`` is pure in these fields; replay repeats it every minute."""
        key = (raw["payload_hash"], raw["text"], raw["fetched_at"], raw["station_id"], raw["target_date"],
               station, target)
        if key not in self._parsed:
            try:
                self._parsed[key] = (True, nbp.parse(raw, station, target))
            except ValueError as exc:
                self._parsed[key] = (False, str(exc))
        ok, value = self._parsed[key]
        if not ok:
            raise ValueError(value)
        return value

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
                    issue, knots, slot = self._parse(raw, spec.icao, target)
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
                inputs = {"payload": raw["payload_hash"], "fetched_at": raw["fetched_at"],
                          "source_payload": raw.get("source_payload_hash"),
                          "slot": list(slot[:3]), "bands": {k: [str(v) for v in b] for k, b in bands.items()},
                          "band_basis": self.universe.band_basis(market.event_id, as_of_utc)}
                # Outside the digest: what a reviewer needs to recompute the view by hand.
                self.last_nbp_read = dict(inputs, issue=issue.isoformat(), knots=list(knots))
                return self._view(market, as_of_utc, issue, nbp.valid_until(issue), joint, inputs, model_id(knots))
            return self._fallback(market, spec, target, as_of_utc, bands)
        except (ValueError, KeyError, TypeError, StopIteration, OverflowError) as exc:
            return Unavailable(str(exc) or "malformed_captured_input", as_of_utc)

    def forecast_gap(self, market, as_of_utc):
        """Why no NBP issue was eligible at the minute (diagnostic only).

        ``expired_next_cycle_fetched_late``: the newest target-bearing issue
        expired (next cycle availability = cycle + 1 h, pre-registered) and the
        next cycle was captured later. ``expired_next_cycle_not_captured``: no
        later cycle exists in the pool. ``fetched_after_expiry``: the newest
        issue arrived after its own expiry. ``no_cycle_with_target`` and
        ``no_bulletin``: nothing to read.
        """
        spec, target = event_identity(market.event_id)
        held, later, any_bulletin = [], [], False
        for raw in self.bulletins:
            if raw.get("station_id") != spec.icao or raw.get("target_date") != target.isoformat():
                continue
            fetched = timestamp(raw["fetched_at"])
            any_bulletin = any_bulletin or fetched <= as_of_utc
            try:
                issue, _, _ = self._parse(raw, spec.icao, target)
            except ValueError:
                continue
            (held if fetched <= as_of_utc else later).append((issue, fetched))
        if not held:
            return "no_cycle_with_target" if any_bulletin else "no_bulletin"
        issue, fetched = max(held)
        if fetched >= nbp.valid_until(issue):
            return "fetched_after_expiry"
        if any(other > issue for other, _ in later):
            return "expired_next_cycle_fetched_late"
        return "expired_next_cycle_not_captured"

    @staticmethod
    def _view(market, as_of, issue, expiry, joint, inputs, model):
        p = joint[market.condition_id]
        stdev = math.sqrt(p * (1 - p)) * ((as_of - issue).total_seconds() / 86400 + .25)
        return OutcomeView(market.condition_id, p, stdev, joint, as_of, expiry, digest(inputs), model, "none")

    def _daily_highs(self, event_id, spec, target):
        """Parse one event's daily-high rows once; refusals keep their row order.

        Entries carry a deferred error, or the capture clock and the issue clock
        (None without one, False when not a lead-one issue). Evaluation
        applies the same checks, in the same order, as a scan of every row.
        """
        key = (event_id, target)
        if key not in self._daily_high_rows:
            parsed = []
            for row in self.forecasts:
                if (row.get("target_date") != target.isoformat() or row.get("event_slug") != event_id
                        or row.get("forecast_kind") != "daily_high"):
                    continue
                try:
                    captured = timestamp(row["captured_at_utc"])
                except (ValueError, KeyError, TypeError) as exc:
                    parsed.append(("captured", (type(exc), exc.args), None, None, row))
                    continue
                issue_text = row.get("provider_issue_time") or row.get("provider_update_time")
                if not issue_text:
                    parsed.append((None, None, captured, None, row))
                    continue
                try:
                    issue = timestamp(issue_text)
                except (ValueError, KeyError, TypeError) as exc:
                    parsed.append(("issue", (type(exc), exc.args), captured, None, row))
                    continue
                lead_one = (target - issue.astimezone(spec.tz).date()).days == 1
                parsed.append((None, None, captured, issue if lead_one else False, row))
            self._daily_high_rows[key] = parsed
        return self._daily_high_rows[key]

    def _fallback_candidates(self, event_id, spec, target, as_of):
        candidates = []
        for failed, error, captured, issue, row in self._daily_highs(event_id, spec, target):
            if failed == "captured":
                raise error[0](*error[1])
            if captured > as_of:
                continue
            if failed == "issue":
                raise error[0](*error[1])
            if issue is None:
                continue  # No provider issue clock.
            if issue is False:
                continue  # Not a lead-one issue.
            if issue <= captured <= as_of < issue + timedelta(hours=24):
                candidates.append({"issue": issue.isoformat(), "row": row})
        return candidates

    def _fallback(self, market, spec, target, as_of, bands):
        candidates = self._fallback_candidates(market.event_id, spec, target, as_of)
        if not candidates:
            raise ValueError("missing_point_in_time_forecast")
        issue = max(timestamp(c["issue"]) for c in candidates)
        newest = [c["row"] for c in candidates if timestamp(c["issue"]) == issue]
        if len({digest({k: r.get(k) for k in ("source", "valid_time", "forecast_high_c")})
                for r in newest}) != 1:
            raise ValueError("conflicting_forecast_issue")
        row = min(newest, key=lambda r: timestamp(r["captured_at_utc"]))
        mean = float(row["forecast_high_c"])
        if not math.isfinite(mean):
            raise ValueError("invalid_forecast_high")
        distribution = NormalDist(mean, 3.6 if spec.unit == "F" else 2.)
        joint = integrate(bands, distribution.cdf)
        inputs = {key: row.get(key) for key in ("event_slug", "target_date", "source", "forecast_kind",
                  "captured_at_utc", "provider_issue_time", "provider_update_time", "forecast_high_c")}
        inputs["bands"] = {k: [str(v) for v in b] for k, b in bands.items()}
        inputs["band_basis"] = self.universe.band_basis(market.event_id, as_of)
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
        # The bounded export supplies this projection from the calibration
        # artifact belonging to the same verified release. Never guess identity
        # from a missing field or infer it from the probability/stage name.
        methods = {r.get("release_calibration_method") for r in sources}
        if len(methods) != 1:
            raise ValueError("served_release_calibration_ambiguous")
        method = methods.pop()
        if not isinstance(method, str) or not method or method != method.strip():
            raise ValueError("served_release_calibration_unavailable")
        if method == "market_shrink":
            return Unavailable("market_informed_release", as_of, kind="out_of_scope")
        p = float(row["model_probability"])
        # Keep the captured marginal exactly; no normalization or re-serving.
        return OutcomeView(market.condition_id, p, math.sqrt(p * (1 - p)) * .25, None,
                           captured, expiry, digest({"snapshot": row["snapshot_id"], "probability": p,
                           "release": release, "manifest": manifest, "stage": stage,
                           "release_calibration_method": method,
                           "model_version": row["model_version"], "captured_at_utc": row["captured_at_utc"]}),
                           f"served:{release}:calibration:{method}:afternoon_residual_centering:{digest(stage)}", "none")
