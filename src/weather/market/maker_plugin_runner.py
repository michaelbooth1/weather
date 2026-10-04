"""Offline composition of captured weather providers and the pure maker policy.

This is a diagnostic caller, outside the provider-adapter import boundary.
It does not simulate fills, inventory, account state or realized economics.
"""
from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path

from maker_core.contracts import OutcomeView, SettlementFact, Unavailable
from maker_core.quoting.policy import Book, DecisionInputs, Portfolio, RewardTerms, decide, informed_v0
from weather.market.market_registry import BUILTIN_SPECS
from weather.market.maker_plugin.clock import WeatherInformationClock
from weather.market.maker_plugin.fair_value import WeatherFairValue
from weather.market.maker_plugin.inputs import body, event_identity, latest, timestamp
from weather.market.maker_plugin.settlement import WeatherSettlement
from weather.market.maker_plugin.universe import WeatherUniverse
from weather.market.maker_plugin_capture import Reader, Segment, StopRun, encoded, regular_path, sealed_segments
from weather.market.maker_plugin_sources import COVERAGE_KEYS, Sources, point_in_time_count, reason
from weather.schema_registry import schema_version

DEFAULT_CACHE_BYTES = 512 * 1024**2


def plain(value):
    if is_dataclass(value):
        return {f.name: plain(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Mapping):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def envelope(payload, now, kind):
    raw = encoded(payload)
    return dict(captured_at_utc=now.isoformat(), kind=kind, http_status=200, body_stored=True,
                body_utf8=raw.decode(), response_sha256=hashlib.sha256(raw).hexdigest())


def increment(counts, key, amount=1):
    # Corrupt inputs cannot grow an unbounded terminal summary.
    key = str(key)[:120]
    counts[key if key in counts or len(counts) < 64 else "other"] += amount


class Report:
    RESERVE = 32768  # Included in the combined JSON + Markdown byte limit.

    def __init__(self, output, limit, summary):
        self.output, self.limit, self.summary = output, limit, summary
        output.mkdir(parents=True, exist_ok=True)
        self.path = output / "report.json"
        with self.path.open("xb") as handle:
            handle.write(b'{"records":[')
        prefix = b"# Weather plugin diagnostic records\n\n[Run summary](#weather-plugin-dry-run) follows the records.\n"
        with (output / "report.md").open("xb") as handle:
            handle.write(prefix)
        self.size, self.count = len(b'{"records":[') + len(prefix), 0

    def append(self, record):
        raw = (b"," if self.count else b"") + encoded(record)
        mass = record["probability_mass"]
        lines = ["", f'## {record["event"]} at {record["as_of_utc"]}', "",
                 f'Segment: {record["segment"]}; split minute: {record["split_minute"]}.',
                 f'Probability sum: {mass["sum_available"]:.12g}; available/expected bands: '
                 f'{mass["available_bands"]}/{mass["expected_bands"]}; complete: {mass["complete"]}.', "",
                 "Input coverage (point-in-time / loaded rows): " + "; ".join(
                     f'{k} {v["point_in_time_rows"]}/{v["loaded_rows"]}'
                     for k, v in record["source_coverage"].items()) + ".", "",
                 "| Condition | Legs | Policy/input reasons |", "| --- | ---: | --- |"]
        for outcome in record["outcomes"]:
            codes = outcome.get("decision", {}).get("reasons", []) + outcome["unavailable"]
            safe_codes = "; ".join(codes).replace("|", "/").replace("\n", " ")[:1000]
            lines.append(f'| {outcome["condition_id"]} | {outcome.get("leg_count", "not evaluated")} | {safe_codes} |')
        md = ("\n".join(lines) + "\n").encode()
        if self.size + len(raw) + len(md) + self.RESERVE > self.limit:
            raise StopRun("output_byte_cap")
        with self.path.open("ab") as handle:
            handle.write(raw)
        with (self.output / "report.md").open("ab") as handle:
            handle.write(md)
        self.size += len(raw) + len(md)
        self.count += 1

    def finish(self, reader):
        self.summary["records_written"] = self.count
        self.summary["input_bytes_read"] = reader.bytes_read
        self.summary["elapsed_seconds"] = round(reader.clock() - reader.started, 6)
        self.summary["output_bytes"] = 0
        # Both outputs carry identical counters; the byte count includes itself.
        for _ in range(8):
            md = markdown(self.summary).encode()
            tail = b'],"summary":' + encoded(self.summary) + b"}\n"
            total = self.size + len(tail) + len(md)
            if self.summary["output_bytes"] == total:
                break
            self.summary["output_bytes"] = total
        if total > self.limit:
            raise RuntimeError("terminal_report_reservation_exceeded")
        with self.path.open("ab") as handle:
            handle.write(tail)
        with (self.output / "report.md").open("ab") as handle:
            handle.write(md)


def markdown(summary):
    lines = ["# Weather plugin dry run", "", "**" + summary["status"] + "**", "",
             "Offline diagnostics; no fills, account/portfolio replay, scoring or edge claim.",
             "Detailed descriptors, clocks, fair values, settlements, mass sums and decisions are in report.json.", ""]
    for name in ("date", "profile", "stop_reason", "records_written", "elapsed_seconds", "input_bytes_read", "output_bytes"):
        lines.append(f"- {name}: {summary.get(name)}")
    lines += ["", "## Coverage and joins", "", "| Source / join | Count |", "| --- | ---: |"]
    lines += [f"| {key} | {value} |" for key, value in sorted(summary["coverage"].items())]
    for title, key in (("Unavailable and input reasons", "unavailable"), ("Policy reason codes", "decision_reasons"),
                       ("Leg counts", "leg_counts"), ("Probability mass coverage", "mass_coverage")):
        lines += ["", "## " + title, "", "| Reason | Count |", "| --- | ---: |"]
        lines += [f"| {k} | {v} |" for k, v in sorted(summary[key].items())]
    lines += ["", "## Diagnostic assumptions", "", summary["assumptions"], ""]
    return "\n".join(lines)


class CaptureIndex:
    """One pass over a verified segment; lookups equal the former full scans.

    Each lookup returns every captured row at the newest clock at or before the
    decision time, so ``latest`` still refuses same-clock conflicts. A body that
    cannot be decoded poisons every later lookup of its kind, as a scan would.
    """
    def __init__(self, captures):
        self.discovery, self.books, self.rewards = [], {}, {}
        self.corrupt = {"books": [], "rewards": []}
        for capture in captures:
            when = timestamp(capture["captured_at_utc"])
            kind = capture["kind"]
            if kind == "discovery":
                self.discovery.append((when, capture))
                continue
            try:
                payload = body(capture)
                if kind == "books":
                    rows = [(str(book["asset_id"]), book) for book in payload]
                    for token, book in rows:
                        self.books.setdefault(token, []).append((when, capture["captured_at_utc"], book))
                else:
                    rows = [(record["condition_id"].lower(), record) for record in payload["data"]]
                    for cid, record in rows:
                        self.rewards.setdefault(cid, []).append(
                            (when, dict(captured_at_utc=capture["captured_at_utc"], record=record)))
            except (ValueError, KeyError, TypeError, AttributeError):
                self.corrupt[kind].append(when)

    def _clean(self, kind, now):
        if any(when <= now for when in self.corrupt[kind]):
            raise ValueError("captured_" + kind + "_malformed")

    def book_rows(self, token, now):
        self._clean("books", now)
        rows = [(when, captured, book) for when, captured, book in self.books.get(token, ()) if when <= now]
        newest = max((when for when, _, _ in rows), default=None)
        return [(captured, book) for when, captured, book in rows if when == newest]

    def book_envelopes(self, tokens, now):
        grouped = {}
        for token in tokens:
            for captured, book in self.book_rows(token, now):
                grouped.setdefault(captured, []).append(book)
        return [envelope(books, timestamp(captured), "books") for captured, books in sorted(grouped.items())]

    def reward_rows(self, cid, now):
        self._clean("rewards", now)
        return [row for when, row in self.rewards.get(cid, ()) if when <= now]


def reward_terms(index, cid, now):
    candidates = index.reward_rows(cid, now)
    if not candidates:
        return None
    selected = latest(candidates, now)
    row = selected["record"]
    rates = [Decimal(str(r["rate_per_day"])) for r in row.get("rewards_config", [])
             if str(r["start_date"])[:10] <= now.date().isoformat() <= str(r["end_date"])[:10]]
    return RewardTerms(timestamp(selected["captured_at_utc"]), Decimal(str(row["rewards_min_size"])),
                       Decimal(str(row["rewards_max_spread"])), sum(rates, Decimal(0)))


def captured_book(index, market, now):
    selected = []
    for outcome in ("YES", "NO"):
        rows = [dict(captured_at_utc=captured, book=book)
                for captured, book in index.book_rows(market.outcome_tokens[outcome], now)]
        selected.append(latest(rows, now))
    if any(r["book"]["market"].lower() != market.condition_id for r in selected):
        raise ValueError("captured_condition_mismatch")
    levels = [tuple((Decimal(str(v["price"])), Decimal(str(v["size"]))) for v in row["book"][side])
              for row in selected for side in ("bids", "asks")]
    return Book(min(timestamp(r["captured_at_utc"]) for r in selected), *levels)


def band_tokens(band):
    tokens = band.get("clobTokenIds")
    try:
        tokens = json.loads(tokens) if isinstance(tokens, str) else tokens
        return [str(token) for token in tokens]
    except (ValueError, TypeError):
        return []  # The universe refuses the malformed mapping itself.


def providers(support):
    """Built once per cached event: constructors copy their inputs defensively."""
    if "providers" not in support:
        universe = WeatherUniverse(band_rows=support["band_rows"])
        support["providers"] = (
            WeatherFairValue(universe, **{k: support[k] for k in (
                "bulletins", "forecasts", "snapshots", "explanations", "source_rows")}),
            WeatherInformationClock(universe, triggers=support["triggers"], bulletins=support["bulletins"]),
            WeatherSettlement(universe, ledger_rows=support["ledger_rows"]))
        # The providers own copies now; keep one copy per cached event, not two.
        support.update({name: () for name, _ in COVERAGE_KEYS})
    return support["providers"]


def evaluate_event(index, event_capture, now, sources, reader, hazard):
    event = event_capture["event"]
    slug = event["slug"]
    spec, target = event_identity(slug)
    support = sources.for_event(slug)
    bad_sources = set(support["bad_sources"])
    for error in support["nbp_errors"]:
        try:
            if timestamp(error["captured_at_utc"]) <= now:
                bad_sources.add("nbp")
        except (ValueError, KeyError, TypeError):
            bad_sources.add("nbp")  # Unknown availability cannot be guessed.
    source_coverage = {name: {"loaded_rows": support["loaded_rows"][name],
                              "point_in_time_rows": point_in_time_count(support["coverage_times"][name], now)}
                       for name, _ in COVERAGE_KEYS}
    provider, clock, settlement = providers(support)
    outcomes, probabilities = [], []
    expected = sum(bool(r.get("active")) and not r.get("closed") and r.get("enableOrderBook") is not False
                   for r in event["markets"])
    for band in event["markets"]:
        reader.check()
        if band.get("closed") or not band.get("active") or band.get("enableOrderBook") is False:
            continue
        cid = str(band.get("conditionId", "")).lower()
        entry = {"condition_id": cid, "unavailable": [], "joins": {}}
        try:
            # Isolate missing books for one band; siblings still retain the full
            # captured partition for fair-value mass calculation.
            single = envelope([dict(event, markets=[band])], timestamp(event_capture["captured_at_utc"]), "discovery")
            books = index.book_envelopes(band_tokens(band), now)
            descriptor = WeatherUniverse(discovery=[single], books=books,
                                         band_rows=support["band_rows"]).describe(cid, now)
            entry["descriptor"] = plain(descriptor)
            entry["joins"]["descriptor"] = True
        except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
            entry["unavailable"].append("descriptor:" + reason(exc))
            entry["joins"]["descriptor"] = False
            outcomes.append(entry)
            continue
        view = provider.evaluate(descriptor, now)
        if bad_sources & {"nbp", "nbp_manifests", "forecasts", "snapshots", "explanations", "observation_sources"}:
            view = Unavailable("corrupt_supporting_input", now, kind="corrupt")
        reader.check()
        entry["fair_value"] = plain(view)
        entry["joins"]["fair_value"] = isinstance(view, OutcomeView)
        if isinstance(view, Unavailable):
            entry["unavailable"].append("fair_value:" + view.reason)
        else:
            probabilities.append(view.p_yes)
        try:
            if bad_sources & {"triggers", "nbp", "nbp_manifests"}:
                raise ValueError("corrupt_clock_input")
            events = clock.upcoming((descriptor,), now - timedelta(minutes=10), now + timedelta(minutes=3))
            events += clock.observe((descriptor,), now)
            entry["clock_events"] = plain(events)
            entry["joins"]["clock"] = True
        except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
            entry["unavailable"].append("clock:" + reason(exc))
            entry["joins"]["clock"] = False
            outcomes.append(entry)
            continue  # Unknown veto evidence cannot be treated as an empty clock.
        fact = settlement.resolve(descriptor, now)
        entry["settlement"] = plain(fact)
        entry["joins"]["settlement_fact"] = isinstance(fact, SettlementFact)
        try:
            book = captured_book(index, descriptor, now)
            terms = reward_terms(index, cid, now)
            entry["joins"].update(book=True, rewards=terms is not None)
            # Explicit hypothetical caps only. Each decision starts independently.
            portfolio = Portfolio(Decimal(100), Decimal(0), Decimal(100), Decimal(100),
                                  Decimal(0), Decimal(100), Decimal(0), Decimal(100))
            decision = decide(DecisionInputs(descriptor, now, book, terms, view, portfolio,
                (target - now.astimezone(spec.tz).date()).days, events, informed_v0, hazard))
            entry["decision"] = plain(decision)
            entry["leg_count"] = len(decision.legs)
        except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
            entry["unavailable"].append("decision_input:" + reason(exc))
        reader.check()
        outcomes.append(entry)
    return dict(market=spec.id, event=slug, as_of_utc=now.isoformat(), minute_utc=now.isoformat()[:16],
                lead_days=(target - now.astimezone(spec.tz).date()).days,
                band_token_batch_utc=support["band_token_batch_utc"],
                outcomes=outcomes, source_coverage=source_coverage, probability_mass={"sum_available": math.fsum(probabilities),
                "available_bands": len(probabilities), "expected_bands": expected,
                "complete": len(probabilities) == expected and expected > 0})


def process(reader, sources, report, day, markets, hazard, stride=1):
    summary = report.summary
    seen = set()
    for sealed, folder, manifest in sealed_segments(reader, day):
        reader.check()
        try:
            captures = Segment(reader, folder, manifest).captures()
            if any(timestamp(c["captured_at_utc"]).date().isoformat() != day or
                   timestamp(c["captured_at_utc"]) > sealed for c in captures):
                raise ValueError("capture_outside_sealed_date_or_clock")
            index = CaptureIndex(captures)
        except (ValueError, KeyError, TypeError, OSError, EOFError) as exc:
            increment(summary["unavailable"], "segment:" + reason(exc))
            reader.coverage["segments.rejected"] += 1
            continue
        reader.coverage["segments.verified"] += 1
        # Last captured books clock in each segment-minute. Segment is retained
        # in the report key: split-minute segments are explicit, never overwritten.
        minutes = {}
        for c in captures:
            if c["kind"] == "books":
                now = timestamp(c["captured_at_utc"])
                minutes[now.replace(second=0, microsecond=0)] = now
        events, cursor = {}, 0
        for minute, now in sorted(minutes.items()):
            reader.check()
            if (minute.hour * 60 + minute.minute) % stride:
                reader.coverage["segment_minutes.skipped_by_stride"] += 1
                continue  # Discovery below is cumulative, so a skipped minute loses nothing.
            while cursor < len(index.discovery) and index.discovery[cursor][0] <= now:
                capture = index.discovery[cursor][1]
                for event in body(capture):
                    events.setdefault(event["slug"], []).append(
                        dict(captured_at_utc=capture["captured_at_utc"], event=event))
                cursor += 1
            reader.coverage["segment_minutes"] += 1
            if not events:
                increment(summary["unavailable"], "discovery:missing_point_in_time_input")
            for slug, candidates in sorted(events.items()):
                reader.check()
                try:
                    spec, target = event_identity(slug)
                    lead = (target - now.astimezone(spec.tz).date()).days
                    if spec.id not in markets or not 0 <= lead <= 2:
                        continue
                    result = evaluate_event(index, latest(candidates, now), now, sources, reader, hazard)
                except (ValueError, KeyError, TypeError, OSError, EOFError) as exc:
                    increment(summary["unavailable"], "event:" + reason(exc))
                    continue
                result["segment"] = folder.name
                result["manifest_canonical_sha256"] = hashlib.sha256(encoded(manifest)).hexdigest()
                key = (slug, now.replace(second=0, microsecond=0))
                result["split_minute"] = key in seen
                report.append(result)
                seen.add(key)
                mass = result["probability_mass"]
                mass_key = "partial" if not mass["complete"] else (
                    "complete_unit_mass" if abs(mass["sum_available"] - 1) <= 1e-9 else "complete_nonunit_mass")
                increment(summary["mass_coverage"], mass_key)
                for entry in result["outcomes"]:
                    for code in entry["unavailable"]:
                        increment(summary["unavailable"], code)
                        # Bounded: reason codes are sanitized, leads are 0..2.
                        reader.coverage[("unavailable.lead" + str(lead) + "." + code)[:120]] += 1
                    for name, success in entry["joins"].items():
                        reader.coverage["join." + name + (".matched" if success else ".missing")] += 1
                    if "decision" in entry:
                        summary["leg_counts"][str(entry["leg_count"])] += 1
                        for code in entry["decision"]["reasons"]:
                            increment(summary["decision_reasons"], code)
                    else:
                        reader.coverage["decisions.not_evaluable"] += 1


def run(args, *, clock=None):
    output, root = Path(args.output).absolute(), Path(args.data_root).absolute()
    regular_path(root, root)
    regular_path(output, output)
    if not root.is_dir():
        raise ValueError("data_root_missing")
    if root.is_relative_to(output) or any(output.is_relative_to(root / name)
                                         for name in ("snapshots", "settlements", "maker_evidence", "forecast_payload_cas")):
        raise ValueError("output_overlaps_inputs")
    if output.exists() and any(output.iterdir()):
        raise ValueError("output_must_be_new_or_empty")
    if not math.isfinite(args.max_seconds) or args.max_seconds <= 0 or args.max_output_bytes < 65536 or args.max_input_bytes <= 0:
        raise ValueError("invalid_caps_minimum_output_65536")
    if args.hypothetical_hazard_per_minute is not None and (
        not math.isfinite(args.hypothetical_hazard_per_minute) or args.hypothetical_hazard_per_minute < 0
    ):
        raise ValueError("invalid_hypothetical_hazard")
    max_cache_bytes = getattr(args, "max_cache_bytes", DEFAULT_CACHE_BYTES)
    if max_cache_bytes <= 0:
        raise ValueError("invalid_cache_budget")
    stride = getattr(args, "minute_stride", 1)
    if isinstance(stride, bool) or not isinstance(stride, int) or not 1 <= stride <= 60:
        raise ValueError("invalid_minute_stride")
    reader = Reader(root, args.max_seconds, args.max_input_bytes, **({"clock": clock} if clock else {}))
    sources = Sources(reader, args.date, args.markets, max_cache_bytes)
    summary = dict(schema_version=schema_version("maker_plugin_dry_run"), date=args.date, profile=informed_v0.name,
        status="COMPLETE", stop_reason=None, coverage=reader.coverage, unavailable=Counter(),
        decision_reasons=Counter(), leg_counts={"0": 0, "1": 0, "2": 0}, mass_coverage=Counter(),
        max_seconds=args.max_seconds, max_output_bytes=args.max_output_bytes, max_input_bytes=args.max_input_bytes,
        max_cache_bytes=max_cache_bytes, minute_stride=stride,
        markets=args.markets, hypothetical_hazard_per_minute=args.hypothetical_hazard_per_minute,
        assumptions="Independent diagnostic decisions: 100-unit cash/order/band/event/wallet caps, zero inventory, "
        "no resting orders or fills, captured books treated as post-only capable. No measured hazard is retained "
        "by 88a: default None preserves MISSING_CONSERVATIVE_FILL_BOUND refusal. Any supplied hazard is hypothetical. "
        "Time limit covers cooperative processing; terminal report flush may add overhead. "
        "Input bytes count decompressed bytes, including rereads, per source as coverage input_bytes.*. "
        "Whole-file reads and decoded segments are limited to 64 MiB each; CLOB token, trigger, ledger and "
        "shared NBP blob files are streamed once per run (1 MiB line limit). Supporting rows after the run "
        "date, and forecast/NBP rows more than 48 hours before it, cannot be point in time and are not loaded. "
        "Per-event inputs stay cached within max_cache_bytes; evictions and reloads are counted. "
        "One sample per segment/event/captured minute, or per stride-th UTC minute of the day when "
        "minute_stride > 1; split minutes are flagged. Future source rows are PIT-filtered.")
    report = Report(output, args.max_output_bytes, summary)
    try:
        process(reader, sources, report, args.date, set(args.markets), args.hypothetical_hazard_per_minute, stride)
    except StopRun as exc:
        summary.update(status="PARTIAL", stop_reason=str(exc))
    except (ValueError, KeyError, TypeError, AttributeError, IndexError, ArithmeticError, OSError, EOFError) as exc:
        summary.update(status="INPUT_ERROR", stop_reason=reason(exc))
    for key, count in sources.errors.items():
        increment(summary["unavailable"], key, count)
    if not report.count and summary["status"] == "COMPLETE":
        summary.update(status="NO_COVERAGE", stop_reason="no_evaluable_event_minutes")
    report.finish(reader)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="UTC capture date YYYY-MM-DD")
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path, help="New/empty report directory")
    parser.add_argument("--markets", nargs="+", choices=[s.id for s in BUILTIN_SPECS], default=[s.id for s in BUILTIN_SPECS])
    parser.add_argument("--max-seconds", type=float, default=2700)
    parser.add_argument("--max-output-bytes", type=int, default=200_000_000)
    parser.add_argument("--max-input-bytes", type=int, default=1024**3)
    parser.add_argument("--max-cache-bytes", type=int, default=DEFAULT_CACHE_BYTES,
                        help="Encoded bytes of per-event supporting rows kept for the run")
    parser.add_argument("--minute-stride", type=int, default=1,
                        help="Evaluate every Nth UTC minute of the day (1-60); reported in the summary")
    parser.add_argument("--hypothetical-hazard-per-minute", type=float, default=None,
                        help="Optional synthetic total band shares/minute bound; never an estimate from capture")
    args = parser.parse_args(argv)
    try:
        if date.fromisoformat(args.date).isoformat() != args.date:
            raise ValueError("date_must_be_canonical")
        summary = run(args)
    except (ValueError, OSError) as exc:
        parser.error(reason(exc))
    print(json.dumps({k: summary[k] for k in ("status", "stop_reason", "records_written", "output_bytes")}))
    return 0 if summary["status"] == "COMPLETE" else 2
