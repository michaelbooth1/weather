import json

import pytest

from weather.market.mm_geoblock import (
    collect_official_geoblock_evidence,
    geoblock_evidence_gate,
)


NOW = "2026-08-13T19:00:00+00:00"


class Response:
    status = 200

    def __init__(self, payload):
        self.payload = payload
        self.closed = False

    def read(self, _limit):
        return json.dumps(self.payload).encode("utf-8")

    def close(self):
        self.closed = True


def collect(payload, *, proxies=None):
    response = Response(payload)
    evidence = collect_official_geoblock_evidence(
        opener=lambda _request, timeout: response,
        proxy_detector=lambda: proxies or {},
        now=NOW,
    )
    assert response.closed
    return evidence


def test_eligible_official_response_is_fresh_content_bound_and_redacts_ip():
    evidence = collect({
        "blocked": False,
        "country": "CH",
        "region": "ZH",
        "ip": "203.0.113.8",
    })

    gate = geoblock_evidence_gate(evidence, now=NOW)

    assert gate["ok"], gate["missing"]
    assert "ip" not in evidence
    assert "203.0.113.8" not in json.dumps(evidence, sort_keys=True)
    assert evidence["requesting_ip_observed"] is True
    assert evidence["requesting_ip_retained"] is False


def test_ontario_and_us_fail_even_if_endpoint_blocked_flag_were_false():
    ontario = collect({
        "blocked": False,
        "country": "CA",
        "region": "ON",
        "ip": "203.0.113.8",
    })
    united_states = collect({
        "blocked": False,
        "country": "US",
        "region": "NY",
        "ip": "203.0.113.9",
    })

    ontario_gate = geoblock_evidence_gate(ontario, now=NOW)
    us_gate = geoblock_evidence_gate(united_states, now=NOW)

    assert not ontario_gate["ok"]
    assert "not_known_api_restricted" in ontario_gate["missing"]
    assert not us_gate["ok"]
    assert "not_polymarket_us" in us_gate["missing"]


def test_blocked_response_stale_evidence_tampering_and_proxy_routes_fail_closed():
    blocked = collect({
        "blocked": True,
        "country": "CA",
        "region": "ON",
        "ip": "203.0.113.8",
    })
    assert not geoblock_evidence_gate(blocked, now=NOW)["ok"]

    stale = collect({
        "blocked": False,
        "country": "CH",
        "region": "ZH",
        "ip": "203.0.113.8",
    })
    stale["checked_at_utc"] = "2026-08-13T18:00:00+00:00"
    stale_gate = geoblock_evidence_gate(stale, now=NOW)
    assert "checked_recently" in stale_gate["missing"]
    assert "evidence_hash_matches" in stale_gate["missing"]

    with pytest.raises(RuntimeError, match="refuses configured proxy routes"):
        collect_official_geoblock_evidence(
            opener=lambda _request, timeout: None,
            proxy_detector=lambda: {"https": "http://proxy.invalid"},
            now=NOW,
        )
