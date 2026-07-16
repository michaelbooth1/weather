import json
import os
import threading
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest
import requests

from weather.collection.forecast_payload_cas import (
    ForecastPayloadCASIntegrityError,
    SharedForecastPayloadCAS,
    forecast_payload_byte_summary,
)
from weather.collection import forecast_payload_fetch_fanout as fanout_module
from weather.collection.forecast_payload_fetch_fanout import (
    CrossProcessMarketInvariantFetchFanout,
    MAX_RECEIPT_BYTES,
)
from weather.collection.snapshot_store import SnapshotStore
from weather.collection.snapshot_tracker import summarize_forecast_payload_storage
from weather.sources.nbm_probabilistic_tmax import (
    nbp_cycle_key_from_url,
    nbp_request_key,
    parse_nbp_station_tmax,
)


NBP_TEXT = """
 KBOS    NBM V5.0 NBP GUIDANCE    5/30/2026  0000 UTC
FHR    24  36| 48  60
TXNP5  70  58| 73  62

 KLGA    NBM V5.0 NBP GUIDANCE    5/30/2026  0000 UTC
FHR    24  36| 48  60
TXNP5  84  68| 80  69
"""
SOURCE_URL = (
    "https://nomads.ncep.noaa.gov/pub/data/nccf/com/blend/prod/"
    "blend.20260530/00/text/blend_nbptx.t00z"
)
REQUEST_KEY = nbp_request_key(SOURCE_URL)
CYCLE_KEY = nbp_cycle_key_from_url(SOURCE_URL)
FETCH_VALUE = {
    "text": NBP_TEXT,
    "fetched_at": "2026-05-30T01:00:00+00:00",
    "request_started_at": "2026-05-30T00:59:59+00:00",
    "response_received_at": "2026-05-30T01:00:00+00:00",
}


def _fetch(coordinator, fetch_fn, *, scope="fleet-pass-1"):
    return coordinator.fetch(
        source="nbm_probabilistic_tmax",
        request_key=REQUEST_KEY,
        cycle_key=CYCLE_KEY,
        scope_key=scope,
        fetch_fn=fetch_fn,
    )


def _source(station_id, result, *, scope="fleet-pass-1"):
    data = parse_nbp_station_tmax(
        result.value["text"],
        station_id,
        "2026-05-30",
        source_url=SOURCE_URL,
        fetched_at=result.value["fetched_at"],
    )
    data["raw_payload"]["forecast_payload_attestation"]["single_fetch"] = {
        "request_key": result.request_key,
        "cycle_key": result.cycle_key,
        "fetched": result.fetched,
        "reused": result.reused,
        "fetched_at": result.value["fetched_at"],
        "request_started_at": result.value["request_started_at"],
        "response_received_at": result.value["response_received_at"],
        "capture_pass_scope": scope,
        "coordination_status": result.coordination_status,
        "waited_seconds": result.waited_seconds,
        "wait_timed_out": result.wait_timed_out,
        "prepublished_payload_hash": result.prepublished_payload_hash,
        "prepublished_payload_bytes": result.prepublished_payload_bytes,
        "prepublished_payload_ref": result.prepublished_payload_ref,
        "prepublished_blob_created": result.prepublished_blob_created,
        "prepublished_blob_reused": result.prepublished_blob_reused,
        "coordinator_evidence_id": result.coordinator_evidence_id,
        "coordinator_receipt_ref": result.coordinator_receipt_ref,
        "coordinator_receipt_sha256": result.coordinator_receipt_sha256,
        "coordinator_attribution_status": result.coordinator_attribution_status,
        "coordinator_network_fetch_count": (
            result.coordinator_network_fetch_count
        ),
        "coordinator_payload_blob_created": (
            result.coordinator_payload_blob_created
        ),
        "coordinator_payload_blob_reused": (
            result.coordinator_payload_blob_reused
        ),
        "coordinator_physical_bytes_written": (
            result.coordinator_physical_bytes_written
        ),
    }
    return {
        "nbm_probabilistic_tmax": {
            "ok": True,
            "fetched_at": result.value["fetched_at"],
            "data": data,
        }
    }


