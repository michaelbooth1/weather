"""Replay-backtest: re-run the *current* model over the captured corpus and
score it against settlement, three ways.

Unlike ``backtest.py`` (which scores the *frozen* probabilities recorded on the
tape, and so cannot evaluate a code change on days already captured), this
re-runs ``estimate_distribution`` over each snapshot's stored inputs with
today's code. For every captured band it compares:

  * **replayed** model -- what the current code produces, and
  * **recorded** model -- what was deployed when the snapshot was taken, and
  * **market**  -- the contemporaneous yes-price,

all against the realized WU settlement bucket. ``replayed_brier - recorded_brier``
is the measured effect of every code change since capture: negative is an
improvement. With ``--save-baseline`` / ``--gate`` it becomes a regression guard
so no model change ships without being measured on real days.

A fidelity canary guards the corpus itself: replaying a snapshot with the same
code version that produced it must reproduce its recorded distribution (L1 ~ 0).

CLI:
  python -m src.replay_backtest [folder ...]
      [--snapshots-root data/snapshots]
      [--settle YYYY-MM-DD=BUCKET ...]
      [--include-reconstructed]          # also score approximate reconstructed days
      [--out data/backtest/replay_report.md]
      [--save-baseline PATH] | [--gate PATH [--tol 0.003]]
"""
import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd

SRC_ROOT = Path(__file__).resolve().parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from backtest import (
    DEFAULT_SNAPSHOTS_ROOT,
    bin_type,
    capture_minute,
    attach_feature_vector,
    fmt_num,
    fmt_pct,
    fmt_signed,
    group_sort_key,
    last_pre_close_rows,
    load_daily_summary,
    load_feature_vectors,
    band_value_hi,
    markdown_table,
    reliability,
    resolve_outcome,
    safe_float,
    score_rows,
    settlement_for_tape,
)
from market_config import date_from_event_slug
from market_registry import REGISTRY, spec_for_slug
from promotion_corpus import (
    entry_for_folder,
    folders_from_manifest,
    load_manifest,
    verify_entry_inputs,
)
from replay import (
    band_model_probability,
    distribution_l1,
    identity_hash,
    index_records_by_snapshot,
    is_reconstructed,
    load_replay_records,
    replay_distribution,
    replay_model_identity,
    replay_model_version,
)
from settled_days import folder_market_id
from toronto_model import TorontoHighTempModel

DEFAULT_OUT = Path("data") / "backtest" / "replay_report.md"
DEFAULT_BASELINE = Path("data") / "backtest" / "replay_baseline.json"
FIDELITY_FAITHFUL_L1 = 0.01  # same-version replay within this L1 is "faithful"


def model_view(rows, prob_field):
    """Rows shaped for ``score_rows``: ``model_probability`` drawn from one of
    the parallel probability fields. All grouping keys are preserved."""
    out = []
    for row in rows:
        copy = dict(row)
        copy["model_probability"] = row[prob_field]
        out.append(copy)
    return out


def comparison(rows):
    """Replayed vs recorded vs market over a row set (None if empty)."""
    replayed = score_rows(model_view(rows, "replayed_p"))
    recorded = score_rows(model_view(rows, "recorded_p"))
    if not replayed or not recorded:
        return None
    return {
        "n": replayed["n"],
        "replayed_brier": replayed["model_brier"],
        "recorded_brier": recorded["model_brier"],
        "market_brier": replayed["market_brier"],
        "replayed_logloss": replayed["model_logloss"],
        "recorded_logloss": recorded["model_logloss"],
        "market_logloss": replayed["market_logloss"],
        "replayed_skill": replayed["brier_skill_score"],
        "recorded_skill": recorded["brier_skill_score"],
        "code_effect": replayed["model_brier"] - recorded["model_brier"],
        "base_rate": replayed["base_rate"],
    }


def daily_first_comparison(day_results):
    """Equal-weight days (so snapshot-heavy days don't dominate the headline)."""
    comps = [day["comparison"] for day in day_results if day.get("comparison")]
    if not comps:
        return None

    def avg(key):
        return sum(c[key] for c in comps) / len(comps)

    return {
        "n_days": len(comps),
        "n": sum(c["n"] for c in comps),
        "replayed_brier": avg("replayed_brier"),
        "recorded_brier": avg("recorded_brier"),
        "market_brier": avg("market_brier"),
        "replayed_skill": avg("replayed_skill"),
        "recorded_skill": avg("recorded_skill"),
        "code_effect": avg("replayed_brier") - avg("recorded_brier"),
        "base_rate": avg("base_rate"),
    }


