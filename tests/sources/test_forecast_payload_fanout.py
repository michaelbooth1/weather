from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from weather.model.model_sources import SourceFetchMixin
from weather.model.source_adapters import FETCH_META_KEY, fetch_source
from weather.sources.forecast_payload_fanout import MarketInvariantFetchFanout


NBP_TEXT = """
 KBOS    NBM V5.0 NBP GUIDANCE    5/30/2026  0000 UTC
FHR    24  36| 48  60
TXNP5  70  58| 73  62

 KLGA    NBM V5.0 NBP GUIDANCE    5/30/2026  0000 UTC
FHR    24  36| 48  60
TXNP5  84  68| 80  69
"""


class StubNbmModel(SourceFetchMixin):
    def __init__(self, station_id, fanout, calls, *, scope="capture-pass-1"):
        self.spec = SimpleNamespace(
            wu_history_id="KNYC:US",
            icao=station_id,
            tz=timezone.utc,
        )
        self.target_date = date(2026, 5, 30)
        self.market_invariant_fetch_fanout = fanout
        self.market_invariant_fetch_scope = scope
        self.calls = calls

    def get_text(self, _url, headers=None):
        self.calls.append(self.spec.icao)
        return NBP_TEXT


def test_nbm_same_cycle_fetches_once_and_fans_out_market_specific_parses():
    fanout = MarketInvariantFetchFanout(max_entries=2)
    calls = []
    cycle = datetime(2026, 5, 30, 0, tzinfo=timezone.utc)
    ny = StubNbmModel("KLGA", fanout, calls)
    bos = StubNbmModel("KBOS", fanout, calls)

    with patch(
        "weather.model.model_sources.nbp_cycle_candidates",
        return_value=[cycle],
    ):
        ny_payload = ny.fetch_nbm_probabilistic_tmax()
        bos_payload = bos.fetch_nbm_probabilistic_tmax()

    assert calls == ["KLGA"]
    assert ny_payload["station_id"] == "KLGA"
    assert bos_payload["station_id"] == "KBOS"
    ny_attestation = ny_payload["raw_payload"]["forecast_payload_attestation"]
    bos_attestation = bos_payload["raw_payload"]["forecast_payload_attestation"]
    assert ny_attestation["single_fetch"]["fetched"] is True
    assert bos_attestation["single_fetch"]["reused"] is True
    assert ny_payload["fetched_at"] == bos_payload["fetched_at"]
    assert ny_payload[FETCH_META_KEY]["status"] == "fresh"
    assert bos_payload[FETCH_META_KEY]["status"] == "fresh_cache"
    assert (
        ny_attestation["single_fetch"]["request_started_at"]
        == bos_attestation["single_fetch"]["request_started_at"]
    )
    assert (
        ny_attestation["single_fetch"]["response_received_at"]
        == bos_attestation["single_fetch"]["response_received_at"]
    )
    assert (
        ny_attestation["request_key"]
        == bos_attestation["request_key"]
    )
    assert (
        ny_attestation["extraction_identity"]
        != bos_attestation["extraction_identity"]
    )


def test_fanout_does_not_reuse_across_cycle_keys():
    fanout = MarketInvariantFetchFanout(max_entries=2)
    calls = []

    first = fanout.fetch(
        source="nbm",
        request_key="request-a",
        cycle_key="cycle-a",
        fetch_fn=lambda: calls.append("a") or "payload-a",
    )
    second = fanout.fetch(
        source="nbm",
        request_key="request-b",
        cycle_key="cycle-b",
        fetch_fn=lambda: calls.append("b") or "payload-b",
    )

    assert first.value == "payload-a"
    assert second.value == "payload-b"
    assert calls == ["a", "b"]


def test_completed_fanout_is_capture_pass_scoped_and_provider_updates_are_visible():
    fanout = MarketInvariantFetchFanout(max_entries=2)
    responses = iter(["provider-version-1", "provider-version-2", "provider-version-3"])
    calls = []

    def fetch():
        value = next(responses)
        calls.append(value)
        return value

    first = fanout.fetch(
        source="nbm",
        request_key="same-url",
        cycle_key="same-cycle",
        scope_key="capture-pass-1",
        fetch_fn=fetch,
    )
    same_pass = fanout.fetch(
        source="nbm",
        request_key="same-url",
        cycle_key="same-cycle",
        scope_key="capture-pass-1",
        fetch_fn=fetch,
    )
    next_pass = fanout.fetch(
        source="nbm",
        request_key="same-url",
        cycle_key="same-cycle",
        scope_key="capture-pass-2",
        fetch_fn=fetch,
    )
    unscoped_first = fanout.fetch(
        source="nbm",
        request_key="same-url",
        cycle_key="same-cycle",
        fetch_fn=fetch,
    )

    assert first.value == same_pass.value == "provider-version-1"
    assert same_pass.reused is True
    assert next_pass.value == "provider-version-2"
    assert next_pass.fetched is True
    assert unscoped_first.value == "provider-version-3"
    assert calls == [
        "provider-version-1",
        "provider-version-2",
        "provider-version-3",
    ]


def test_source_wrapper_retains_original_fanout_attempt_provenance():
    fanout = MarketInvariantFetchFanout(max_entries=2)
    calls = []
    cycle = datetime(2026, 5, 30, 0, tzinfo=timezone.utc)
    ny = StubNbmModel("KLGA", fanout, calls)
    bos = StubNbmModel("KBOS", fanout, calls)
    outer_time = datetime(2030, 1, 1, tzinfo=timezone.utc)

    with patch(
        "weather.model.model_sources.nbp_cycle_candidates",
        return_value=[cycle],
    ):
        _, ny_source = fetch_source(
            "nbm_probabilistic_tmax",
            ny.fetch_nbm_probabilistic_tmax,
            now_fn=lambda: outer_time,
        )
        _, bos_source = fetch_source(
            "nbm_probabilistic_tmax",
            bos.fetch_nbm_probabilistic_tmax,
            now_fn=lambda: outer_time,
        )

    ny_single_fetch = ny_source["data"]["raw_payload"][
        "forecast_payload_attestation"
    ]["single_fetch"]
    bos_single_fetch = bos_source["data"]["raw_payload"][
        "forecast_payload_attestation"
    ]["single_fetch"]
    assert calls == ["KLGA"]
    assert ny_source["status"] == "fresh"
    assert bos_source["status"] == "fresh_cache"
    assert ny_source["fetched_at"] == bos_source["fetched_at"]
    assert ny_source["request_started_at"] == bos_source["request_started_at"]
    assert ny_source["response_received_at"] == bos_source["response_received_at"]
    assert ny_source["request_started_at"] == ny_single_fetch["request_started_at"]
    assert bos_source["response_received_at"] == bos_single_fetch[
        "response_received_at"
    ]
    assert ny_source["request_started_at"] != outer_time.isoformat()
