"""Second-candidate registration reader and comparison report.

The first exam's POLICIES, reader, report and CLI are untouched. This module
adds the edge allowlist beside them plus the fill endpoint: settlement markout
per filled share. Enrollment stays with the reviewed APPROVED_REGISTRATIONS.
"""
from collections import defaultdict
from dataclasses import replace
from decimal import Decimal as D
import time

from maker_core.evidence.journal import canonical_bytes, digest
from maker_core.quoting.one_sided import NAME
from maker_core.replay import authorization
from maker_core.replay.approved_registrations import APPROVED_REGISTRATIONS
from maker_core.replay.baselines import matched_clock
from maker_core.replay.bundle import BundleError, Limits, _Reader, _json, sha256
from maker_core.replay.diagnostics import ASSUMPTIONS, coverage_report
from maker_core.replay.engine import replay
from maker_core.replay.fill_model import BOUNDS
from maker_core.replay.inference import cluster_intervals, paired_cells
from maker_core.replay.one_sided import EdgeReplayConfig, edge_replay
from maker_core.replay.report import REPLAY_ASSUMPTIONS, _safe
from maker_core.replay.score import score

EDGE_POLICIES = (NAME, "informed-v0", "no_quote", "blind_re1", "clock_only")
EDGE_ASSUMPTIONS = (
    "One-sided-edge-v0 holds a filled band to reconciled settlement; exit review is advisory and never replayed.",
    "Decidedness direction comes from captured band rows; an unknown or conflicting band shape never quotes a side.",
    "The net screen counts modeled rewards only; recorded expected edge is never credited against hazard.",
    "The clock control is matched to the edge candidate's pull exposure, not to informed-v0's.",
)
FILL_ESTIMAND = "mean over complete market/UTC-day cells of settlement markout per filled share"


def read_edge_authorization(path, expected_hash, *, decision_log=None, frozen_protocol=None,
                            execution_addendum=None, clarification=None):
    """The first exam's checks with the edge policy list; fails before input IO."""
    if not path or expected_hash not in APPROVED_REGISTRATIONS:
        raise BundleError("owner_signed_pre_registration_hash_not_approved")
    reader = _Reader(Limits(8*1024**2+458752, 1, 5), time.monotonic)
    raw = reader.read(path, 8*1024**2)
    if sha256(raw) != expected_hash:
        raise BundleError("pre_registration_hash_mismatch")
    doc = _json(raw)
    if (not isinstance(doc, dict) or doc.get("owner") != APPROVED_REGISTRATIONS[expected_hash]
            or not isinstance(doc.get("hurdles"), dict) or not doc["hurdles"]
            or doc.get("clusters") != ["date", "date_x_market"]
            or doc.get("policies") != list(EDGE_POLICIES)):
        raise BundleError("invalid_signed_pre_registration")
    authorization._verify_decision(doc, reader, decision_log, frozen_protocol, execution_addendum,
                                   authorization._utc_now(), clarification)
    return doc


def fill_markout_cells(result):
    """Settlement value minus fill price, per filled share, per market/UTC-day cell.

    A cell with any unresolved fill is dropped whole; missing never becomes zero.
    """
    totals, shares, bad = defaultdict(D), defaultdict(D), set()
    for fill in result.fills:
        cell = fill.at.date().isoformat(), fill.market_id
        fact = result.settlements.get(fill.condition_id)
        if fact is None:
            bad.add(cell)
            continue
        value = D(str(fact.p_yes if fill.outcome == "YES" else 1 - fact.p_yes))
        totals[cell] += (value - fill.price) * fill.size
        shares[cell] += fill.size
    cells = {cell: float(totals[cell] / shares[cell]) for cell in sorted(shares) if cell not in bad}
    return cells, sorted(bad)