def grouped_comparison(rows, group_key):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row.get(group_key)].append(row)
    output = []
    for group, group_rows in sorted(grouped.items(), key=lambda item: group_sort_key(item[0])):
        comp = comparison(group_rows)
        if comp:
            output.append({"group": group, **comp})
    return output


def fidelity_summary(fidelity_rows):
    """Split replay fidelity into exact-identity canary and legacy cohorts.

    ``model_version`` alone is not a replay identity: artifacts can be retrained
    without changing the human label. New records carry ``model_identity`` and
    only matching identity hashes are admitted to the canary. Older same-label
    rows are reported separately as legacy/ambiguous instead of failing the
    canary for a change we cannot fingerprint after the fact.
    """
    captured = [f for f in fidelity_rows if not f["reconstructed"]]
    same_identity = []
    legacy_same_label = []
    changed = []
    for f in captured:
        if (
            f.get("recorded_identity_hash")
            and f.get("recorded_identity_hash") == f.get("replayed_identity_hash")
        ):
            same_identity.append(f)
        elif (
            not f.get("recorded_identity_hash")
            and f.get("recorded_version") == f.get("replayed_version")
        ):
            legacy_same_label.append(f)
        else:
            changed.append(f)
    reconstructed = [f for f in fidelity_rows if f["reconstructed"]]

    def mean_l1(rows):
        return sum(r["l1"] for r in rows) / len(rows) if rows else None

    same_mean = mean_l1(same_identity)
    legacy_mean = mean_l1(legacy_same_label)
    changed_mean = mean_l1(changed)
    return {
        "same_identity_n": len(same_identity),
        "same_identity_mean_l1": same_mean,
        "same_identity_max_l1": max((r["l1"] for r in same_identity), default=None),
        "same_identity_faithful": (same_mean is not None and same_mean <= FIDELITY_FAITHFUL_L1),
        # Back-compat aliases for older tests/callers; these now mean exact
        # replay identity, not the human version string.
        "same_version_n": len(same_identity),
        "same_version_mean_l1": same_mean,
        "same_version_max_l1": max((r["l1"] for r in same_identity), default=None),
        "same_version_faithful": (same_mean is not None and same_mean <= FIDELITY_FAITHFUL_L1),
        "legacy_same_version_n": len(legacy_same_label),
        "legacy_same_version_mean_l1": legacy_mean,
        "legacy_same_version_max_l1": max((r["l1"] for r in legacy_same_label), default=None),
        "changed_version_n": len(changed),
        "changed_version_mean_l1": changed_mean,
        "changed_version_max_l1": max((r["l1"] for r in changed), default=None),
        "reconstructed_n": len(reconstructed),
        "reconstructed_mean_l1": mean_l1(reconstructed),
    }


def _manifest_summary(manifest):
    if not manifest:
        return None
    summary = manifest.get("summary") or {}
    return {
        "path": manifest.get("_path"),
        "schema_version": manifest.get("schema_version"),
        "corpus_hash": manifest.get("corpus_hash"),
        "as_of": manifest.get("as_of"),
        "quality_grades": manifest.get("quality_grades"),
        "include_reconstructed": manifest.get("include_reconstructed"),
        "market_day_count": summary.get("market_day_count"),
        "snapshot_count": summary.get("snapshot_count"),
        "band_row_count": summary.get("band_row_count"),
        "identity_record_count": summary.get("identity_record_count"),
        "by_market": summary.get("by_market"),
    }


def _override_applies(overrides, slug, target_date, market_id):
    if not overrides:
        return False
    iso = target_date.isoformat() if target_date else None
    return any(
        key in overrides
        for key in (slug, iso, f"{market_id}:{iso}" if market_id and iso else None)
        if key
    )


def _pinned_settlement(entry):
    if not entry:
        return None
    bucket = entry.get("settlement_bucket")
    if bucket is None:
        return None
    return (
        int(bucket),
        f"promotion_corpus:{entry.get('settlement_source') or 'unknown'}",
        entry.get("quality_reason") or "",
    )


