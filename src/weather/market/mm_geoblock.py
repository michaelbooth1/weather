"""Fail-closed physical geolocation proof for International Polymarket trading.

Polymarket requires builders to check ``https://polymarket.com/api/geoblock``
before placing orders.  This module retains only the non-sensitive eligibility
fields; the requesting IP is deliberately never written to an artifact.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import timedelta
from urllib.request import Request, getproxies, urlopen

from weather.market.mm_policy import parse_time, utc_now


GEOBLOCK_SCHEMA_VERSION = "polymarket_geoblock_v0.1"
GEOBLOCK_ENDPOINT = "https://polymarket.com/api/geoblock"
GEOBLOCK_DOCUMENTATION_URL = "https://docs.polymarket.com/api-reference/geoblock"
MAX_GEOBLOCK_AGE_SECONDS = 300.0
COUNTRY_CODE_RE = re.compile(r"^[A-Z]{2}$")
REGION_CODE_RE = re.compile(r"^[A-Z0-9-]{0,16}$")

# Belt-and-suspenders protection for restrictions documented when this gate was
# introduced.  The live endpoint remains authoritative for additions; retaining
# known restrictions makes a false-negative endpoint response fail closed.
KNOWN_API_RESTRICTED_COUNTRIES = frozenset({
    "AU", "BE", "BI", "BR", "BY", "CD", "CF", "CU", "DE", "ET", "FR",
    "GB", "IQ", "IR", "IT", "KP", "LB", "LY", "MM", "NI", "PL", "RU",
    "SG", "SK", "SO", "SS", "SD", "SY", "TH", "TW", "UM", "US", "VE",
    "YE", "ZW",
})
KNOWN_API_RESTRICTED_REGIONS = frozenset({
    "CA-AB", "CA-BC", "CA-ON", "CA-QC", "UA-09", "UA-14", "UA-43",
})


def _canonical_sha256(payload):
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _eligibility_fields(payload):
    return {
        "blocked": payload.get("blocked"),
        "country": payload.get("country"),
        "region": payload.get("region"),
    }


def geoblock_evidence_sha256(evidence):
    return _canonical_sha256({
        key: value
        for key, value in dict(evidence or {}).items()
        if key != "evidence_sha256"
    })


def _configured_proxy_names(proxy_detector):
    try:
        proxies = dict(proxy_detector() or {})
    except Exception as exc:
        raise RuntimeError("proxy configuration could not be inspected") from exc
    return sorted(
        str(name).lower()
        for name, value in proxies.items()
        if str(name).lower() in {"http", "https", "all"} and str(value or "").strip()
    )


def collect_official_geoblock_evidence(
    *,
    opener=urlopen,
    proxy_detector=getproxies,
    now=None,
    timeout_seconds=10.0,
):
    """Fetch current geoblock state without retaining the requesting IP.

    Configured HTTP proxies are rejected.  This does not attempt to infer every
    possible network tunnel; the surrounding live manifest separately requires
    an explicit no-circumvention/physical-location confirmation.
    """

    configured_proxies = _configured_proxy_names(proxy_detector)
    if configured_proxies:
        raise RuntimeError(
            "geoblock proof refuses configured proxy routes: "
            + ", ".join(configured_proxies)
        )
    request = Request(
        GEOBLOCK_ENDPOINT,
        headers={
            "Accept": "application/json",
            "Cache-Control": "no-cache",
            "User-Agent": "weather-mm-geoblock/0.1",
        },
        method="GET",
    )
    response = opener(request, timeout=float(timeout_seconds))
    try:
        status = getattr(response, "status", None)
        if status is None and hasattr(response, "getcode"):
            status = response.getcode()
        raw = response.read(16_385)
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()
    if status != 200:
        raise RuntimeError(f"official geoblock endpoint returned HTTP {status}")
    if len(raw) > 16_384:
        raise RuntimeError("official geoblock response exceeded the safety limit")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("official geoblock response was not valid JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("official geoblock response must be an object")
    if not isinstance(payload.get("blocked"), bool):
        raise RuntimeError("official geoblock response omitted boolean blocked state")
    country = str(payload.get("country") or "").strip().upper()
    region = str(payload.get("region") or "").strip().upper()
    if not COUNTRY_CODE_RE.fullmatch(country) or not REGION_CODE_RE.fullmatch(region):
        raise RuntimeError("official geoblock response had invalid country or region codes")
    requesting_ip_present = bool(str(payload.get("ip") or "").strip())
    if not requesting_ip_present:
        raise RuntimeError("official geoblock response omitted the requesting IP observation")
    evidence = {
        "schema_version": GEOBLOCK_SCHEMA_VERSION,
        "endpoint": GEOBLOCK_ENDPOINT,
        "checked_at_utc": utc_now(now).isoformat(),
        "http_status": 200,
        "blocked": payload["blocked"],
        "country": country,
        "region": region,
        "official_response_fields_sha256": _canonical_sha256({
            "blocked": payload["blocked"],
            "country": country,
            "region": region,
        }),
        "requesting_ip_observed": True,
        "requesting_ip_retained": False,
        "proxy_configuration_absent": True,
    }
    evidence["evidence_sha256"] = geoblock_evidence_sha256(evidence)
    return evidence


def geoblock_evidence_gate(evidence, *, now=None, max_age_seconds=MAX_GEOBLOCK_AGE_SECONDS):
    """Validate one recent, redacted response from the official endpoint."""

    payload = dict(evidence or {})
    observed_at = parse_time(payload.get("checked_at_utc"))
    current = utc_now(now)
    country = str(payload.get("country") or "").strip().upper()
    region = str(payload.get("region") or "").strip().upper()
    subdivision = f"{country}-{region}" if country and region else ""
    known_restricted = (
        country in KNOWN_API_RESTRICTED_COUNTRIES
        or subdivision in KNOWN_API_RESTRICTED_REGIONS
    )
    recent = bool(
        observed_at is not None
        and observed_at <= current + timedelta(minutes=5)
        and current - observed_at <= timedelta(seconds=float(max_age_seconds))
    )
    checks = {
        "schema_supported": payload.get("schema_version") == GEOBLOCK_SCHEMA_VERSION,
        "endpoint_exact": payload.get("endpoint") == GEOBLOCK_ENDPOINT,
        "checked_recently": recent,
        "http_status_ok": payload.get("http_status") == 200,
        "blocked_is_boolean": isinstance(payload.get("blocked"), bool),
        "official_endpoint_allows_orders": payload.get("blocked") is False,
        "country_code_valid": COUNTRY_CODE_RE.fullmatch(country) is not None,
        "region_code_valid": REGION_CODE_RE.fullmatch(region) is not None,
        "not_known_api_restricted": not known_restricted,
        "not_polymarket_us": country != "US",
        "response_fields_hash_matches": (
            payload.get("official_response_fields_sha256")
            == _canonical_sha256(_eligibility_fields({
                "blocked": payload.get("blocked"),
                "country": country,
                "region": region,
            }))
        ),
        "requesting_ip_observed": payload.get("requesting_ip_observed") is True,
        "requesting_ip_not_retained": (
            payload.get("requesting_ip_retained") is False
            and "ip" not in payload
        ),
        "proxy_configuration_absent": payload.get("proxy_configuration_absent") is True,
        "evidence_hash_matches": (
            payload.get("evidence_sha256") == geoblock_evidence_sha256(payload)
        ),
    }
    missing = [name for name, valid in checks.items() if not valid]
    return {
        "ok": not missing,
        "checks": checks,
        "missing": missing,
        "country": country or None,
        "region": region or None,
        "blocked": payload.get("blocked"),
        "checked_at_utc": payload.get("checked_at_utc"),
        "evidence_sha256": payload.get("evidence_sha256"),
        "reason": "ok" if not missing else "geoblock proof missing: " + ", ".join(missing),
    }