def test_process_like_callers_fetch_once_and_account_one_prepublished_blob(tmp_path):
    root = tmp_path / "shared-cas"
    first = CrossProcessMarketInvariantFetchFanout(root, poll_seconds=0.002)
    second = CrossProcessMarketInvariantFetchFanout(root, poll_seconds=0.002)
    holder_started = threading.Event()
    release_holder = threading.Event()
    calls = []

    def holder_fetch():
        calls.append("holder")
        holder_started.set()
        assert release_holder.wait(timeout=2)
        return dict(FETCH_VALUE)

    def forbidden_waiter_fetch():
        calls.append("waiter")
        raise AssertionError("waiter must reuse the holder receipt")

    with ThreadPoolExecutor(max_workers=2) as pool:
        holder_future = pool.submit(_fetch, first, holder_fetch)
        assert holder_started.wait(timeout=2)
        waiter_future = pool.submit(_fetch, second, forbidden_waiter_fetch)
        release_holder.set()
        holder = holder_future.result(timeout=2)
        waiter = waiter_future.result(timeout=2)

    assert calls == ["holder"]
    assert holder.fetched is True
    assert holder.coordination_status == "cross_process_holder_published"
    assert holder.prepublished_blob_created is True
    assert waiter.reused is True
    assert waiter.coordination_status == "cross_process_receipt_reused"
    assert waiter.value == holder.value
    assert len(list(root.rglob("*.blob"))) == 1
    assert len(list(root.rglob("*.receipt.json"))) == 1
    assert list(root.rglob("*.claim")) == []

    # Persist the follower first to prove accounting does not depend on market
    # completion order.  The holder's manifest still owns the one physical
    # write that happened before either per-market writer ran.
    bos_store = SnapshotStore(
        root=tmp_path / "bos-event",
        event_slug="bos-event",
        shared_forecast_payload_cas_root=root,
    )
    ny_store = SnapshotStore(
        root=tmp_path / "ny-event",
        event_slug="ny-event",
        shared_forecast_payload_cas_root=root,
    )
    bos_store.root.mkdir(parents=True)
    ny_store.root.mkdir(parents=True)
    bos_row = bos_store.write_forecast_payloads(
        _source("KBOS", waiter),
        "bos-snapshot",
        datetime(2026, 5, 30, 1, 1, tzinfo=timezone.utc),
        "model-v",
        config_identity={"market_id": "boston", "target_date": "2026-05-30"},
    )[0]
    ny_row = ny_store.write_forecast_payloads(
        _source("KLGA", holder),
        "ny-snapshot",
        datetime(2026, 5, 30, 1, 2, tzinfo=timezone.utc),
        "model-v",
        config_identity={"market_id": "nyc", "target_date": "2026-05-30"},
    )[0]

    summary = forecast_payload_byte_summary([bos_row, ny_row])
    assert summary["network_fetch_count"] == 1
    assert summary["network_reuse_count"] == 1
    assert summary["cross_process_reuse_count"] == 1
    assert summary["network_wait_timeout_fail_open_count"] == 0
    assert summary["created_blob_count"] == 1
    assert summary["reused_blob_count"] == 1
    assert summary["physical_bytes_written"] == len(NBP_TEXT.encode("utf-8"))


