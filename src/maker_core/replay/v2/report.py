"""Per-cell scored report and its hash-bound sidecar (W5; registration draft §7 and §12).

The **scored report** holds, per market/UTC-date cell x policy x fill bound: status and exclusion
reasons, covered/pulled seconds, rewards at k = 1, 0.5 and 0.3, nominal rebate, settled inventory P&L,
unresolved fills, quotes, requotes, markouts, the three modeled nets, excluded seconds by reason with
the excluded-interval count and the SHA-256 of that cell's interval list, and the pull endpoint's
per-cell counts. It also holds the band-day table, the paired inference (the frozen estimators, which
read cell sums only), Clarification 2's k = 0.3 sensitivity, Clarification 3's fields through the frozen
``registered_decision``, and §12's non-decision small-cluster bound beside every economic estimate.

The **sidecar** holds the merged run-length excluded intervals and each pass's decision-stream SHA-256.
No estimator reads it; the report binds it by SHA-256, byte count and record count.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import fields
from decimal import Decimal
import hashlib

from scipy.special import stdtrit

from maker_core.evidence.journal import canonical_bytes
from maker_core.replay.clarification_3 import quote_presence, registered_decision
from maker_core.replay.fill_model import BOUNDS
from maker_core.replay.inference import cluster_intervals, paired_cells
from maker_core.replay.score import HORIZONS
from maker_core.replay.v2.pull import pull_endpoint
from maker_core.replay.v2.score import DAY_US, from_us

D = Decimal
REPORT_FORMAT = "maker_core.replay.v2.report.v0.1"
SIDECAR_FORMAT = "maker_core.replay.v2.sidecar.v0.1"
POLICIES = ("informed-v0", "blind_re1", "no_quote", "clock_only")
REPORTED_METRICS = ("modeled_net_k1", "modeled_net_k05", "modeled_net_k03")
SUMMED = ("active_seconds", "covered_seconds", "excluded_seconds", "pulled_seconds", "reward_k1", "reward_k05",
          "reward_k03", "nominal_rebate", "settled_inventory_pnl", "cash_hours", "fills", "filled_shares",
          "unresolved_fills", "quotes", "requotes")
ASSUMPTIONS = (
    "Registration draft v2 §5: a band is decided only at its own events; between them its state is carried.",
    "Strictly-through is primary; at-price is sensitivity. Public price paths do not identify queue fills.",
    "Sibling and unfilled remainder cancel immediately, with zero latency; invisible cancels remain unobserved.",
    "Books are held at most 60 seconds, with ten-second submit freshness read at each own event; gaps exclude exposure.",
    "Nominal rebates and modeled liquidity rewards are not payments and never increase replay cash.",
    "Money is exact at 1e-6 pUSD (C5); report quotients are rounded once per band-day.",
    "Inventory starts empty and is held to reconciled settlement or censored at the last supplied day boundary.",
    "Clock matching uses only retrospective pull exposure, not returns; unmatched controls have no intervals.",
    "Cluster minimums and synthetic checks do not establish power, economic edge or live readiness.",
)


def small_cluster_bound(estimate, cluster):
    """§12: estimate - t(0.95, G - 1) x bootstrap SE; G = G_D (date) or min(G_D, G_M) (crossed). Reported only."""
    g = estimate["date_clusters"] if cluster == "date" else min(estimate["date_clusters"], estimate["market_clusters"])
    se, value = estimate.get("bootstrap_standard_error"), estimate.get("estimate")
    lower = None
    if se is not None and value is not None and g >= 2:
        lower = value - float(stdtrit(g - 1, 0.95)) * se
    return dict(lower_bound=lower, clusters=g, t_quantile=None if g < 2 else float(stdtrit(g - 1, 0.95)),
                rule="estimate - t(0.95, G - 1) x bootstrap SE", interpretation="Non-decision sensitivity (C10).")


def inference(scores, matching, *, replicates, seed, check):
    intervals = {}
    for baseline in POLICIES[1:]:
        for metric in REPORTED_METRICS:
            key = baseline + ":" + metric
            if baseline == "clock_only" and matching["status"] != "MATCHED":
                intervals[key] = dict(status="UNMATCHED_CLOCK_CONTROL", intervals=None)
                continue
            cells, excluded = paired_cells(scores["informed-v0"], scores[baseline], metric)
            estimates = cluster_intervals(cells, replicates=replicates, seed=seed, check=check)
            for cluster, estimate in estimates.items():
                estimate["small_cluster"] = small_cluster_bound(estimate, cluster)
            intervals[key] = dict(excluded_market_dates=excluded, intervals=estimates)
    return intervals


def _split(start_us, end_us):
    cursor = start_us
    while cursor < end_us:
        stop = min(end_us, (cursor // DAY_US + 1) * DAY_US)
        yield from_us(cursor).date().isoformat(), cursor, stop
        cursor = stop


def cell_rows(policy, bound, band_days, scorer, markets, pull_cells):
    """One row per market/UTC-date cell: sums of its band-days plus its excluded-interval binding."""
    cells = {}
    for r in band_days:
        key = r["date"], r["market_id"]
        cell = cells.get(key)
        if cell is None:
            cell = cells[key] = dict(date=r["date"], market_id=r["market_id"], policy=policy, fill_bound=bound,
                                     band_days=0, complete_band_days=0, exclusion_reasons=defaultdict(D),
                                     markouts={h: dict(pnl=D(0), shares=D(0), missing_fills=0)
                                               for h in (*HORIZONS, "settlement")},
                                     **{name: D(0) if name not in ("fills", "unresolved_fills", "quotes", "requotes")
                                        else 0 for name in SUMMED},
                                     **{metric: D(0) for metric in REPORTED_METRICS})
        cell["band_days"] += 1
        for name in SUMMED:
            cell[name] += r[name]
        for reason, value in r["excluded_by_reason"].items():
            cell["exclusion_reasons"][reason] += value
        for horizon, m in r["markouts"].items():
            for name in ("pnl", "shares", "missing_fills"):
                cell["markouts"][horizon][name] += m[name]
        complete = r["active_seconds"] and r["status"] == "COVERED" and r["modeled_net_k1"] is not None
        cell["complete_band_days"] += int(bool(complete))
        for metric in REPORTED_METRICS:
            if cell[metric] is not None and r["active_seconds"]:
                cell[metric] = cell[metric] + r[metric] if complete else None
    digests, counts = defaultdict(hashlib.sha256), defaultdict(int)
    for cid in sorted(scorer.excluded):
        for start, end, reason in scorer.excluded[cid]:
            for day, a, b in _split(start, end):
                key = day, markets[cid]
                digests[key].update(canonical_bytes([cid, a, b, reason]))
                counts[key] += 1
    rows = []
    for key in sorted(cells):
        cell = cells[key]
        cell["status"] = ("EXCLUDED" if not cell["covered_seconds"] else
                          "PARTIAL" if cell["excluded_seconds"] else "COVERED")
        cell["exclusion_reasons"] = dict(sorted(cell["exclusion_reasons"].items()))
        cell["excluded_intervals"] = counts.get(key, 0)
        cell["excluded_intervals_sha256"] = digests[key].hexdigest() if key in digests else None
        if policy in ("informed-v0", "clock_only") and pull_cells is not None:
            counts_ = pull_cells.get(f"{key[0]}|{key[1]}")
            if counts_ is not None:
                side = "informed" if policy == "informed-v0" else "clock"
                cell["pull"] = dict(opportunities=counts_["opportunities"], large_moves=counts_["large_moves"],
                                    pulled_minutes=counts_[side + "_pulled"], removed_moves=counts_[side + "_removed"])
        rows.append(cell)
    return rows


class Sidecar:
    """Canonical JSONL, hashed as written; ``path`` None keeps only the hash, bytes and record count."""

    def __init__(self, path=None):
        self.handle = path.open("xb") if path is not None else None
        self.sha, self.bytes, self.records = hashlib.sha256(), 0, 0

    def write(self, value):
        raw = canonical_bytes(value)
        self.sha.update(raw)
        self.bytes += len(raw)
        self.records += 1
        if self.handle is not None:
            self.handle.write(raw)

    def close(self):
        if self.handle is not None:
            self.handle.close()
        return dict(format=SIDECAR_FORMAT, sha256=self.sha.hexdigest(), bytes=self.bytes, records=self.records)


def _config(config):
    return {f.name: getattr(config, f.name) for f in fields(config) if f.name not in ("clock_pulls", "debug", "keep",
                                                                                         "policy", "fill_bound")}


def build_report(run, config, *, replicates=2000, seed=20260926, registration_hash=None, sidecar_path=None,
                 check=lambda: None):
    """Compose the scored report from a finished ``pipeline.Run`` and write its sidecar; returns (report, sidecar)."""
    from maker_core.replay.v2.pipeline import verify_run_binding
    plan, books, passes, matches, markets = run.plan, run.books, run.passes, run.matches, run.markets
    fixture_only = all(d.provenance == "synthetic" for d in plan.days)
    run_binding = verify_run_binding(run, config, scored=not fixture_only)  # owner T2(a): no binding, no report
    sidecar = Sidecar(sidecar_path)
    try:
        sidecar.write(dict(kind="header", format=SIDECAR_FORMAT, days=[d.day.isoformat() for d in plan.days]))
        report = dict(format=REPORT_FORMAT, mode="comparison",
                      status="FIXTURE_ONLY" if fixture_only else "PRE_REGISTERED_REPLAY",
                      pre_registration_sha256=registration_hash, configuration=_config(config),
                      input_hashes={d.day.isoformat(): dict(d.input_hashes) for d in plan.days},
                      run_binding=run_binding, assumptions=ASSUMPTIONS, bounds={})
        for bound in BOUNDS:
            check()
            band_days = {policy: passes[bound][policy].band_days(books, markets) for policy in POLICIES}
            matching = matches[bound]
            pull = pull_endpoint(plan, passes[bound]["informed-v0"].scorer, passes[bound]["clock_only"].scorer,
                                 books, matching, replicates=replicates, seed=seed, check=check)
            traces = {}
            for policy in POLICIES:
                p = passes[bound][policy]
                summary = p.engine.summary()
                summary["excluded_intervals"] = p.scorer.excluded_runs
                traces[policy] = summary
                sidecar.write(dict(kind="pass", **summary))
                for cid in sorted(p.scorer.excluded):
                    for start, end, reason in p.scorer.excluded[cid]:
                        sidecar.write(dict(kind="excluded", fill_bound=bound, policy=policy, condition_id=cid,
                                           start=from_us(start), end=from_us(end), reason=reason))
            for b, number, value, trial in run.trials:
                if b == bound:
                    summary = trial if isinstance(trial, dict) else trial.engine.summary()
                    sidecar.write(dict(kind="clock_trial", round=number, calendar_prefix_fraction=value, **summary))
            sidecar.write(dict(kind="clock_windows", fill_bound=bound,
                               windows=[list(w) for w in passes[bound]["clock_only"].engine.config.clock_pulls]))
            report["bounds"][bound] = dict(
                scores={policy: cell_rows(policy, bound, band_days[policy], passes[bound][policy].scorer, markets,
                                          pull["cells"]) for policy in POLICIES},
                band_days=band_days,
                intervals=inference(band_days, matching, replicates=replicates, seed=seed, check=check),
                clock_match=matching, quote_presence=quote_presence(band_days), pull_efficiency=pull, traces=traces)
    finally:
        binding = sidecar.close()
    report["sidecar"] = binding
    # The frozen decision reads the band-day table as its scores; Clarification 3 fields ride beside it.
    view = dict(report, bounds={b: dict(v, scores=v["band_days"]) for b, v in report["bounds"].items()})
    report["registered_decision"] = registered_decision(view)
    return report, binding


def report_bytes(report) -> bytes:
    return canonical_bytes(report)