def settlement_distance(kind, value, value_hi, settlement_bucket):
    if settlement_bucket is None or value is None:
        return None
    try:
        settlement = int(float(settlement_bucket))
        lo = int(float(value))
        hi = int(float(value_hi)) if value_hi is not None else lo
    except (TypeError, ValueError):
        return None
    if kind == "lte":
        return max(0, settlement - lo)
    if kind == "gte":
        return max(0, lo - settlement)
    if lo <= settlement <= hi:
        return 0
    return min(abs(settlement - lo), abs(settlement - hi))


def settlement_distance_bucket(value):
    if value is None:
        return "missing"
    try:
        value = int(float(value))
    except (TypeError, ValueError):
        return "missing"
    if value <= 0:
        return "0"
    if value == 1:
        return "1"
    if value == 2:
        return "2"
    return "3+"


def run_replay_backtest(folders, daily_summary_path, overrides, out_path,
                        include_reconstructed=False, write=True,
                        corpus_manifest=None):
    # Each folder replays through ITS OWN market's model (spec, unit, artifacts,
    # climatology) and settles against its own market's daily summary; one
    # Toronto model for every folder silently mis-replayed the 11 F markets.
    # An explicit daily_summary_path stays a global override for all folders.
    models = {}

    def model_for_market(market_id):
        if market_id not in models:
            models[market_id] = TorontoHighTempModel(market_id=market_id)
        return models[market_id]

    daily_indexes = {}

    def daily_index_for_market(market_id):
        if daily_summary_path is not None:
            key = "__override__"
            if key not in daily_indexes:
                daily_indexes[key] = load_daily_summary(daily_summary_path)
            return daily_indexes[key]
        if market_id not in daily_indexes:
            spec = REGISTRY[market_id]
            daily_indexes[market_id] = load_daily_summary(
                spec.data_root / "daily" / "daily_summary.csv"
            )
        return daily_indexes[market_id]

    all_rows = []
    days = []
    fidelity_rows = []
    corpus_warnings = []
    snaps_in_corpus = 0
    snaps_scored = 0

    for folder in folders:
        tape_path = Path(folder) / "snapshots_long.csv"
        if not tape_path.exists():
            print(f"  skip {folder}: no snapshots_long.csv")
            continue
        market_id = folder_market_id(folder)
        if market_id is None:
            print(f"  skip {Path(folder).name}: not a registered market slug")
            continue
        records = index_records_by_snapshot(load_replay_records(folder))
        if not records:
            print(f"  skip {Path(folder).name}: no replay_inputs.jsonl (capture not yet seeded)")
            continue
        model = model_for_market(market_id)
        daily_index = daily_index_for_market(market_id)
        df = pd.read_csv(tape_path)
        if "snapshot_id" not in df:
            continue
        slug = Path(folder).name
        target_date = date_from_event_slug(slug)
        date_label = target_date.isoformat() if target_date else slug
        corpus_entry = entry_for_folder(corpus_manifest, folder) if corpus_manifest else None
        if corpus_entry:
            pinned_ids = {str(item) for item in corpus_entry.get("snapshot_ids") or []}
            corpus_warnings.extend(verify_entry_inputs(corpus_entry, folder, df, records))
            df = df[df["snapshot_id"].astype(str).isin(pinned_ids)].copy()
            records = {
                snapshot_id: record for snapshot_id, record in records.items()
                if str(snapshot_id) in pinned_ids
            }
        pinned_settlement = None if _override_applies(overrides, slug, target_date, market_id) else _pinned_settlement(corpus_entry)
        if pinned_settlement:
            bucket, source, note = pinned_settlement
        else:
            bucket, source, note = settlement_for_tape(df, target_date, daily_index, overrides)
        feature_index = load_feature_vectors(folder)

        day_rows = []
        for snapshot_id, group in df.groupby("snapshot_id"):
            record = records.get(str(snapshot_id))
            if not record:
                continue
            reconstructed = is_reconstructed(record)
            if reconstructed and not include_reconstructed:
                continue
            snaps_in_corpus += 1
            distribution = replay_distribution(model, record)
            if not distribution:
                continue
            snaps_scored += 1

            recorded_distribution = record.get("recorded_distribution")
            if recorded_distribution:
                replayed_identity = replay_model_identity(model)
                recorded_identity = record.get("model_identity")
                fidelity_rows.append({
                    "snapshot_id": str(snapshot_id),
                    "date": date_label,
                    "market_id": market_id,
                    "recorded_version": record.get("model_version"),
                    "replayed_version": replay_model_version(model),
                    "recorded_identity_hash": identity_hash(recorded_identity),
                    "replayed_identity_hash": identity_hash(replayed_identity),
                    "l1": distribution_l1(distribution, recorded_distribution),
                    "reconstructed": reconstructed,
                })

            for _, band_series in group.iterrows():
                band = band_series.to_dict()
                value_hi = band_value_hi(band.get("range_label"), band.get("bin_value_c"))
                outcome = resolve_outcome(
                    band.get("bin_kind"), band.get("bin_value_c"), bucket,
                    value_hi=value_hi)
                if outcome is None:
                    continue
                market_yes = safe_float(band.get("market_yes"))
                recorded_p = safe_float(band.get("model_probability"))
                if market_yes is None or recorded_p is None:
                    continue
                replayed_p = band_model_probability(model, distribution, band)
                if replayed_p is None:
                    continue
                minute = capture_minute(band.get("captured_at_local"))
                distance = settlement_distance(
                    band.get("bin_kind"),
                    band.get("bin_value_c"),
                    value_hi,
                    bucket,
                )
                scoring_row = {
                    "snapshot_id": str(snapshot_id),
                    "market_id": market_id,
                    "target_date": date_label,
                    "captured_at_local": band.get("captured_at_local"),
                    "capture_minute": minute,
                    "cutoff_hour": minute // 60 if minute is not None else None,
                    "band": band.get("range_label"),
                    "bin_type": bin_type(band.get("bin_kind")),
                    "bin_value_c": safe_float(band.get("bin_value_c")),
                    "bin_value_hi": safe_float(value_hi),
                    "market_yes": market_yes,
                    "market_no": safe_float(band.get("market_no")),
                    "outcome": int(outcome),
                    "recorded_p": recorded_p,
                    "replayed_p": replayed_p,
                    "reconstructed": reconstructed,
                    "settlement_bucket": bucket,
                    "settlement_distance": distance,
                    "settlement_distance_bucket": settlement_distance_bucket(distance),
                }
                attach_feature_vector(scoring_row, feature_index.get(str(snapshot_id)))
                day_rows.append(scoring_row)

        all_rows.extend(day_rows)
        days.append({
            "date": date_label,
            "event_slug": slug,
            "market_id": market_id,
            "unit": REGISTRY[market_id].display_unit,
            "settlement": bucket,
            "source": source,
            "note": note,
            "snapshots_scored": len({r["snapshot_id"] for r in day_rows}),
            "rows": len(day_rows),
            "reconstructed": any(r["reconstructed"] for r in day_rows),
            "comparison": comparison(day_rows),
        })
        print(f"  {slug}: settlement {bucket} {REGISTRY[market_id].display_unit} ({source}); "
              f"{len({r['snapshot_id'] for r in day_rows})} snapshots replayed, {len(day_rows)} band-rows")

    last_rows = last_pre_close_rows(all_rows)
    results = {
        "folders": [str(f) for f in folders],
        "days": days,
        "total_rows": len(all_rows),
        "all_rows": all_rows,
        "snaps_in_corpus": snaps_in_corpus,
        "snaps_scored": snaps_scored,
        "replayed_versions": sorted({f["replayed_version"] for f in fidelity_rows if f["replayed_version"]}),
        "aggregate": comparison(all_rows),
        "daily_first": daily_first_comparison(days),
        "last_pre_close": comparison(last_rows),
        "by_day": grouped_comparison(all_rows, "target_date"),
        "by_hour": grouped_comparison(all_rows, "cutoff_hour"),
        "by_bin_type": grouped_comparison(all_rows, "bin_type"),
        "fidelity": fidelity_summary(fidelity_rows),
        "fidelity_rows": fidelity_rows,
        "include_reconstructed": include_reconstructed,
        "promotion_corpus": _manifest_summary(corpus_manifest),
        "corpus_warnings": corpus_warnings,
    }
    if write:
        write_report(results, out_path)
    return results