def test_wait_timeout_fails_open_to_callers_normal_fetch(tmp_path):
    root = tmp_path / "shared-cas"
    holder_coordinator = CrossProcessMarketInvariantFetchFanout(
        root,
        wait_timeout_seconds=1,
        poll_seconds=0.002,
    )
    waiter_coordinator = CrossProcessMarketInvariantFetchFanout(
        root,
        wait_timeout_seconds=0.02,
        poll_seconds=0.002,
    )
    holder_started = threading.Event()
    release_holder = threading.Event()
    calls = []

    def holder_fetch():
        calls.append("holder")
        holder_started.set()
        assert release_holder.wait(timeout=2)
        return dict(FETCH_VALUE)

    def fail_open_fetch():
        calls.append("fail-open")
        return {**FETCH_VALUE, "text": NBP_TEXT + "\nfail-open"}

    with ThreadPoolExecutor(max_workers=2) as pool:
        holder_future = pool.submit(_fetch, holder_coordinator, holder_fetch)
        assert holder_started.wait(timeout=2)
        waiter = pool.submit(
            _fetch,
            waiter_coordinator,
            fail_open_fetch,
        ).result(timeout=2)
        release_holder.set()
        holder_future.result(timeout=2)

    assert calls == ["holder", "fail-open"]
    assert waiter.fetched is True
    assert waiter.reused is False
    assert waiter.wait_timed_out is True
    assert waiter.coordination_status == "cross_process_wait_timeout_fail_open"
    assert waiter.value["text"].endswith("fail-open")


def test_holder_http_backoff_outcome_is_shared_without_second_provider_call(tmp_path):
    root = tmp_path / "shared-cas"
    first = CrossProcessMarketInvariantFetchFanout(root, poll_seconds=0.002)
    second = CrossProcessMarketInvariantFetchFanout(root, poll_seconds=0.002)
    holder_started = threading.Event()
    release_holder = threading.Event()
    calls = []

    def unavailable_fetch():
        calls.append("holder")
        holder_started.set()
        assert release_holder.wait(timeout=2)
        response = requests.Response()
        response.status_code = 404
        raise requests.HTTPError("not published", response=response)

    def forbidden_waiter_fetch():
        calls.append("waiter")
        return dict(FETCH_VALUE)

    with ThreadPoolExecutor(max_workers=2) as pool:
        holder_future = pool.submit(_fetch, first, unavailable_fetch)
        assert holder_started.wait(timeout=2)
        waiter_future = pool.submit(_fetch, second, forbidden_waiter_fetch)
        release_holder.set()
        errors = []
        for future in (holder_future, waiter_future):
            with pytest.raises(requests.HTTPError) as caught:
                future.result(timeout=2)
            errors.append(caught.value)

    assert calls == ["holder"]
    assert [error.response.status_code for error in errors] == [404, 404]
    assert len(list(root.rglob("*.receipt.json"))) == 1


def test_receipt_symlink_is_rejected_without_provider_fetch(tmp_path):
    root = tmp_path / "shared-cas"
    coordinator = CrossProcessMarketInvariantFetchFanout(root)
    receipt_path, _ = coordinator._paths(
        "nbm_probabilistic_tmax",
        REQUEST_KEY,
        CYCLE_KEY,
        "fleet-pass-1",
    )
    target = tmp_path / "outside-receipt.json"
    target.write_text("{}\n", encoding="utf-8")
    receipt_path.parent.mkdir(parents=True)
    try:
        receipt_path.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")
    calls = []

    with pytest.raises(
        ForecastPayloadCASIntegrityError,
        match="regular non-reparse file",
    ):
        _fetch(coordinator, lambda: calls.append("provider") or dict(FETCH_VALUE))

    assert calls == []


def test_receipt_parent_symlink_or_reparse_is_rejected_without_provider_fetch(
    tmp_path,
    monkeypatch,
):
    root = tmp_path / "shared-cas"
    coordinator = CrossProcessMarketInvariantFetchFanout(root)
    receipt_path, _ = coordinator._paths(
        "nbm_probabilistic_tmax",
        REQUEST_KEY,
        CYCLE_KEY,
        "fleet-pass-1",
    )
    receipt_path.parent.parent.mkdir(parents=True)
    outside = tmp_path / "outside-receipt-parent"
    outside.mkdir()
    try:
        receipt_path.parent.symlink_to(outside, target_is_directory=True)
    except OSError:
        receipt_path.parent.mkdir()
        original_lstat = fanout_module.os.lstat

        class ReparseStat:
            def __init__(self, wrapped):
                self._wrapped = wrapped
                self.st_file_attributes = int(
                    getattr(wrapped, "st_file_attributes", 0) or 0
                ) | fanout_module._FILE_ATTRIBUTE_REPARSE_POINT

            def __getattr__(self, name):
                return getattr(self._wrapped, name)

        def lstat_with_reparse_parent(path):
            value = original_lstat(path)
            if os.path.abspath(path) == os.path.abspath(receipt_path.parent):
                return ReparseStat(value)
            return value

        monkeypatch.setattr(
            fanout_module.os,
            "lstat",
            lstat_with_reparse_parent,
        )
    calls = []

    with pytest.raises(
        ForecastPayloadCASIntegrityError,
        match="ancestor is not a regular non-reparse directory",
    ):
        _fetch(coordinator, lambda: calls.append("provider") or dict(FETCH_VALUE))

    assert calls == []


