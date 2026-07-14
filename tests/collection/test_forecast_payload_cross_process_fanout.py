import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest
import requests

from weather.collection.forecast_payload_cas import forecast_payload_byte_summary
from weather.collection.forecast_payload_fetch_fanout import (
    CrossProcessMarketInvariantFetchFanout,
)
from weather.collection.snapshot_store import SnapshotStore
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


def _source(station_id, result):
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
        "capture_pass_scope": "fleet-pass-1",
        "coordination_status": result.coordination_status,
        "waited_seconds": result.waited_seconds,
        "wait_timed_out": result.wait_timed_out,
        "prepublished_payload_hash": result.prepublished_payload_hash,
        "prepublished_payload_bytes": result.prepublished_payload_bytes,
        "prepublished_payload_ref": result.prepublished_payload_ref,
        "prepublished_blob_created": result.prepublished_blob_created,
        "prepublished_blob_reused": result.prepublished_blob_reused,
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