# --- Report -----------------------------------------------------------------

def comparison_table_rows(items):
    rows = []
    for label, comp in items:
        if not comp:
            continue
        rows.append([
            label,
            comp.get("n_days", "-"),
            comp.get("n", "-"),
            fmt_num(comp.get("replayed_brier")),
            fmt_num(comp.get("recorded_brier")),
            fmt_num(comp.get("market_brier")),
            fmt_signed(comp.get("code_effect")),
            fmt_signed(comp.get("replayed_skill"), 3),
            fmt_pct(comp.get("base_rate")),
        ])
    return rows


def grouped_comparison_table_rows(items):
    return [
        [
            str(item.get("group")) if item.get("group") not in (None, "") else "-",
            item.get("n", "-"),
            fmt_num(item.get("replayed_brier")),
            fmt_num(item.get("recorded_brier")),
            fmt_num(item.get("market_brier")),
            fmt_signed(item.get("code_effect")),
            fmt_signed(item.get("replayed_skill"), 3),
            fmt_pct(item.get("base_rate")),
        ]
        for item in items
    ]


COMPARISON_HEADERS = [
    "Scope", "Days", "Rows", "Replayed Brier", "Recorded Brier",
    "Market Brier", "Code Effect", "Replayed Skill", "Base Rate",
]
GROUPED_HEADERS = [
    "Group", "Rows", "Replayed Brier", "Recorded Brier",
    "Market Brier", "Code Effect", "Replayed Skill", "Base Rate",
]


