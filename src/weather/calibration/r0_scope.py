"""Code-owned scope and column contract of the retrain R0 research arm.

Training-only: serving never imports this module. It owns the owner decisions
that turn the served per-market base models into R0
(``docs/research/retrain-sizing-memo-2026-10-19.md``, "R0 run plan", M6-M8;
DECISION_LOG 2026-10-21 and the 2026-10-23 answers relayed by master-agent):

* **Scope (M8):** R0 = the US 11, the EDGE-1 population. Toronto has no PIT
  corpus and keeps its served June model; it is never trained by R0 and is
  always recorded as excluded in the candidate manifest.
* **Columns:** the served bundle's ``feature_names`` minus
  * the training-policy exclusions (``native_station_pressure_train_serve_v1``:
    ``pressure`` and ``pressure_trend_3h`` in F markets; owner 2026-10-21), and
  * the forecast-consensus columns a single-provider PIT corpus cannot express
    (``forecast_source_count``, ``forecast_disagreement``; Miami is the only US
    market whose served bundle selects them; owner M7 2026-10-23: Miami drops
    them and stays in).
* **Base models only:** the per-market HGB and LR are refit; the served
  late-day continuation models stay byte-identical (DL 2026-10-21).

Every removed column is recorded, with its reason and decision, in the trained
artifacts and the candidate manifest (``served_model_differences``), so the
release binding and the parity checks see each difference from served.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

# The memo's fixed training order (R0.1 step 3); also the manifest's scope.
R0_MARKET_IDS: tuple[str, ...] = (
    "atlanta",
    "austin",
    "chicago",
    "dallas",
    "denver",
    "houston",
    "los-angeles",
    "miami",
    "nyc",
    "san-francisco",
    "seattle",
)

# Built-in markets outside R0, with the reason recorded in the manifest.
R0_OUT_OF_SCOPE_MARKETS: Mapping[str, str] = {
    "toronto": "out-of-scope-r0-is-us11 (owner M8 2026-10-23; no PIT corpus)",
}

DECISION_PRESSURE = "owner 2026-10-21 'Drop pressure (Recommended)' (DL 2026-10-21)"
DECISION_CONSENSUS = "owner M7 2026-10-23 'as recommended': Miami drops the consensus columns, stays in"
DECISION_BASE_ONLY = "owner 2026-10-21 'No, base models only (Recommended)' (DL 2026-10-21)"
DECISION_LEAF_SWEEP = "owner 2026-10-24 R0 leaf sweep 'as recommended' (research arm; served stays 20)"

# The served trainer's HGB leaf floor (scikit-learn default); the R0 leaf sweep
# varies it per research arm only.
SERVED_HGB_MIN_SAMPLES_LEAF = 20

# Columns a single-provider PIT forecast corpus cannot express: the corpus
# holds one model's lead-1 temperature, so a provider count and a spread
# across providers would be constants in training and live values in serving.
PIT_SINGLE_PROVIDER_EXCLUDED_COLUMNS: tuple[str, ...] = (
    "forecast_source_count",
    "forecast_disagreement",
)
REASON_POLICY = "training_policy_exclusion"
REASON_SINGLE_PROVIDER = "single_provider_pit_corpus_cannot_express"

# Record name only; not a registered durable schema (no versioned literal).
SERVED_MODEL_DIFFERENCES_RECORD = "r0_served_model_differences"
SERVED_MODEL_DIFFERENCES_RECORD_VERSION = 1


class R0ScopeError(ValueError):
    """The request falls outside the R0 scope fixed by the owner decisions."""


def require_r0_market(market_id: str) -> str:
    """Return ``market_id`` when R0 trains it; fail closed otherwise."""
    market = str(market_id)
    if market in R0_MARKET_IDS:
        return market
    reason = R0_OUT_OF_SCOPE_MARKETS.get(market, "not an R0 market")
    raise R0ScopeError(f"market {market!r} is outside R0 ({reason}); R0 = {list(R0_MARKET_IDS)}")


def r0_single_provider_exclusions(served_feature_names: Sequence[str]) -> list[str]:
    """The served columns R0 drops because a single-provider corpus cannot express them."""
    return [name for name in served_feature_names if name in PIT_SINGLE_PROVIDER_EXCLUDED_COLUMNS]


def column_differences(
    served_feature_names: Sequence[str],
    trained_feature_names: Sequence[str],
    *,
    policy_exclusions: Sequence[str] = (),
    single_provider_exclusions: Sequence[str] = (),
) -> list[dict[str, str]]:
    """One row per served column the trained list lacks, each with its reason.

    Fails closed on a removed column with no recorded reason, or on a trained
    column the served list does not hold (R0 never adds a column).
    """
    served = [str(name) for name in served_feature_names]
    trained = {str(name) for name in trained_feature_names}
    added = sorted(trained - set(served))
    if added:
        raise R0ScopeError(f"trained columns are not in the served list: {added}")
    policy = {str(name) for name in policy_exclusions}
    single = {str(name) for name in single_provider_exclusions}
    rows = []
    for name in served:
        if name in trained:
            continue
        if name in policy:
            rows.append({"column": name, "reason": REASON_POLICY, "decision": DECISION_PRESSURE})
        elif name in single:
            rows.append({"column": name, "reason": REASON_SINGLE_PROVIDER, "decision": DECISION_CONSENSUS})
        else:
            raise R0ScopeError(f"served column {name!r} was removed with no recorded reason")
    return rows


def served_model_differences(
    allowlist: Mapping[str, Any],
    training_inputs: Mapping[str, Any] | None,
    *,
    base_models_only: bool,
    hgb_min_samples_leaf: int = SERVED_HGB_MIN_SAMPLES_LEAF,
) -> dict[str, Any]:
    """The per-artifact record of every way an R0 fit differs from served.

    ``allowlist`` is the trained artifacts' ``training_column_allowlist``
    record; ``training_inputs`` their ``training_inputs`` record. At the served
    leaf floor the hyperparameters entry is the unchanged marker (so default
    fits keep their record byte-identical); otherwise it names the value.
    """
    leaf = int(hgb_min_samples_leaf)
    hyperparameters: Any = "unchanged_from_served_trainer"
    if leaf != SERVED_HGB_MIN_SAMPLES_LEAF:
        hyperparameters = {
            "hgb_min_samples_leaf": leaf,
            "served_hgb_min_samples_leaf": SERVED_HGB_MIN_SAMPLES_LEAF,
            "decision": DECISION_LEAF_SWEEP,
        }
    served = allowlist.get("served_feature_names")
    if served is None:
        raise R0ScopeError("the allowlist has no served list to compare against")
    removed = list(allowlist.get("column_differences_from_served") or [])
    inputs = dict(training_inputs or {})
    corpus = inputs.get("pit_forecast_corpus") or {}
    return {
        "record": SERVED_MODEL_DIFFERENCES_RECORD,
        "record_version": SERVED_MODEL_DIFFERENCES_RECORD_VERSION,
        "allowlist_mode": allowlist.get("mode"),
        "served_column_count": len(served),
        "trained_column_count": len(allowlist.get("feature_names") or []),
        "columns_removed": removed,
        "columns_added": [],
        "column_order_kept": True,
        "base_models_only": bool(base_models_only),
        "late_day_continuation": "not_refit_served_bytes_bound_by_candidate_manifest",
        "late_day_decision": DECISION_BASE_ONLY,
        "forecast_source": inputs.get("forecast_source"),
        "forecast_corpus_ids": [row.get("corpus_id") for row in corpus.get("corpora") or []],
        "centre_date": inputs.get("centre_date"),
        "training_years": inputs.get("training_years"),
        "training_days_by_year": inputs.get("training_days_by_year"),
        "hyperparameters": hyperparameters,
    }


__all__ = [
    "DECISION_BASE_ONLY",
    "DECISION_CONSENSUS",
    "DECISION_PRESSURE",
    "PIT_SINGLE_PROVIDER_EXCLUDED_COLUMNS",
    "R0ScopeError",
    "R0_MARKET_IDS",
    "R0_OUT_OF_SCOPE_MARKETS",
    "REASON_POLICY",
    "REASON_SINGLE_PROVIDER",
    "SERVED_MODEL_DIFFERENCES_RECORD",
    "column_differences",
    "r0_single_provider_exclusions",
    "require_r0_market",
    "served_model_differences",
]