def edge_comparison_report(bundles, config=EdgeReplayConfig(), *, replicates=2000, seed=20260926,
                           registration_hash=None, check=lambda: None):
    if not isinstance(config, EdgeReplayConfig):
        raise BundleError("unsupported_replay_policy")
    bundles = tuple(sorted(bundles, key=lambda b: b.day))
    report = dict(format="maker_core.replay.edge_comparison.v0.1", mode="comparison", candidate=NAME,
        status="FIXTURE_ONLY" if all(b.provenance == "synthetic" for b in bundles) else "PRE_REGISTERED_REPLAY",
        pre_registration_sha256=registration_hash, configuration=config,
        input_hashes={b.day.isoformat(): dict(b.input_hashes) for b in bundles},
        coverage=[coverage_report(b, NAME, check=check) for b in bundles],
        assumptions=(*ASSUMPTIONS[:4], *REPLAY_ASSUMPTIONS, *EDGE_ASSUMPTIONS), bounds={})
    for bound in BOUNDS:
        check()
        cfg = replace(config, fill_bound=bound, clock_pulls=())
        base = cfg.base()
        results = {NAME: edge_replay(bundles, cfg, check=check), "informed-v0": replay(bundles, base, check=check)}
        for policy in ("no_quote", "blind_re1"):
            results[policy] = replay(bundles, replace(base, policy=policy), check=check)
        results["clock_only"], matching = matched_clock(bundles, base, results[NAME], check=check)
        scores = {name: score(results[name], check=check) for name in EDGE_POLICIES}
        intervals = {}
        for baseline in EDGE_POLICIES[1:]:
            for metric in ("modeled_net_k1", "modeled_net_k05"):
                key = baseline + ":" + metric
                if baseline == "clock_only" and matching["status"] != "MATCHED":
                    intervals[key] = dict(status="UNMATCHED_CLOCK_CONTROL", intervals=None)
                    continue
                cells, excluded = paired_cells(scores[NAME], scores[baseline], metric)
                intervals[key] = dict(excluded_market_dates=excluded,
                    intervals=cluster_intervals(cells, replicates=replicates, seed=seed, check=check))
        cells, unresolved = fill_markout_cells(results[NAME])
        fill = cluster_intervals(cells, replicates=replicates, seed=seed, check=check)
        for estimate in fill.values():
            estimate["estimand"] = FILL_ESTIMAND
        report["bounds"][bound] = dict(scores=scores, intervals=intervals, clock_match=matching,
            fill_markout=dict(unresolved_market_dates=unresolved, intervals=fill),
            traces={name: dict(decision_count=len(r.decisions), decision_sha256=digest(r.decisions),
                              final_cash=r.final_cash, fills=r.fills, exclusions=r.exclusions)
                    for name, r in results.items()})
    return report


def edge_report_bytes(report):
    raw = canonical_bytes(report)
    lines = ["# Maker replay report: " + NAME, "", "**" + report["status"] + " - modeled counterfactuals.**", "",
             "No live, promotion or edge verdict follows from replay.", "",
             "Registration SHA-256: " + str(report["pre_registration_sha256"]), ""]
    for bound, result in report["bounds"].items():
        lines += ["## " + bound, "", "Clock match: " + result["clock_match"]["status"], "", "### Paired 90% intervals", ""]
        for comparator, entry in result["intervals"].items():
            if entry.get("intervals") is None:
                lines.append("- " + comparator + ": " + entry["status"])
                continue
            for cluster, e in entry["intervals"].items():
                lines.append(f"- {comparator} / {cluster}: {e['status']}; mean {e['estimate']}; 90% {e['interval']}; "
                             f"dates={e['date_clusters']}, markets={e['market_clusters']}.")
        lines += ["", "### Settlement markout per filled share", ""]
        for cluster, e in result["fill_markout"]["intervals"].items():
            lines.append(f"- {cluster}: {e['status']}; mean {e['estimate']}; 90% {e['interval']}; "
                         f"dates={e['date_clusters']}, markets={e['market_clusters']}.")
        lines.append("- unresolved market-dates: " + _safe(result["fill_markout"]["unresolved_market_dates"]))
        lines.append("")
    lines += ["## Assumptions", "", *("- " + x for x in report["assumptions"]), ""]
    return raw, ("\n".join(lines) + "\n").encode()
