import csv
import json
from pathlib import Path

import pytest

from weather.market import taker_bot_cli
from tests.market.test_market_making_run import (
    write_known_edge_map,
    write_market_fixture,
)
from tests.test_release_serving import _active_fixture
from weather.market.market_config import config_for_date
from weather.market.market_making_run import build_run_once as build_maker_run_once
from weather.market.taker_bot import build_run_once as build_taker_run_once
from weather.market.taker_bot import COUNTERFACTUAL_ORDER_COLUMNS, ORDER_COLUMNS
from weather.market.taker_bot_finalization import write_settled_worker_tape
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
from weather.release_artifacts import canonical_payload_sha256
from weather.release_serving import clear_process_serving_bundle_cache
from weather.schema_registry import schema_version


TARGET_DATE = "2026-06-18"
NOW = "2026-06-18T16:00:00+00:00"
OLD_EVENT = "highest-temperature-in-atlanta-on-june-14-2026"


def _read_csv(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _replace_fixture_text(path: Path, *, event_slug: str) -> None:
    text = path.read_text(encoding="utf-8")
    text = text.replace(OLD_EVENT, event_slug)
    text = text.replace("2026-06-14", TARGET_DATE)
    text = text.replace("atlanta", "nyc")
    path.write_text(text, encoding="utf-8")


def _write_release_bound_worker_inputs(
    root: Path,
    *,
    release_id: str,
    manifest_sha256: str,
    pointer_sha256: str,
    sequence: int,
) -> tuple[Path, Path, Path]:
    snapshots_root, promotion = write_market_fixture(root)
    event_slug = config_for_date(TARGET_DATE, "nyc").event_slug
    old_folder = snapshots_root / OLD_EVENT
    for path in old_folder.iterdir():
        if path.is_file():
            _replace_fixture_text(path, event_slug=event_slug)
    folder = snapshots_root / event_slug
    old_folder.rename(folder)
    _replace_fixture_text(promotion, event_slug=event_slug)

    snapshot_path = folder / "snapshots_long.csv"
    snapshot_rows = _read_csv(snapshot_path)
    for row in snapshot_rows:
        row["model_probability"] = "0.5"
    with snapshot_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(snapshot_rows[0]))
        writer.writeheader()
        writer.writerows(snapshot_rows)

    known_edge = write_known_edge_map(root / "known_edge.json")
    _replace_fixture_text(known_edge, event_slug=event_slug)
    observation_status = root / "observation_status.json"
    observation_status.write_text(
        json.dumps(
            {
                "last_heartbeat": "2026-06-18T15:59:50+00:00",
                "consecutive_errors": 0,
            }
        ),
        encoding="utf-8",
    )

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
    replay_input["captured_input_hash"] = canonical_payload_sha256(replay_input)
    (folder / "replay_inputs.jsonl").write_text(
        json.dumps(replay_input, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return snapshots_root, promotion, observation_status


def _assert_release_stamped(rows: list[dict[str, str]], manifest_sha256: str) -> None:
    assert rows
    assert {row["release_id"] for row in rows} == {"r1"}
    assert {row["release_manifest_sha256"] for row in rows} == {manifest_sha256}
    assert {row["release_identity_status"] for row in rows} == {
        "verified_variant_serving_bundle"
    }
    assert {row["base_model_release_bound"] for row in rows} == {"True"}


def test_taker_and_maker_bind_verified_release_and_stamp_summaries_and_tapes(
    tmp_path: Path,
) -> None:
    paths, _frozen, release, releases_root, pointer = _active_fixture(
        tmp_path / "release"
    )
    pointer_payload = json.loads(pointer.read_text(encoding="utf-8"))
    snapshots_root, promotion, observation_status = _write_release_bound_worker_inputs(
        tmp_path / "worker-inputs",
        release_id=release["release_id"],
        manifest_sha256=release["manifest_sha256"],
        pointer_sha256=pointer_payload["pointer_sha256"],
        sequence=pointer_payload["sequence"],
    )
    known_edge = tmp_path / "worker-inputs" / "known_edge.json"

    clear_process_serving_bundle_cache()
    try:
        taker = build_taker_run_once(
            TARGET_DATE,
            budget_usdc=12.0,
            markets="nyc",
            runs_root=tmp_path / "taker-runs",
            snapshots_root=snapshots_root,
            run_id="release-bound-taker",
            now=NOW,
            config={"counterfactual_tape_enabled": False},
            active_release_pointer_path=pointer,
            releases_root=releases_root,
            release_repo_root=paths["repo"],
            release_check_runtime=False,
        )
        maker = build_maker_run_once(
            TARGET_DATE,
            budget_usdc=25.0,
            mode="shadow",
            markets=["nyc"],
            runs_root=tmp_path / "maker-runs",
            snapshots_root=snapshots_root,
            promotion_refresh=promotion,
            known_edge_map=known_edge,
            observation_status_path=observation_status,
            run_id="release-bound-maker",
            now=NOW,
            active_release_pointer_path=pointer,
            releases_root=releases_root,
            release_repo_root=paths["repo"],
            release_check_runtime=False,
        )
    finally:
        clear_process_serving_bundle_cache()

    for payload in (taker, maker):
        assert payload["release_id"] == "r1"
        assert payload["release_manifest_sha256"] == release["manifest_sha256"]
        assert payload["release_identity_status"] == "verified_variant_serving_bundle"
        assert payload["base_model_release_bound"] is True
        persisted = json.loads(
            Path(payload["run_folder"], "run_summary.json").read_text(encoding="utf-8")
        )
        assert persisted["release_id"] == "r1"
        assert persisted["release_manifest_sha256"] == release["manifest_sha256"]

    _assert_release_stamped(_read_csv(taker["orders_path"]), release["manifest_sha256"])
    _assert_release_stamped(
        _read_csv(maker["quote_intents_path"]),
        release["manifest_sha256"],
    )


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


def test_taker_closes_incremental_store_when_raw_snapshot_binding_blocks(
    tmp_path: Path,
    monkeypatch,
) -> None:
    state = {"closed": False}

    class FakeIncrementalStore:
        def __init__(self, _run_folder):
            pass

        def prepare_tape(self, *_args, **_kwargs):
            return None

        def pending_tick(self):
            return {}

        def filled_rows(self, _name):
            return []

        def close(self):
            state["closed"] = True

    def fail_discovery(*_args, **_kwargs):
        raise WorkerReleaseBindingError("synthetic raw snapshot binding failure")

    monkeypatch.setattr(
        taker_bot_cli,
        "IncrementalTakerStore",
        FakeIncrementalStore,
    )
    monkeypatch.setattr(taker_bot_cli, "discover_inputs", fail_discovery)

    with pytest.raises(
        WorkerReleaseBindingError,
        match="synthetic raw snapshot binding failure",
    ):
        taker_bot_cli.build_run_once(
            TARGET_DATE,
            budget_usdc=1.0,
            markets="nyc",
            runs_root=tmp_path / "runs",
            snapshots_root=tmp_path / "snapshots",
            run_id="binding-close-test",
            now=NOW,
            observation_status_path=tmp_path / "observation-status.json",
        )

    assert state["closed"] is True


def test_tampered_snapshot_probability_blocks_against_hashed_capture(
    tmp_path: Path,
) -> None:
    paths, _frozen, release, releases_root, pointer = _active_fixture(
        tmp_path / "release"
    )
    pointer_payload = json.loads(pointer.read_text(encoding="utf-8"))
    snapshots_root, _promotion, _observation_status = (
        _write_release_bound_worker_inputs(
            tmp_path / "worker-inputs",
            release_id=release["release_id"],
            manifest_sha256=release["manifest_sha256"],
            pointer_sha256=pointer_payload["pointer_sha256"],
            sequence=pointer_payload["sequence"],
        )
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
    snapshots_root, _promotion, _observation_status = (
        _write_release_bound_worker_inputs(
            tmp_path / "worker-inputs",
            release_id=release["release_id"],
            manifest_sha256=release["manifest_sha256"],
            pointer_sha256=pointer_payload["pointer_sha256"],
            sequence=pointer_payload["sequence"],
        )
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
        replay["captured_input_hash"] = canonical_payload_sha256(
            {key: value for key, value in replay.items() if key != "captured_input_hash"}
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


def test_settled_taker_and_counterfactual_tapes_preserve_bound_lineage(
    tmp_path: Path,
) -> None:
    paths, _frozen, release, releases_root, pointer = _active_fixture(tmp_path)
    clear_process_serving_bundle_cache()
    try:
        binding = load_worker_release_binding(
            pointer_path=pointer,
            releases_root=releases_root,
            repo_root=paths["repo"],
            check_runtime=False,
        )
        lineage = {
            field: binding.lineage.get(field)
            for field in LINEAGE_FIELDS
        }
        settled_taker = tmp_path / "settled_orders_long.csv"
        settled_counterfactual = tmp_path / "settled_counterfactual_orders_long.csv"
        write_settled_worker_tape(
            settled_taker,
            ORDER_COLUMNS,
            [{"order_status": "FILLED", **lineage}],
        )
        write_settled_worker_tape(
            settled_counterfactual,
            COUNTERFACTUAL_ORDER_COLUMNS,
            [{"counterfactual_order_status": "WOULD_BUY", **lineage}],
        )

        for path, base_columns in (
            (settled_taker, ORDER_COLUMNS),
            (settled_counterfactual, COUNTERFACTUAL_ORDER_COLUMNS),
        ):
            with path.open("r", encoding="utf-8", newline="") as handle:
                header = next(csv.reader(handle))
            assert header == [*base_columns, *LINEAGE_FIELDS]
            _assert_release_stamped(_read_csv(path), release["manifest_sha256"])

        legacy = tmp_path / "settled_legacy_orders_long.csv"
        write_settled_worker_tape(legacy, ORDER_COLUMNS, [{"order_status": "NO_TRADE"}])
        with legacy.open("r", encoding="utf-8", newline="") as handle:
            assert next(csv.reader(handle)) == ORDER_COLUMNS
    finally:
        clear_process_serving_bundle_cache()