def test_oversized_receipt_is_rejected_before_json_decode(tmp_path):
    root = tmp_path / "shared-cas"
    coordinator = CrossProcessMarketInvariantFetchFanout(root)
    receipt_path, _ = coordinator._paths(
        "nbm_probabilistic_tmax",
        REQUEST_KEY,
        CYCLE_KEY,
        "fleet-pass-1",
    )
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_bytes(b"{" + b" " * MAX_RECEIPT_BYTES)

    with pytest.raises(ForecastPayloadCASIntegrityError, match="exceeds"):
        _fetch(coordinator, lambda: dict(FETCH_VALUE))


def test_receipt_mutation_during_read_is_rejected(tmp_path, monkeypatch):
    root = tmp_path / "shared-cas"
    coordinator = CrossProcessMarketInvariantFetchFanout(root)
    receipt_path, _ = coordinator._paths(
        "nbm_probabilistic_tmax",
        REQUEST_KEY,
        CYCLE_KEY,
        "fleet-pass-1",
    )
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_text("{}\n", encoding="utf-8")
    original_read = fanout_module.os.read
    mutated = False

    def read_and_mutate(handle, size):
        nonlocal mutated
        value = original_read(handle, size)
        if not mutated:
            mutated = True
            current = os.lstat(receipt_path)
            os.utime(
                receipt_path,
                ns=(current.st_atime_ns, current.st_mtime_ns + 1_000_000_000),
            )
        return value

    monkeypatch.setattr(fanout_module.os, "read", read_and_mutate)
    with pytest.raises(ForecastPayloadCASIntegrityError, match="mutated during read"):
        _fetch(coordinator, lambda: dict(FETCH_VALUE))

    assert mutated is True


def test_payload_semantic_cycle_must_match_requested_cycle(tmp_path):
    root = tmp_path / "shared-cas"
    coordinator = CrossProcessMarketInvariantFetchFanout(root)
    wrong_cycle = {
        **FETCH_VALUE,
        "text": NBP_TEXT.replace("0000 UTC", "0600 UTC"),
    }

    with pytest.raises(
        ForecastPayloadCASIntegrityError,
        match="requested NBM cycle",
    ):
        _fetch(coordinator, lambda: wrong_cycle)

    assert list(root.rglob("*.blob")) == []


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("not an NBM bulletin", "does not contain"),
        (
            NBP_TEXT.replace(
                "KLGA    NBM V5.0 NBP GUIDANCE    5/30/2026  0000 UTC",
                "KLGA    NBM V5.0 NBP GUIDANCE    5/30/2026  0600 UTC",
            ),
            "inconsistent",
        ),
        (NBP_TEXT.replace("0000 UTC", "0030 UTC"), "not an hourly"),
        (NBP_TEXT.replace("0000 UTC", "0600 UTC"), "requested NBM cycle"),
    ],
)
def test_malformed_or_mismatched_bulletin_semantics_fail_closed(
    tmp_path,
    text,
    message,
):
    coordinator = CrossProcessMarketInvariantFetchFanout(tmp_path / "cas")
    with pytest.raises(ForecastPayloadCASIntegrityError, match=message):
        _fetch(coordinator, lambda: {**FETCH_VALUE, "text": text})


