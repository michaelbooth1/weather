import csv
import json
from pathlib import Path

import pytest

from weather.captured_input_hash import captured_input_payload_sha256
from tests.test_release_serving import _active_fixture
from weather.market.market_config import config_for_date
from weather.market.worker_release_binding import (
    LINEAGE_FIELDS,
    WorkerReleaseBindingError,
    load_worker_release_binding,
    stamp_worker_release_lineage,
    verify_worker_csv_tape_for_append,
    verify_worker_snapshot_binding,
    verify_worker_tape_lineage,
    worker_tape_columns,
    worker_tape_summary_fields,
)
from weather.release_serving import clear_process_serving_bundle_cache
from weather.schema_registry import schema_version


# The taker/maker workers that bound releases were retired and deleted on
# 2026-09-29; the binding contract itself is still exercised on a fixed column
# list and a minimal snapshot folder.
ORDER_COLUMNS = ["order_status", "market_id", "range_label", "limit_price"]
TARGET_DATE = "2026-06-18"
NOW = "2026-06-18T16:00:00+00:00"
OLD_EVENT = "highest-temperature-in-atlanta-on-june-14-2026"


def _read_csv(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_release_bound_worker_inputs(
    root: Path,
    *,
    release_id: str,
    manifest_sha256: str,
    pointer_sha256: str,
    sequence: int,
) -> Path:
    event_slug = config_for_date(TARGET_DATE, "nyc").event_slug
    snapshots_root = root / "snapshots"
    folder = snapshots_root / event_slug
    folder.mkdir(parents=True)
    snapshot_rows = [
        {
            "snapshot_id": "s1",
            "captured_at_utc": "2026-06-18T15:59:30+00:00",
            "event_slug": event_slug,
            "model_version": "candidate",
            "range_label": f"{value}-{value + 1} F",
            "condition_id": f"condition-{value}",
            "clob_yes_token_id": f"token-{value}",
            "bin_kind": "eq",
            "bin_value_c": str(value),
            "model_probability": "0.5",
            "market_yes": "0.50",
            "best_bid": "0.49",
            "best_ask": "0.51",
            "market_status": "active",
        }
        for value in (80, 82)
    ]
    with (folder / "snapshots_long.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(snapshot_rows[0]))
        writer.writeheader()
        writer.writerows(snapshot_rows)

    replay_input = {
        "schema_version": schema_version("replay_inputs"),
        "snapshot_id": "s1",
        "captured_at_utc": "2026-06-18T15:59:30+00:00",
        "captured_at_local": "2026-06-18T11:59:30-04:00",
        "event_slug": event_slug,
        "target_date": TARGET_DATE,
        "model_version": "candidate",
        "release_id": release_id,
        "release_manifest_sha256": manifest_sha256,
        "release_pointer_sha256": pointer_sha256,
        "release_sequence": sequence,
        "release_identity_status": "verified_variant_serving_bundle",
        "release_identity_reason": "synthetic verified serving fixture",
        "base_model_release_bound": True,
        "base_model_binding_reason": "synthetic complete base-model graph",
        "captured_input_hash_algorithm": "sha256-canonical-json;omit=captured_input_hash",
        "recorded_distribution": {"80": 0.5, "82": 0.5},
        "sources": {"synthetic": {"status": "fresh"}},
    }
    replay_input["captured_input_hash"] = captured_input_payload_sha256(
        replay_input,
        persisted=False,
    )
    (folder / "replay_inputs.jsonl").write_text(
        json.dumps(replay_input, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return snapshots_root


def test_unbound_diagnostic_tape_keeps_legacy_columns(tmp_path: Path) -> None:
    binding = load_worker_release_binding(
        pointer_path=tmp_path / "missing-pointer.json",
        repo_root=tmp_path,
        releases_root=tmp_path / "releases",
        check_runtime=False,
        enabled=False,
    )

    assert binding.release_bound is False
    assert worker_tape_columns(ORDER_COLUMNS, binding) == ORDER_COLUMNS


def test_unbound_lineage_accepts_legacy_or_complete_stamp_but_rejects_partial(
    tmp_path: Path,
) -> None:
    binding = load_worker_release_binding(
        pointer_path=tmp_path / "missing-pointer.json",
        repo_root=tmp_path,
        releases_root=tmp_path / "releases",
        check_runtime=False,
        enabled=False,
    )
    stamped: dict[str, object] = {}
    stamp_worker_release_lineage([stamped], binding)

    verify_worker_tape_lineage([{}], binding, label="legacy unbound row")
    verify_worker_tape_lineage(
        [stamped],
        binding,
        label="canonical stamped unbound pending row",
    )
    recovered = worker_tape_summary_fields([stamped])
    assert recovered["release_identity_status"] == "research_unbound_non_countable"
    assert recovered["base_model_release_bound"] is False

    partial = dict(stamped)
    partial.pop("release_identity_reason")
    with pytest.raises(WorkerReleaseBindingError, match="release_identity_reason"):
        verify_worker_tape_lineage(
            [partial],
            binding,
            label="partial unbound row",
        )
    with pytest.raises(WorkerReleaseBindingError, match="incomplete release lineage"):
        worker_tape_summary_fields([partial])


def test_sticky_pointer_disappearance_fails_closed(tmp_path: Path) -> None:
    paths, _frozen, _release, releases_root, pointer = _active_fixture(tmp_path)
    clear_process_serving_bundle_cache()
    try:
        binding = load_worker_release_binding(
            pointer_path=pointer,
            releases_root=releases_root,
            repo_root=paths["repo"],
            check_runtime=False,
        )
        assert binding.release_bound is True
        pointer.unlink()

        with pytest.raises(WorkerReleaseBindingError, match="RESTART_REQUIRED"):
            load_worker_release_binding(
                pointer_path=pointer,
                releases_root=releases_root,
                repo_root=paths["repo"],
                check_runtime=False,
            )
    finally:
        clear_process_serving_bundle_cache()


def test_wrong_release_no_trade_row_blocks_before_append(tmp_path: Path) -> None:
    paths, _frozen, _release, releases_root, pointer = _active_fixture(tmp_path)
    clear_process_serving_bundle_cache()
    try:
        binding = load_worker_release_binding(
            pointer_path=pointer,
            releases_root=releases_root,
            repo_root=paths["repo"],
            check_runtime=False,
        )
        columns = worker_tape_columns(ORDER_COLUMNS, binding)
        tape = tmp_path / "orders_long.csv"
        with tape.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerow(
                {
                    "order_status": "NO_TRADE",
                    **{
                        field: binding.lineage.get(field)
                        for field in columns
                        if field in binding.lineage
                    },
                    "release_id": "wrong-release",
                }
            )

        with pytest.raises(WorkerReleaseBindingError, match="release_id"):
            verify_worker_csv_tape_for_append(
                tape,
                columns,
                binding,
                label="synthetic no-trade tape",
            )
    finally:
        clear_process_serving_bundle_cache()


def test_bound_lineage_reason_mismatch_blocks(tmp_path: Path) -> None:
    paths, _frozen, _release, releases_root, pointer = _active_fixture(tmp_path)
    clear_process_serving_bundle_cache()
    try:
        binding = load_worker_release_binding(
            pointer_path=pointer,
            releases_root=releases_root,
            repo_root=paths["repo"],
            check_runtime=False,
        )
        row = {field: binding.lineage.get(field) for field in LINEAGE_FIELDS}
        row["release_identity_reason"] = "mismatched synthetic reason"

        with pytest.raises(
            WorkerReleaseBindingError,
            match="release_identity_reason",
        ):
            verify_worker_tape_lineage(
                [row],
                binding,
                label="bound reason mismatch",
            )
    finally:
        clear_process_serving_bundle_cache()


def test_tampered_snapshot_probability_blocks_against_hashed_capture(
    tmp_path: Path,
) -> None:
    paths, _frozen, release, releases_root, pointer = _active_fixture(
        tmp_path / "release"
    )
    pointer_payload = json.loads(pointer.read_text(encoding="utf-8"))
    snapshots_root = _write_release_bound_worker_inputs(
        tmp_path / "worker-inputs",
        release_id=release["release_id"],
        manifest_sha256=release["manifest_sha256"],
        pointer_sha256=pointer_payload["pointer_sha256"],
        sequence=pointer_payload["sequence"],
    )
    event_slug = config_for_date(TARGET_DATE, "nyc").event_slug
    folder = snapshots_root / event_slug
    rows = _read_csv(folder / "snapshots_long.csv")
    rows[0]["model_probability"] = "0.49"

    clear_process_serving_bundle_cache()
    try:
        binding = load_worker_release_binding(
            pointer_path=pointer,
            releases_root=releases_root,
            repo_root=paths["repo"],
            check_runtime=False,
        )
        with pytest.raises(
            WorkerReleaseBindingError,
            match="model_probability does not match.*recorded_distribution",
        ):
            verify_worker_snapshot_binding(
                folder,
                rows,
                binding,
                market_id="nyc",
                target_date=TARGET_DATE,
            )
    finally:
        clear_process_serving_bundle_cache()


def test_worker_snapshot_binding_rejects_cross_market_event_provenance(
    tmp_path: Path,
) -> None:
    paths, _frozen, release, releases_root, pointer = _active_fixture(
        tmp_path / "release"
    )
    pointer_payload = json.loads(pointer.read_text(encoding="utf-8"))
    snapshots_root = _write_release_bound_worker_inputs(
        tmp_path / "worker-inputs",
        release_id=release["release_id"],
        manifest_sha256=release["manifest_sha256"],
        pointer_sha256=pointer_payload["pointer_sha256"],
        sequence=pointer_payload["sequence"],
    )
    event_slug = config_for_date(TARGET_DATE, "nyc").event_slug
    folder = snapshots_root / event_slug
    rows = _read_csv(folder / "snapshots_long.csv")

    clear_process_serving_bundle_cache()
    try:
        binding = load_worker_release_binding(
            pointer_path=pointer,
            releases_root=releases_root,
            repo_root=paths["repo"],
            check_runtime=False,
        )

        wrong_rows = [dict(row, event_slug=OLD_EVENT) for row in rows]
        with pytest.raises(
            WorkerReleaseBindingError,
            match="snapshot_event_slug",
        ):
            verify_worker_snapshot_binding(
                folder,
                wrong_rows,
                binding,
                market_id="nyc",
                target_date=TARGET_DATE,
            )

        replay_path = folder / "replay_inputs.jsonl"
        replay = json.loads(replay_path.read_text(encoding="utf-8"))
        replay["event_slug"] = OLD_EVENT
        replay["captured_input_hash"] = captured_input_payload_sha256(
            replay,
            persisted=True,
        )
        replay_path.write_text(json.dumps(replay) + "\n", encoding="utf-8")
        with pytest.raises(WorkerReleaseBindingError, match="event_slug"):
            verify_worker_snapshot_binding(
                folder,
                rows,
                binding,
                market_id="nyc",
                target_date=TARGET_DATE,
            )

        with pytest.raises(WorkerReleaseBindingError, match="snapshot folder"):
            verify_worker_snapshot_binding(
                tmp_path / "wrong-market-event-folder",
                rows,
                binding,
                market_id="nyc",
                target_date=TARGET_DATE,
            )
    finally:
        clear_process_serving_bundle_cache()