def write_report(results, out_path):
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    fid = results.get("fidelity") or {}
    corpus = results.get("promotion_corpus") or {}
    lines = [
        "# Replay Backtest (model re-run over captured inputs)",
        "",
        f"Generated: {generated}",
        "",
        (
            f"Days scored: {len(results['days'])}  |  "
            f"Snapshots replayed: {results['snaps_scored']}  |  "
            f"Band-rows: {results['total_rows']}"
        ),
        f"Replayed model version(s): {', '.join(results.get('replayed_versions') or []) or '-'}",
        f"Reconstructed days included: {results.get('include_reconstructed')}",
        "",
        "> **Code Effect = Replayed Brier - Recorded Brier** (negative = the current",
        "> code is better than what was deployed when the snapshot was captured).",
        "> Recorded/market are the frozen tape values; replayed is today's code re-run",
        "> over the identical stored inputs. Lower Brier is better.",
        "",
    ]
    if corpus:
        lines += [
            "## Promotion Corpus",
            "",
        ]
        lines += markdown_table(
            ["Field", "Value"],
            [
                ["Corpus hash", corpus.get("corpus_hash") or "-"],
                ["Path", corpus.get("path") or "-"],
                ["As of", corpus.get("as_of") or "-"],
                ["Market days", corpus.get("market_day_count") or 0],
                ["Pinned snapshots", corpus.get("snapshot_count") or 0],
                ["Pinned band rows", corpus.get("band_row_count") or 0],
                ["Identity-bearing records", corpus.get("identity_record_count") or 0],
                ["Quality grades", ", ".join(corpus.get("quality_grades") or []) or "-"],
            ],
        )
        warnings = results.get("corpus_warnings") or []
        if warnings:
            lines += ["", "### Corpus Pin Warnings", ""]
            lines += [f"- {warning}" for warning in warnings[:50]]
            if len(warnings) > 50:
                lines.append(f"- ... {len(warnings) - 50} more")
        lines.append("")

    lines += [
        "## Replay Fidelity Canary",
        "",
        "Replaying a snapshot with the *same replay identity* that produced it",
        "must reproduce its recorded distribution (L1 ~ 0). Replay identity is",
        "stricter than the human model version: it includes model kind, market,",
        "distribution-code fingerprints, and per-market artifact fingerprints.",
        "Older same-label records without identity are shown as legacy diagnostics",
        "and are excluded from the canary.",
        "",
    ]
    lines += markdown_table(
        ["Cohort", "Snapshots", "Mean L1", "Max L1", "Verdict"],
        [
            [
                "Same replay identity (canary)",
                fid.get("same_identity_n", 0),
                fmt_num(fid.get("same_identity_mean_l1")),
                fmt_num(fid.get("same_identity_max_l1")),
                "FAITHFUL" if fid.get("same_identity_faithful") else
                ("-" if fid.get("same_identity_n", 0) == 0 else "CHECK"),
            ],
            [
                "Unversioned same-label legacy",
                fid.get("legacy_same_version_n", 0),
                fmt_num(fid.get("legacy_same_version_mean_l1")),
                fmt_num(fid.get("legacy_same_version_max_l1")),
                "excluded from canary",
            ],
            [
                "Changed version/identity (effect size)",
                fid.get("changed_version_n", 0),
                fmt_num(fid.get("changed_version_mean_l1")),
                fmt_num(fid.get("changed_version_max_l1")),
                "code change moved the distribution",
            ],
            [
                "Reconstructed (approximate)",
                fid.get("reconstructed_n", 0),
                fmt_num(fid.get("reconstructed_mean_l1")),
                "-",
                "approximate inputs -- exploratory only",
            ],
        ],
    )

    lines += ["", "## Headline: Replayed vs Recorded vs Market", ""]
    lines += markdown_table(
        COMPARISON_HEADERS,
        comparison_table_rows([
            ("All snapshots", results.get("aggregate")),
            ("Daily-first equal-day average", results.get("daily_first")),
            ("Last pre-close", results.get("last_pre_close")),
        ]),
    )

    lines += ["", "## Per Target Day", ""]
    lines += markdown_table(
        ["Date", "Settlement", "Source", "Snaps", "Replayed Brier",
         "Recorded Brier", "Market Brier", "Code Effect", "Note"],
        [
            [
                day["date"],
                f"{day['settlement']} {day.get('unit', 'C')}" if day["settlement"] is not None else "-",
                day["source"],
                day["snapshots_scored"],
                fmt_num((day.get("comparison") or {}).get("replayed_brier")),
                fmt_num((day.get("comparison") or {}).get("recorded_brier")),
                fmt_num((day.get("comparison") or {}).get("market_brier")),
                fmt_signed((day.get("comparison") or {}).get("code_effect")),
                day["note"] or "-",
            ]
            for day in results["days"]
        ],
    )

    lines += ["", "## By Capture Hour", ""]
    lines += markdown_table(GROUPED_HEADERS, grouped_comparison_table_rows(results.get("by_hour", [])))

    lines += ["", "## By Market-Bin Type", ""]
    lines += markdown_table(GROUPED_HEADERS, grouped_comparison_table_rows(results.get("by_bin_type", [])))

    lines += ["", "## Replayed Reliability", ""]
    lines += markdown_table(
        ["Confidence bin", "N", "Mean predicted", "Realized"],
        [
            [row["bin"], row["n"], fmt_pct(row["pred"]), fmt_pct(row["actual"])]
            for row in reliability(model_view(results["all_rows"], "replayed_p"), "model_probability")
        ],
    )

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text("\n".join(lines) + "\n", encoding="utf-8")