def test_unscoped_and_timeout_fail_open_results_validate_bulletin_cycle(tmp_path):
    wrong_cycle = {
        **FETCH_VALUE,
        "text": NBP_TEXT.replace("0000 UTC", "0600 UTC"),
    }
    unscoped = CrossProcessMarketInvariantFetchFanout(tmp_path / "unscoped")
    with pytest.raises(ForecastPayloadCASIntegrityError, match="requested NBM cycle"):
        unscoped.fetch(
            source="nbm_probabilistic_tmax",
            request_key=REQUEST_KEY,
            cycle_key=CYCLE_KEY,
            fetch_fn=lambda: wrong_cycle,
        )

    root = tmp_path / "timeout"
    holder_coordinator = CrossProcessMarketInvariantFetchFanout(
        root,
        wait_timeout_seconds=1,
        poll_seconds=0.002,
    )
    waiter_coordinator = CrossProcessMarketInvariantFetchFanout(
        root,
        wait_timeout_seconds=0.01,
        poll_seconds=0.002,
    )
    holder_started = threading.Event()
    release_holder = threading.Event()

    def holder_fetch():
        holder_started.set()
        assert release_holder.wait(timeout=2)
        return dict(FETCH_VALUE)

    with ThreadPoolExecutor(max_workers=2) as pool:
        holder_future = pool.submit(_fetch, holder_coordinator, holder_fetch)
        assert holder_started.wait(timeout=2)
        with pytest.raises(
            ForecastPayloadCASIntegrityError,
            match="requested NBM cycle",
        ):
            _fetch(waiter_coordinator, lambda: wrong_cycle)
        release_holder.set()
        holder_future.result(timeout=2)


