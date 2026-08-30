from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from weather.market import mm_geographic_eligibility as geography


NOW = datetime(2026, 8, 24, 5, 0, tzinfo=timezone.utc)
SOURCE_ADDRESS = "203.0.113.17"


class ResponseStub:
    def __init__(
        self,
        payload,
        *,
        status: int = 200,
        content_type: str = "application/json",
        final_url: str = geography.GEOBLOCK_ENDPOINT,
    ):
        self.status = status
        self.headers = {"Content-Type": content_type}
        self._raw = (
            payload
            if isinstance(payload, bytes)
            else json.dumps(payload, separators=(",", ":")).encode("utf-8")
        )
        self._final_url = final_url
        self.closed = False

    def read(self, _size: int) -> bytes:
        return self._raw

    def geturl(self) -> str:
        return self._final_url

    def close(self) -> None:
        self.closed = True


class OpenerStub:
    def __init__(self, response: ResponseStub):
        self.response = response
        self.calls = []

    def __call__(self, request, *, timeout):
        self.calls.append((request, timeout))
        return self.response


def official_payload(*, blocked: bool = False) -> dict:
    return {
        "blocked": blocked,
        "ip": SOURCE_ADDRESS,
        "country": "GB",
        "region": "ENG",
    }


def run_check(tmp_path, payload=None, **overrides):
    response = ResponseStub(official_payload() if payload is None else payload)
    opener = OpenerStub(response)
    receipt_path = tmp_path / "geography.json"
    receipt = geography.check_geographic_eligibility(
        receipt_path,
        confirmation=geography.PHYSICAL_LOCATION_CONFIRMATION,
        physical_location_eligible=True,
        no_circumvention=True,
        opener=opener,
        clock=lambda: NOW,
        **overrides,
    )
    return receipt, receipt_path, opener


def test_eligible_official_check_is_exact_fresh_and_self_bound(tmp_path):
    receipt, receipt_path, opener = run_check(tmp_path)

    request, timeout = opener.calls[0]
    assert request.full_url == geography.GEOBLOCK_ENDPOINT
    assert request.get_method() == "GET"
    assert request.get_header("Authorization") is None
    assert request.get_header("Cache-control") == "no-cache, no-store, max-age=0"
    assert timeout == geography.REQUEST_TIMEOUT_SECONDS
    assert receipt["status"] == "PASS"
    assert receipt["eligible"] is True
    assert receipt["agreement"] is True
    assert receipt["freshness_max_age_seconds"] == 60
    assert receipt_path.is_file()
    assert (
        geography.validate_geographic_eligibility_receipt(receipt, now=NOW)
        == receipt
    )


def test_official_blocked_response_spends_receipt_and_refuses(tmp_path):
    response = ResponseStub(official_payload(blocked=True))
    path = tmp_path / "blocked.json"

    with pytest.raises(geography.GeographicEligibilityError) as caught:
        geography.check_geographic_eligibility(
            path,
            confirmation=geography.PHYSICAL_LOCATION_CONFIRMATION,
            physical_location_eligible=True,
            no_circumvention=True,
            opener=OpenerStub(response),
            clock=lambda: NOW,
        )

    assert caught.value.blocker_code == "OFFICIAL_LOCATION_BLOCKED"
    receipt = json.loads(path.read_text(encoding="utf-8"))
    assert receipt["status"] == "FAIL"
    assert receipt["eligible"] is False
    assert receipt["blocker_code"] == "OFFICIAL_LOCATION_BLOCKED"


@pytest.mark.parametrize(
    "payload",
    (
        b"not-json",
        {"blocked": False, "country": "GB", "region": "ENG"},
        {"blocked": "false", "ip": SOURCE_ADDRESS, "country": "GB", "region": "ENG"},
    ),
)
def test_malformed_official_response_is_refused(tmp_path, payload):
    path = tmp_path / "malformed.json"

    with pytest.raises(geography.GeographicEligibilityError) as caught:
        geography.check_geographic_eligibility(
            path,
            confirmation=geography.PHYSICAL_LOCATION_CONFIRMATION,
            physical_location_eligible=True,
            no_circumvention=True,
            opener=OpenerStub(ResponseStub(payload)),
            clock=lambda: NOW,
        )

    assert caught.value.blocker_code == "MALFORMED_OFFICIAL_RESPONSE"
    assert json.loads(path.read_text(encoding="utf-8"))["status"] == "FAIL"


def test_previously_valid_receipt_is_refused_after_freshness_window(tmp_path):
    receipt, _path, _opener = run_check(tmp_path)

    with pytest.raises(geography.GeographicEligibilityError) as caught:
        geography.validate_geographic_eligibility_receipt(
            receipt,
            now=NOW + timedelta(seconds=61),
        )

    assert caught.value.blocker_code == "RECEIPT_STALE"


def test_public_and_physical_location_disagreement_is_refused(tmp_path):
    path = tmp_path / "disagreement.json"

    with pytest.raises(geography.GeographicEligibilityError) as caught:
        geography.check_geographic_eligibility(
            path,
            confirmation=geography.PHYSICAL_LOCATION_CONFIRMATION,
            physical_location_eligible=False,
            no_circumvention=True,
            opener=OpenerStub(ResponseStub(official_payload())),
            clock=lambda: NOW,
        )

    assert caught.value.blocker_code == "PUBLIC_PHYSICAL_LOCATION_DISAGREEMENT"
    receipt = json.loads(path.read_text(encoding="utf-8"))
    assert receipt["agreement"] is False
    assert receipt["eligible"] is False


def test_source_ip_is_validated_but_never_retained(tmp_path):
    receipt, receipt_path, _opener = run_check(tmp_path)
    serialized = receipt_path.read_text(encoding="utf-8")

    assert SOURCE_ADDRESS not in serialized
    assert "ip" not in receipt["official"]
    assert receipt["privacy"]["source_address_retained"] is False
    assert receipt["response_binding"]["redacted_body_sha256"]


def test_retained_decision_or_receipt_hash_tampering_is_refused(tmp_path):
    receipt, _path, _opener = run_check(tmp_path)
    receipt["official"]["country"] = "FR"

    with pytest.raises(geography.GeographicEligibilityError):
        geography.validate_geographic_eligibility_receipt(
            receipt,
            now=NOW,
        )
