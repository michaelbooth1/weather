import hashlib
import json

import pytest

from weather.backtesting.settlement_io import (
    authoritative_ledger_label,
    canonical_winning_band,
)
from weather.reporting.validation.point_in_time_evaluation import (
    PRODUCTION_PRESELECTION_SOURCE_SCHEMA_VERSION,
    validate_production_preselection_source_row,
)


# Copied on 2026-07-24 from the read-only current revision-12 ledger rows and
# their tapes. Runtime tests use only tmp_path fixtures, never the data mirror.
CURRENT_LEDGER_TAPE_SPELLINGS = (
    (
        "atlanta",
        "highest-temperature-in-atlanta-on-june-6-2026",
        "2026-06-06",
        "86-87 F",
        "86-87\u00b0F",
    ),
    (
        "toronto",
        "highest-temperature-in-toronto-on-june-3-2026",
        "2026-06-03",
        "28 C or higher",
        "28 C or higher",
    ),
)


@pytest.mark.parametrize(
    ("market_id", "slug", "target_date", "ledger_band", "tape_band"),
    CURRENT_LEDGER_TAPE_SPELLINGS,
    ids=("current-atlanta-86-87-f", "current-toronto-28-c-or-higher"),
)
def test_current_toronto_and_atlanta_ledger_tape_spellings_share_one_source_form(
    tmp_path,
    monkeypatch,
    market_id,
    slug,
    target_date,
    ledger_band,
    tape_band,
):
    ledger_root = tmp_path / "settlements"
    monkeypatch.setenv("SETTLEMENT_LEDGER_ROOT", str(ledger_root))
    folder = tmp_path / "snapshots" / slug
    folder.mkdir(parents=True)
    tape = folder / "snapshots_long.csv"
    tape.write_text(
        f"snapshot_id,range_label\nsnapshot-1,{tape_band}\n",
        encoding="utf-8",
    )
    ledger_row = {
        "event_slug": slug,
        "market_id": market_id,
        "target_date": target_date,
        "winning_band": ledger_band,
        "settlement_bucket": 86 if market_id == "atlanta" else 28,
        "snapshot_tape_path": (
            "C:\\production\\weather\\data\\snapshots\\"
            f"{slug}\\snapshots_long.csv"
        ),
        "evidence": {
            "raw_resolution_hashes": {
                "snapshot_tape_sha256": hashlib.sha256(tape.read_bytes()).hexdigest(),
            }
        },
    }
    ledger = ledger_root / market_id / "ledger.jsonl"
    ledger.parent.mkdir(parents=True)
    ledger.write_text(json.dumps(ledger_row) + "\n", encoding="utf-8")

    loaded = authoritative_ledger_label(folder)
    source_row = validate_production_preselection_source_row(
        {
            "schema_version": PRODUCTION_PRESELECTION_SOURCE_SCHEMA_VERSION,
            "target_date": target_date,
            "market_id": market_id,
            "cutoff_or_snapshot": "snapshot-1",
            "band": tape_band,
            "feature_available_at_utc": f"{target_date}T16:00:00+00:00",
            "prediction_boundary_at_utc": f"{target_date}T16:00:00+00:00",
            "label_quality": "complete",
            "countable": True,
            "claim_lane": "weather_only",
            "source_quality": "healthy",
            "label": 1.0,
        }
    )

    assert loaded["winning_band"] == ledger_band
    assert source_row["band"] == canonical_winning_band(ledger_band)
    assert source_row["band"] == canonical_winning_band(tape_band)