def test_legacy_v01_success_receipt_is_read_with_unknown_attribution(tmp_path):
    root = tmp_path / "shared-cas"
    coordinator = CrossProcessMarketInvariantFetchFanout(root)
    stored = coordinator.cas.put(NBP_TEXT.encode("utf-8"))
    receipt_path, _ = coordinator._paths(
        "nbm_probabilistic_tmax",
        REQUEST_KEY,
        CYCLE_KEY,
        "fleet-pass-1",
    )
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_receipt = {
        "schema_version": fanout_module.RECEIPT_SCHEMA_VERSION,
        "source": "nbm_probabilistic_tmax",
        "request_key": REQUEST_KEY,
        "cycle_key": CYCLE_KEY,
        "scope_key": "fleet-pass-1",
        "status": "success",
        "fetched_at": FETCH_VALUE["fetched_at"],
        "request_started_at": FETCH_VALUE["request_started_at"],
        "response_received_at": FETCH_VALUE["response_received_at"],
        "payload_hash": stored["payload_hash"],
        "payload_bytes": stored["payload_bytes"],
        "payload_ref": stored["payload_ref"],
    }
    receipt_path.write_text(
        json.dumps(legacy_receipt, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    result = _fetch(
        CrossProcessMarketInvariantFetchFanout(root),
        lambda: pytest.fail("legacy receipt must be reused"),
    )
    assert result.reused is True
    assert (
        result.coordinator_attribution_status
        == "legacy_receipt_attribution_unavailable"
    )
    assert result.coordinator_evidence_id is None
    assert result.coordinator_receipt_sha256


def test_two_scope_receipts_count_two_fetches_but_one_physical_write(tmp_path):
    root = tmp_path / "shared-cas"
    first = _fetch(
        CrossProcessMarketInvariantFetchFanout(root),
        lambda: dict(FETCH_VALUE),
        scope="fleet-pass-1",
    )
    second = _fetch(
        CrossProcessMarketInvariantFetchFanout(root),
        lambda: dict(FETCH_VALUE),
        scope="fleet-pass-2",
    )
    assert first.coordinator_payload_blob_created is True
    assert second.coordinator_payload_blob_reused is True

    rows = []
    for index, (result, scope) in enumerate(
        ((first, "fleet-pass-1"), (second, "fleet-pass-2")),
        start=1,
    ):
        store = SnapshotStore(
            root=tmp_path / f"event-{index}",
            event_slug=f"event-{index}",
            shared_forecast_payload_cas_root=root,
        )
        store.root.mkdir(parents=True)
        rows.extend(
            store.write_forecast_payloads(
                _source("KLGA", result, scope=scope),
                f"snapshot-{index}",
                datetime(2026, 5, 30, 1, index, tzinfo=timezone.utc),
                "model-v",
                config_identity={
                    "market_id": "nyc",
                    "target_date": "2026-05-30",
                },
            )
        )
    summary = forecast_payload_byte_summary(rows)
    assert summary["coordinator_evidence_count"] == 2
    assert summary["network_fetch_count"] == 2
    assert summary["physical_bytes_written"] == len(NBP_TEXT.encode("utf-8"))


def test_preexisting_cas_blob_records_one_fetch_and_zero_physical_bytes(tmp_path):
    root = tmp_path / "shared-cas"
    SharedForecastPayloadCAS(root).put(NBP_TEXT.encode("utf-8"))
    result = _fetch(
        CrossProcessMarketInvariantFetchFanout(root),
        lambda: dict(FETCH_VALUE),
    )
    assert result.coordinator_payload_blob_reused is True
    store = SnapshotStore(
        root=tmp_path / "event",
        event_slug="event",
        shared_forecast_payload_cas_root=root,
    )
    store.root.mkdir(parents=True)
    row = store.write_forecast_payloads(
        _source("KLGA", result),
        "snapshot",
        datetime(2026, 5, 30, 1, 1, tzinfo=timezone.utc),
        "model-v",
        config_identity={"market_id": "nyc", "target_date": "2026-05-30"},
    )[0]
    summary = forecast_payload_byte_summary([row])
    assert summary["network_fetch_count"] == 1
    assert summary["physical_bytes_written"] == 0
    assert summary["avoided_bytes"] == len(NBP_TEXT.encode("utf-8"))


def test_timeout_fetch_plus_holder_counts_two_fetches_and_one_write(tmp_path):
    root = tmp_path / "shared-cas"
    holder_coordinator = CrossProcessMarketInvariantFetchFanout(
        root,
        wait_timeout_seconds=1,
        poll_seconds=0.002,
    )
    waiter_coordinator = CrossProcessMarketInvariantFetchFanout(
        root,
        wait_timeout_seconds=0.01,
        poll_seconds=0.002,
    )
    holder_started = threading.Event()
    release_holder = threading.Event()

    def holder_fetch():
        holder_started.set()
        assert release_holder.wait(timeout=2)
        return dict(FETCH_VALUE)

    with ThreadPoolExecutor(max_workers=2) as pool:
        holder_future = pool.submit(_fetch, holder_coordinator, holder_fetch)
        assert holder_started.wait(timeout=2)
        waiter = _fetch(waiter_coordinator, lambda: dict(FETCH_VALUE))
        waiter_store = SnapshotStore(
            root=tmp_path / "waiter-event",
            event_slug="waiter-event",
            shared_forecast_payload_cas_root=root,
        )
        waiter_store.root.mkdir(parents=True)
        waiter_row = waiter_store.write_forecast_payloads(
            _source("KBOS", waiter),
            "waiter",
            datetime(2026, 5, 30, 1, 1, tzinfo=timezone.utc),
            "model-v",
            config_identity={
                "market_id": "boston",
                "target_date": "2026-05-30",
            },
        )[0]
        release_holder.set()
        holder = holder_future.result(timeout=2)
    holder_store = SnapshotStore(
        root=tmp_path / "holder-event",
        event_slug="holder-event",
        shared_forecast_payload_cas_root=root,
    )
    holder_store.root.mkdir(parents=True)
    holder_row = holder_store.write_forecast_payloads(
        _source("KLGA", holder),
        "holder",
        datetime(2026, 5, 30, 1, 2, tzinfo=timezone.utc),
        "model-v",
        config_identity={"market_id": "nyc", "target_date": "2026-05-30"},
    )[0]
    summary = forecast_payload_byte_summary([waiter_row, holder_row])
    payload_bytes = len(NBP_TEXT.encode("utf-8"))
    assert summary["network_fetch_count"] == 2
    assert summary["physical_bytes_written"] == payload_bytes
    assert summary["avoided_bytes"] == payload_bytes


def test_receipt_evidence_accounts_once_when_holder_never_writes_manifest(tmp_path):
    root = tmp_path / "shared-cas"
    holder = _fetch(
        CrossProcessMarketInvariantFetchFanout(root),
        lambda: dict(FETCH_VALUE),
    )
    assert holder.coordinator_payload_blob_created is True

    def forbidden_fetch():
        raise AssertionError("followers must consume the published receipt")

    follower_one = _fetch(
        CrossProcessMarketInvariantFetchFanout(root),
        forbidden_fetch,
    )
    follower_two = _fetch(
        CrossProcessMarketInvariantFetchFanout(root),
        forbidden_fetch,
    )
    assert follower_one.coordinator_evidence_id == holder.coordinator_evidence_id
    assert follower_two.coordinator_evidence_id == holder.coordinator_evidence_id

    bos_store = SnapshotStore(
        root=tmp_path / "bos-event",
        event_slug="bos-event",
        shared_forecast_payload_cas_root=root,
    )
    ny_store = SnapshotStore(
        root=tmp_path / "ny-event",
        event_slug="ny-event",
        shared_forecast_payload_cas_root=root,
    )
    bos_store.root.mkdir(parents=True)
    ny_store.root.mkdir(parents=True)
    bos_row = bos_store.write_forecast_payloads(
        _source("KBOS", follower_one),
        "bos-follower",
        datetime(2026, 5, 30, 1, 1, tzinfo=timezone.utc),
        "model-v",
        config_identity={"market_id": "boston", "target_date": "2026-05-30"},
    )[0]
    ny_row = ny_store.write_forecast_payloads(
        _source("KLGA", follower_two),
        "ny-follower",
        datetime(2026, 5, 30, 1, 2, tzinfo=timezone.utc),
        "model-v",
        config_identity={"market_id": "nyc", "target_date": "2026-05-30"},
    )[0]

    assert bos_row["single_fetch_fetched"] is False
    assert ny_row["single_fetch_fetched"] is False
    assert bos_row["payload_blob_reused"] is True
    assert ny_row["payload_blob_reused"] is True
    summary = forecast_payload_byte_summary([bos_row, ny_row])
    payload_bytes = len(NBP_TEXT.encode("utf-8"))
    assert summary["coordinator_evidence_count"] == 1
    assert summary["coordinator_network_fetch_count"] == 1
    assert summary["network_fetch_count"] == 1
    assert summary["coordinator_physical_bytes_written"] == payload_bytes
    assert summary["physical_bytes_written"] == payload_bytes
    assert summary["logical_referenced_bytes"] == 2 * payload_bytes
    assert summary["avoided_bytes"] == payload_bytes

    fleet_summary = summarize_forecast_payload_storage(
        {
            "boston": {
                "forecast_payload_storage": forecast_payload_byte_summary(
                    [bos_row]
                )
            },
            "nyc": {
                "forecast_payload_storage": forecast_payload_byte_summary(
                    [ny_row]
                )
            },
        }
    )
    assert fleet_summary["coordinator_evidence_count"] == 1
    assert fleet_summary["network_fetch_count"] == 1
    assert fleet_summary["physical_bytes_written"] == payload_bytes
    assert fleet_summary["avoided_bytes"] == payload_bytes
    assert len(fleet_summary["coordinator_attributions"]) == 1

    conflicting = deepcopy(
        forecast_payload_byte_summary([ny_row])
    )
    conflicting["coordinator_attributions"][0][
        "coordinator_receipt_sha256"
    ] = "f" * 64
    with pytest.raises(ValueError, match="conflicts across records"):
        summarize_forecast_payload_storage(
            {
                "boston": {
                    "forecast_payload_storage": forecast_payload_byte_summary(
                        [bos_row]
                    )
                },
                "nyc": {"forecast_payload_storage": conflicting},
            }
        )
