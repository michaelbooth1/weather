"""Reconciled, PIT ledger labels only. No WU/WRH proxy or venue lookup."""
import math

from maker_core.contracts import Pending, SettlementFact, utc_time
from weather.market.maker_plugin.inputs import band, digest, event_identity, records, timestamp

# Matches settlement_ledger.LEDGER_REVISION_METADATA_FIELDS without importing
# that module's provider/network closure.
REVISION_FIELDS = {"ledger_record_type", "revision_id", "revision_number", "recorded_at_utc",
                   "supersedes_revision_id", "previous_label_hash", "label_hash",
                   "revision_changes", "revision_provenance"}


class WeatherSettlement:
    def __init__(self, universe, *, ledger_rows=()):
        self.universe = universe
        self.ledger_rows = records(ledger_rows)

    def resolve(self, market, as_of_utc):
        utc_time(as_of_utc)
        try:
            spec, target = event_identity(market.event_id)
            if market.domain_id != "weather" or market.native_unit != spec.unit:
                raise ValueError("market_identity_or_unit_mismatch")
            rows = [r for r in self.ledger_rows if r.get("event_slug") == market.event_id
                    and timestamp(r["recorded_at_utc"]) <= as_of_utc]
            if not rows or as_of_utc < market.close_at_utc:
                raise ValueError("settlement_not_recorded_or_event_open")
            previous = None
            for row in sorted(rows, key=lambda r: int(r["revision_number"])):
                label = {k: v for k, v in row.items() if k not in REVISION_FIELDS}
                if row.get("ledger_record_type") != "settlement_revision" or row["label_hash"] != digest(label):
                    raise ValueError("ledger_label_hash_mismatch_or_legacy_unbound")
                seed = {k: row.get(k) for k in ("event_slug", "revision_number", "recorded_at_utc",
                                               "label_hash", "supersedes_revision_id")}
                if row["revision_id"] != "sha256:" + digest(seed):
                    raise ValueError("ledger_revision_hash_mismatch")
                if row["revision_number"] != (previous["revision_number"] + 1 if previous else 1):
                    raise ValueError("ledger_revision_gap_or_conflict")
                if previous and (row["supersedes_revision_id"] != previous["revision_id"]
                                 or row["previous_label_hash"] != previous["label_hash"]
                                 or timestamp(row["recorded_at_utc"]) < timestamp(previous["recorded_at_utc"])):
                    raise ValueError("ledger_supersession_mismatch")
                if not previous and (row.get("supersedes_revision_id") or row.get("previous_label_hash")):
                    raise ValueError("missing_ledger_ancestor")
                before = {k: v for k, v in (previous or {}).items() if k not in REVISION_FIELDS}
                changes = [{"field": k, "old": before.get(k), "new": label.get(k)}
                           for k in sorted(set(before) | set(label)) if before.get(k) != label.get(k)]
                if row.get("revision_changes") != changes:
                    raise ValueError("ledger_revision_changes_mismatch")
                previous = row
            row = previous
            if timestamp(row["finalized_at_utc"]) > timestamp(row["recorded_at_utc"]):
                raise ValueError("settlement_finalized_after_recording")
            if row["market_id"] != spec.id or row["target_date"] != target.isoformat() or row["settlement_unit"] != spec.unit:
                raise ValueError("settlement_identity_or_unit_mismatch")
            if row.get("reconciliation_status") != "match" or not row.get("polymarket_winning_band"):
                raise ValueError("settlement_not_reconciled")
            if row["winning_band"] != row["polymarket_winning_band"]:
                raise ValueError("winning_band_disagrees_with_venue")
            bucket = float(row["settlement_bucket"])
            if not math.isfinite(bucket) or not bucket.is_integer():
                raise ValueError("invalid_settlement_bucket")
            winning = band({"bin_kind": row["winning_band_kind"], "bin_value_c": row["winning_band_value"],
                            "bin_value_hi_c": row["winning_band_value_hi"]})
            if not winning[0] < bucket < winning[1]:
                raise ValueError("winning_band_excludes_settlement_bucket")
            bands = self.universe.bands(market.event_id, as_of_utc)
            if winning not in bands.values():
                raise ValueError("winning_band_missing_from_captured_event")
            lo, hi = bands[market.condition_id]
            return SettlementFact(market.condition_id, float(lo < bucket < hi), as_of_utc,
                                  {"ledger": row["label_hash"], "revision": row["revision_id"]}, "match")
        except (ValueError, KeyError, TypeError, OverflowError) as exc:
            return Pending(str(exc) or "malformed_ledger_input", as_of_utc)
