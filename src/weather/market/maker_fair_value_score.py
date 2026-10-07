"""Offline caller for the unchanged 110b T+1/T+2 fair-value pre-registration."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import time

from maker_core.contracts import OutcomeView, SettlementFact, Unavailable
from maker_core.evidence.journal import canonical_bytes, plain
from maker_core.replay.bundle import BundleError, Limits, load_bundle, regular_path, sha256
from maker_core.replay.payloads import decode
from weather.market.maker_fair_value_statistics import BIN_EDGES, REPLICATES, SEED, tables
from weather.market.maker_plugin.fair_value import WeatherFairValue
from weather.market.maker_plugin.inputs import digest, event_identity, timestamp
from weather.market.mg1_metric_guard import MG1Reserved, date_range, refuse_reserved_targets
from weather.market.maker_plugin.universe import WeatherUniverse
from weather.paths import REPO_ROOT


PANEL_START, PANEL_END = date(2026, 9, 25), date(2026, 10, 8)
EARLIEST_DATE = PANEL_END + timedelta(days=1)
PREREGISTRATION = "docs/research/t1-fair-value-preregistration-2026-09-25.md"
# Amendment 2: tied-knot reads are scored as their own strata, never pooled into the primary.
SOURCE_MODELS = {"nbp-v2-piecewise-linear": "nbp", "pit-lead1-normal-fixed-2C-equivalent": "fallback",
                 "nbp-v2-piecewise-linear-atoms": "nbp_atoms",
                 "nbp-v2-piecewise-linear-atoms-resolution-tails": "nbp_resolution_tails"}
SUPPORT_CLOCKS = dict(snapshots="captured_at_utc", bulletins="fetched_at", forecasts="captured_at_utc",
                      source_rows="captured_at_utc", explanations="captured_at_utc")
MAX_BUNDLES, MAX_TOTAL_BYTES, MAX_TOTAL_RECORDS = 256, 512 * 1024**2, 500_000
LIMITATIONS = [
    "Descriptive only: no significance/promotion gate, alpha spend, centre-skew selection or live authorization.",
    "An interval crossing zero is not evidence of an improvement; expect Brier to be worse than the market mid.",
    "UNDERPOWERED when either cluster dimension has fewer than ten unique clusters, including within each stratum.",
    "No numeric detectable effect or power is established by this descriptive protocol; thin/sparse clusters limit precision.",
    "Fallback spread 2 C / 3.6 F is a zero-fit engineering prior, not an estimated climatological error.",
    "Tied-knot NBP reads (Amendment 2) are separate strata, excluded from the primary and pooled tables.",
    "Reliability counts and means weight selected band-hours; Brier first averages bands, then hours within market-day.",
    "Missing exports, hours and settlements are not filled. Coverage denominators describe supplied captures only.",
    "Export hashes bind bytes, not authenticity; reconciled settlement projections rely on the bounded export producer.",
    "Execute the single authorized real read on 2026-10-15 with the replay execution manifest and the same sealed bundles.",
]


def _one(rows, reason):
    unique = {r.payload_sha256: r for r in rows}
    if len(unique) != 1:
        raise ValueError(reason)
    return next(iter(unique.values()))


class Panel:
    """Index retained evidence, with explicit availability checks at every query."""
    def __init__(self, bundles, now, check):
        self.check, self.now = check, now
        self.descriptors, self.views, self.support, self.facts = (defaultdict(list) for _ in range(4))
        self.books = defaultdict(lambda: defaultdict(list))
        self.identities, self.windows = {}, {}
        self.coverage = Counter()
        records = []
        for bundle in bundles:
            for condition in bundle.conditions:
                key = (bundle.day, condition.condition_id)
                if key in self.windows:
                    raise ValueError("overlapping_condition_exports")
                self.windows[key] = condition
            records.extend(bundle.records)
        records.sort(key=lambda r: (r.captured_at, r.sequence, r.condition_id, r.kind, r.payload_sha256))
        for row in records:
            check()
            if row.kind != "descriptor":
                continue
            value = decode(row)
            market = value.market
            spec, target = event_identity(market.event_id)
            condition = self.windows[(row.captured_at.date(), row.condition_id)]
            identity = (market.event_id, spec.id, target.isoformat(), market.native_unit,
                        tuple(sorted(market.outcome_tokens.items())))
            expected_close = datetime.combine(target + timedelta(days=1), datetime.min.time(), spec.tz)
            if (condition.market_id != spec.id or condition.domain_id != "weather"
                    or market.domain_id != "weather" or market.native_unit != spec.unit
                    or market.group_relation != "partition"
                    or market.close_at_utc != expected_close
                    or (row.condition_id in self.identities and self.identities[row.condition_id] != identity)):
                raise ValueError("descriptor_identity_mismatch")
            self.identities[row.condition_id] = identity
            self.descriptors[row.condition_id].append((row, value))
        for row in records:
            check()
            if row.condition_id not in self.identities:
                raise ValueError("missing_descriptor_identity")
            event = self.identities[row.condition_id][0]
            if row.kind == "plugin_input" and row.payload.get("source") in SUPPORT_CLOCKS:
                source = row.payload["source"]
                raw = plain(row.payload["record"])
                original = timestamp(row.payload["original_captured_at"])
                if original != timestamp(raw[SUPPORT_CLOCKS[source]]) or original > row.captured_at:
                    raise ValueError("support_capture_identity_mismatch")
                spec, target = event_identity(event)
                if source == "bulletins":
                    matches = raw.get("station_id") == spec.icao and raw.get("target_date") == target.isoformat()
                else:
                    matches = raw.get("event_slug") == event
                if not matches:
                    raise ValueError("support_event_identity_mismatch")
                self.support[event].append((row.captured_at, source, raw))
            elif row.kind == "book":
                self.books[(event, row.captured_at)][row.condition_id].append(row)
            elif row.kind == "outcome_view":
                self.views[row.condition_id].append(row)
            elif row.kind == "settlement":
                self.facts[row.condition_id].append(row)

    def descriptor(self, cid, at):
        eligible = [(r, d) for r, d in self.descriptors[cid] if r.captured_at <= at]
        if not eligible:
            raise ValueError("missing_point_in_time_descriptor")
        latest = max(r.captured_at for r, _ in eligible)
        row = _one([r for r, _ in eligible if r.captured_at == latest], "conflicting_descriptor")
        return decode(row)

    def candidate(self, event, at, books):
        spec, target = event_identity(event)
        lead = (target - at.astimezone(spec.tz).date()).days
        retained = defaultdict(dict)
        for available, source, raw in self.support[event]:
            if available <= at:
                retained[source][digest(raw)] = raw
        support = {source: [rows[k] for k in sorted(rows)] for source, rows in retained.items()}
        universe = WeatherUniverse(band_rows=support.get("snapshots", ()))
        bands = universe.bands(event, at)
        bounds = sorted(bands.values())
        if (not bounds or bounds[0][0] != -math.inf or bounds[-1][1] != math.inf
                or any(a[1] != b[0] for a, b in zip(bounds, bounds[1:]))):
            raise ValueError("incomplete_event_partition")
        if set(books) != set(bands):
            raise ValueError("incomplete_captured_minute")
        provider = WeatherFairValue(universe, **support)
        result, sources = [], set()
        for cid in sorted(bands):
            self.check()
            condition = self.windows[(at.date(), cid)]
            if not condition.active_from <= at < condition.active_until:
                raise ValueError("outside_active_interval")
            descriptor = self.descriptor(cid, at)
            if descriptor.horizon_days != lead or descriptor.market.event_id != event:
                raise ValueError("local_lead_identity_mismatch")
            book = decode(_one(books[cid], "conflicting_book_capture"))
            if book.as_of_utc != at or not book.yes_bids or not book.yes_asks:
                raise ValueError("missing_contemporaneous_two_sided_mid")
            bid, ask = book.yes_bids[0][0], book.yes_asks[0][0]
            if bid > ask:
                raise ValueError("crossed_book")
            eligible = [r for r in self.views[cid] if r.captured_at == at]
            if not eligible:
                raise ValueError("missing_contemporaneous_fair_value")
            view = decode(_one(eligible, "conflicting_fair_value"))
            if isinstance(view, Unavailable):
                raise ValueError("fair_value_unavailable:" + view.reason)
            rebuilt = provider.evaluate(descriptor.market, at)
            if isinstance(rebuilt, Unavailable):
                raise ValueError("input_unavailable:" + rebuilt.reason)
            if (not isinstance(view, OutcomeView) or plain(view) != plain(rebuilt)
                    or view.as_of_utc != at or not at < view.valid_until_utc
                    or view.calibration_grade != "none" or view.model_id not in SOURCE_MODELS):
                raise ValueError("fair_value_input_binding_mismatch")
            sources.add(SOURCE_MODELS[view.model_id])
            result.append(dict(condition_id=cid, probability=view.p_yes, stdev=view.stdev,
                               mid=float((bid + ask) / 2), inputs_hash=view.inputs_hash))
        if len(sources) != 1:
            raise ValueError("mixed_event_estimators")
        source = sources.pop()
        if source == "fallback" and lead != 1:
            raise ValueError("fallback_requires_lead_one")
        return dict(event_id=event, market_id=spec.id, target_date=target.isoformat(), lead=lead,
                    source=source, captured_at=at.isoformat(), bands=result)

    def settle(self, row):
        # MG-1: refuse before this view is joined to any settlement fact.
        refuse_reserved_targets([row["target_date"]], entry="maker_fair_value_score.settle")
        facts = []
        for band in row["bands"]:
            eligible = [r for r in self.facts[band["condition_id"]] if r.captured_at <= self.now]
            if not eligible:
                raise ValueError("missing_reconciled_settlement")
            latest = max(r.captured_at for r in eligible)
            fact = decode(_one([r for r in eligible if r.captured_at == latest], "conflicting_settlement"))
            if (not isinstance(fact, SettlementFact) or fact.p_yes not in (0, 1)
                    or fact.as_of_utc < self.descriptor(band["condition_id"], self.now).market.close_at_utc
                    or re.fullmatch(r"[0-9a-f]{64}", fact.source_hashes.get("ledger", "")) is None
                    or re.fullmatch(r"sha256:[0-9a-f]{64}", fact.source_hashes.get("revision", "")) is None):
                raise ValueError("settlement_identity_unbound")
            facts.append(fact)
        if len({tuple(sorted(f.source_hashes.items())) for f in facts}) != 1 or sum(f.p_yes for f in facts) != 1:
            raise ValueError("incomplete_or_inconsistent_event_settlement")
        for band, fact in zip(row["bands"], facts):
            band.update(observed_yes=fact.p_yes, settlement_hashes=dict(fact.source_hashes))

    def select(self):
        selected, exclusions, seen_hours = {}, Counter(), set()
        for (event, at), books in sorted(self.books.items(), key=lambda item: (item[0][1], item[0][0])):
            self.check()
            spec, target = event_identity(event)
            lead = (target - at.astimezone(spec.tz).date()).days
            self.coverage["captured_event_instants"] += 1
            if not PANEL_START <= target <= PANEL_END:
                exclusions["target_outside_frozen_panel"] += 1
                continue
            if lead not in (1, 2):
                exclusions["local_lead_out_of_scope"] += 1
                continue
            self.coverage["eligible_event_instants"] += 1
            key = event, lead, at.replace(minute=0, second=0, microsecond=0)
            seen_hours.add(key)
            if key in selected:
                self.coverage["later_captures_in_selected_hour"] += 1
                continue
            try:
                selected[key] = self.candidate(event, at, books)
            except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
                exclusions[str(exc)] += 1
        self.coverage.update(observed_eligible_event_hours=len(seen_hours),
                             selected_complete_event_hours=len(selected),
                             hours_without_complete_minute=len(seen_hours - set(selected)))
        rows, settlement_exclusions = [], Counter()
        # Sampling is fixed before labels are read; a missing label never picks a later minute.
        for key in sorted(selected):
            row = selected[key]
            try:
                self.settle(row)
            except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
                settlement_exclusions[str(exc)] += 1
                continue
            rows.append(row)
        self.coverage["scored_event_hours"] = len(rows)
        return rows, dict(sorted(exclusions.items())), dict(sorted(settlement_exclusions.items()))


def score(bundle_paths, *, code_tip, now=None):
    """Verify and score explicit bundles. Clock injection is for unit fixtures only."""
    # MG-1: the declared target panel is checked before any bundle, view or settlement is opened.
    refuse_reserved_targets(date_range(PANEL_START, PANEL_END), entry="maker_fair_value_score.score")
    now = timestamp(now or datetime.now(timezone.utc))
    if now.date() < EARLIEST_DATE:
        raise ValueError("scoring_before_registered_earliest_date:2026-10-09")
    if re.fullmatch(r"[0-9a-f]{40}", code_tip) is None:
        raise ValueError("exact_code_tip_required")
    if not 1 <= len(bundle_paths) <= MAX_BUNDLES:
        raise ValueError("bundle_count_cap")
    started = time.monotonic()

    def check():
        if time.monotonic() - started >= 300:
            raise ValueError("scoring_time_cap")

    bundles, hashes, total_bytes, total_records = [], set(), 0, 0
    for path in bundle_paths:
        check()
        remaining = MAX_TOTAL_BYTES - total_bytes
        if remaining <= 0:
            raise ValueError("panel_byte_cap")
        bundle = load_bundle(Path(path), limits=Limits(max_bytes=min(64 * 1024**2, remaining)))
        # MG-1 second line: a bundle captured on a reserved day is never indexed or joined.
        refuse_reserved_targets([bundle.day], entry="maker_fair_value_score.bundle_day")
        if bundle.day >= now.date() or bundle.sealed_at > now:
            raise ValueError("bundle_not_closed_at_scoring")
        manifest = bundle.input_hashes["bundle.json"]
        if manifest in hashes:
            raise ValueError("duplicate_bundle")
        hashes.add(manifest)
        total_bytes += bundle.input_bytes
        total_records += len(bundle.records)
        if total_records > MAX_TOTAL_RECORDS:
            raise ValueError("panel_record_cap")
        bundles.append(bundle)
    if len({b.provenance for b in bundles}) != 1:
        raise ValueError("mixed_synthetic_and_captured_inputs")
    panel = Panel(bundles, now, check)
    rows, exclusions, settlement_exclusions = panel.select()
    result = dict(status="DESCRIPTIVE_ONLY", provenance=bundles[0].provenance, code_tip=code_tip,
        preregistration=dict(path=PREREGISTRATION, sha256=sha256((REPO_ROOT / PREREGISTRATION).read_bytes()),
                            target_start=str(PANEL_START), target_end=str(PANEL_END), earliest_date=str(EARLIEST_DATE),
                            bootstrap_replicates=REPLICATES, bootstrap_seed=SEED, reliability_edges=BIN_EDGES),
        exports=[dict(day=str(b.day), hashes=dict(b.input_hashes), bytes=b.input_bytes)
                 for b in sorted(bundles, key=lambda b: (b.day, b.input_hashes["bundle.json"]))],
        coverage=dict(sorted(panel.coverage.items())), capture_exclusions=exclusions,
        settlement_exclusions=settlement_exclusions, selected_hours=rows,
        limitations=LIMITATIONS, tables=tables(rows))
    observed_dates = {r["target_date"] for r in rows}
    result["coverage"]["unscored_target_dates"] = [str(PANEL_START + timedelta(days=i))
        for i in range((PANEL_END - PANEL_START).days + 1) if str(PANEL_START + timedelta(days=i)) not in observed_dates]
    check()
    return result


def markdown(report):
    lines = ["# T+1/T+2 fair-value reliability", "", "**DESCRIPTIVE ONLY — no promotion or live authorization.**", "",
             f"Provenance: {report['provenance']}; code tip: `{report['code_tip']}`.", "",
             "| Stratum | Status | Dates | Markets | Market-days | Hours | Provider Brier | Mid Brier | Difference | Crossed 90% | Date-only 90% |",
             "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |"]

    def fmt(value):
        return "unavailable" if value is None else f"{value:.8g}"

    def interval(value):
        return "unavailable" if value is None else "[" + ", ".join(map(fmt, value)) + "]"

    for name, table in report["tables"].items():
        b = table["brier"]
        cells = [name, table["status"], *[str(table[k]) for k in ("date_clusters", "market_clusters", "market_days", "hours")]]
        cells += [fmt(b[k]["estimate"]) if b else "unavailable" for k in ("provider", "mid", "provider_minus_mid")]
        cells += [interval(b["provider_minus_mid"][k]["interval_90"]) if b else "unavailable" for k in ("crossed", "date_only")]
        lines.append("| " + " | ".join(cells) + " |")
    for name, table in report["tables"].items():
        lines += ["", f"## {name}", "", table.get("interpretation", "No paired observations."), "",
                  "| Probability bin | Band-hours | Mean p (crossed / date-only 90%) | YES frequency (crossed / date-only 90%) | Mean stdev (crossed / date-only 90%) |",
                  "| --- | ---: | --- | --- | --- |"]
        for b in table["reliability"]:
            cells = [f"[{b['lower']:.1f}, {b['upper']:.1f}" + ("]" if b["upper_inclusive"] else ")"), str(b["count"])]
            for metric in ("mean_probability", "observed_yes_frequency", "mean_declared_stdev"):
                v = b[metric]
                cells.append(fmt(v["estimate"]) + " " + " / ".join(interval(v[k]["interval_90"]) for k in ("crossed", "date_only")))
            lines.append("| " + " | ".join(cells) + " |")
    lines += ["", "## Coverage and exclusions", "", "```json", json.dumps({k: report[k] for k in
              ("coverage", "capture_exclusions", "settlement_exclusions")}, indent=2, sort_keys=True), "```", "",
              "## Limitations", "", *["- " + text for text in report["limitations"]], "",
              "JSON retains export hashes, selected captures, settlement bindings, market-day scores and valid/undefined replicate counts.", ""]
    return "\n".join(lines)


def main(argv=None):
    # MG-1: refused before arguments are parsed or any path is touched; one line, exit 2.
    try:
        refuse_reserved_targets(date_range(PANEL_START, PANEL_END), entry="maker_fair_value_score.main")
    except MG1Reserved as exc:
        sys.stderr.write(f"fair-value score refused: MG1Reserved: {exc}\n")
        raise SystemExit(2) from None
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", action="append", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="new report directory; inputs remain read-only")
    args = parser.parse_args(argv)
    try:
        # Check date before opening, enumerating or hashing any supplied evidence.
        if datetime.now(timezone.utc).date() < EARLIEST_DATE:
            raise ValueError("scoring_before_registered_earliest_date:2026-10-09")
        output = regular_path(args.out)
        if output.exists() or not output.parent.is_dir():
            raise ValueError("new_output_directory_required")
        for source in args.bundle:
            source = regular_path(source)
            if output == source or output.is_relative_to(source) or source.is_relative_to(output):
                raise ValueError("output_input_overlap")
        tip = subprocess.check_output(["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"], text=True).strip()
        report = score(args.bundle, code_tip=tip)
        implementation = [*(REPO_ROOT / "src/weather/market").glob("maker_fair_value_*.py"),
                          *(REPO_ROOT / "src/weather/market/maker_plugin").glob("*.py"),
                          REPO_ROOT / "src/maker_core/replay/bundle.py",
                          REPO_ROOT / "src/maker_core/replay/payloads.py"]
        report["implementation_hashes"] = {str(p.relative_to(REPO_ROOT)).replace("\\", "/"): sha256(p.read_bytes())
            for p in sorted(implementation)}
        json_bytes, md_bytes = canonical_bytes(report), markdown(report).encode("utf-8")
        output.mkdir()
        for name, raw in (("report.json", json_bytes), ("report.md", md_bytes)):
            with (output / name).open("xb") as handle:
                handle.write(raw)
    except (ValueError, KeyError, TypeError, ArithmeticError, OSError, subprocess.SubprocessError, BundleError) as exc:
        parser.exit(2, f"fair-value score refused: {type(exc).__name__}: {exc}\n")
    print(json.dumps({"status": report["status"], "coverage": report["coverage"]}, sort_keys=True))
    return 0