# --- Baseline / regression gate ---------------------------------------------

def baseline_payload(results):
    aggregate = results.get("aggregate") or {}
    daily = results.get("daily_first") or {}
    corpus = results.get("promotion_corpus") or {}
    return {
        "generated": datetime.now().isoformat(),
        "replayed_versions": results.get("replayed_versions"),
        "snaps_scored": results.get("snaps_scored"),
        "aggregate_replayed_brier": aggregate.get("replayed_brier"),
        "aggregate_market_brier": aggregate.get("market_brier"),
        "daily_first_replayed_brier": daily.get("replayed_brier"),
        "corpus_hash": corpus.get("corpus_hash"),
        "corpus_schema_version": corpus.get("schema_version"),
        "corpus_market_day_count": corpus.get("market_day_count"),
        "corpus_snapshot_count": corpus.get("snapshot_count"),
    }


def save_baseline(path, results):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(baseline_payload(results), indent=2, sort_keys=True), encoding="utf-8")


def gate(baseline_path, results, tol):
    """Compare the current replayed aggregate Brier to a saved baseline.

    Returns (passed, message). A change that *worsens* the replayed Brier on the
    corpus by more than ``tol`` fails the gate.
    """
    try:
        baseline = json.loads(Path(baseline_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"could not read baseline {baseline_path}: {exc}"
    aggregate = results.get("aggregate") or {}
    current = aggregate.get("replayed_brier")
    base = baseline.get("aggregate_replayed_brier")
    base_corpus = baseline.get("corpus_hash")
    current_corpus = (results.get("promotion_corpus") or {}).get("corpus_hash")
    if base_corpus and current_corpus != base_corpus:
        return False, (
            f"corpus mismatch: baseline {base_corpus} vs current {current_corpus or '-'}"
        )
    if current is None or base is None:
        return False, "missing aggregate Brier in baseline or current run"
    delta = current - base
    passed = delta <= tol
    verdict = "PASS" if passed else "FAIL"
    return passed, (
        f"{verdict}: replayed Brier {current:.4f} vs baseline {base:.4f} "
        f"(delta {delta:+.4f}, tol {tol:.4f})"
    )


def main():
    parser = argparse.ArgumentParser(description="Replay the model over captured inputs and score it.")
    parser.add_argument("folders", nargs="*", help="Snapshot folders (default: all under snapshots root).")
    parser.add_argument("--market", default=None, choices=sorted(REGISTRY),
                        help="Only replay this market's folders (default: all, each "
                             "replayed with its own market's model).")
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--corpus", default=None,
                        help="Pinned promotion corpus manifest. When set, replay only the "
                             "manifest's snapshot IDs and settlement labels.")
    parser.add_argument("--daily-summary", default=None,
                        help="Daily summary CSV override for ALL folders "
                             "(default: each market's own data root).")
    parser.add_argument("--settle", action="append", default=[],
                        help="Force settlement: YYYY-MM-DD=BUCKET (repeatable).")
    parser.add_argument("--include-reconstructed", action="store_true",
                        help="Also score approximate reconstructed days (excluded by default).")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--save-baseline", nargs="?", const=str(DEFAULT_BASELINE), default=None,
                        help="Save this run's replayed scores as the regression baseline.")
    parser.add_argument("--gate", nargs="?", const=str(DEFAULT_BASELINE), default=None,
                        help="Fail (exit 1) if replayed Brier regressed vs the saved baseline.")
    parser.add_argument("--tol", type=float, default=0.003, help="Gate tolerance on aggregate Brier.")
    args = parser.parse_args()

    overrides = {}
    for item in args.settle:
        date_str, _, value = item.partition("=")
        overrides[date_str.strip()] = int(value)

    corpus_manifest = load_manifest(args.corpus) if args.corpus else None
    folders = args.folders
    if corpus_manifest and not folders:
        folders = [str(folder) for folder in folders_from_manifest(corpus_manifest, args.snapshots_root)]
    elif corpus_manifest:
        corpus_slugs = {entry.get("event_slug") for entry in corpus_manifest.get("entries") or []}
        outside = [folder for folder in folders if Path(folder).name not in corpus_slugs]
        if outside:
            raise SystemExit(
                "--corpus was provided, but these folders are not in the manifest: "
                + ", ".join(outside)
            )
    if not folders:
        root = Path(args.snapshots_root)
        folders = sorted(str(p.parent) for p in root.glob("*/snapshots_long.csv"))
    if args.market:
        folders = [f for f in folders if folder_market_id(f) == args.market]
    if not folders:
        print("No snapshot tapes found.")
        return

    print(f"Replaying {len(folders)} market day(s) over the corpus...")
    results = run_replay_backtest(
        folders, args.daily_summary, overrides, args.out,
        include_reconstructed=args.include_reconstructed,
        corpus_manifest=corpus_manifest,
    )

    if results["snaps_scored"] == 0:
        print("\nNo snapshots had replay inputs yet. Seed the corpus by running the")
        print("collector (snapshot_tracker) on this version, then re-run this backtest.")
        return

    aggregate = results.get("aggregate") or {}
    fid = results.get("fidelity") or {}
    if aggregate:
        print(
            f"\nAll-snapshot replayed Brier {aggregate['replayed_brier']:.4f} vs "
            f"recorded {aggregate['recorded_brier']:.4f} vs market {aggregate['market_brier']:.4f} "
            f"(code effect {aggregate['code_effect']:+.4f})"
        )
    if fid.get("same_identity_n"):
        verdict = "faithful" if fid.get("same_identity_faithful") else "CHECK CORPUS"
        print(f"Fidelity canary: {fid['same_identity_n']} same-identity snapshots, "
              f"mean L1 {fid['same_identity_mean_l1']:.5f} ({verdict})")
    elif fid.get("legacy_same_version_n"):
        print("Fidelity canary: no exact-identity snapshots yet; "
              f"{fid['legacy_same_version_n']} legacy same-label snapshot(s) excluded "
              f"(mean L1 {fid['legacy_same_version_mean_l1']:.5f})")
    print(f"Report written to {args.out}")

    if args.save_baseline:
        save_baseline(args.save_baseline, results)
        print(f"Baseline saved to {args.save_baseline}")
    if args.gate:
        passed, message = gate(args.gate, results, args.tol)
        print(f"Regression gate: {message}")
        if not passed:
            sys.exit(1)


if __name__ == "__main__":
    main()
