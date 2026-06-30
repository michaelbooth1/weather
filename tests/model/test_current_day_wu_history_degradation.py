import csv
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import requests

from weather.collection.collection_health import source_family_degradation
from weather.model.model_sources import SourceFetchMixin
from weather.model.source_adapters import fetch_source


class FakeWuHistoryModel(SourceFetchMixin):
    def __init__(self, history_id, tz_name="America/Toronto", status_code=400):
        tz = ZoneInfo(tz_name)
        target_date = datetime.now(tz).date()
        self.spec = SimpleNamespace(
            wu_history_id=history_id,
            wu_units="m",
            tz=tz,
        )
        self.target_date = target_date
        self.target_date_str = target_date.strftime("%Y%m%d")
        self.timeout = 1
        self.saved_cache = None
        self.status_code = status_code

    def get_json(self, _url, _params):
        response = requests.Response()
        response.status_code = self.status_code
        response.url = "https://example.invalid/legacy-paid-provider/history"
        error = requests.HTTPError(f"{self.status_code} Client Error")
        error.response = response
        raise error

    def load_last_good_sources(self):
        return {}

    def save_last_good_sources(self, cache):
        self.saved_cache = cache


def write_rows(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def test_wu_history_paid_provider_path_is_expected_unavailable_for_all_ids():
    for history_id in ("CYYZ:9:CA", "KATL:9:US"):
        model = FakeWuHistoryModel(history_id)

        name, payload = fetch_source(
            "wu_history",
            model.fetch_wu_history,
            fetched_at="2026-06-21T15:36:00-04:00",
        )
        blended = model.blend_with_last_good({name: payload})

        row = blended["wu_history"]
        assert payload["status"] == "paid_provider_disabled"
        assert payload.get("http_status") is None
        assert payload["fallback_source"] == "metar,eccc_swob,current_high_ledger"
        assert row["status"] == "paid_provider_disabled"
        assert row["degradation_state"] == "paid_provider_disabled"
        assert row["cache_status"] == "expected_unavailable"
        assert not row["ok"]
        assert row["fallback_source"] == "metar,eccc_swob,current_high_ledger"


def test_expected_current_day_wu_history_source_status_is_not_failed(tmp_path):
    write_rows(
        tmp_path / "source_status_long.csv",
        [
            {
                "snapshot_id": "s1",
                "captured_at_utc": "2026-06-21T19:36:00+00:00",
                "captured_at_local": "2026-06-21T15:36:00-04:00",
                "source": "wu_history",
                "ok": "False",
                "stale": "False",
                "status": "expected_current_day_unavailable",
                "source_family": "wu_history",
                "http_status": "400",
                "degradation_state": "expected_current_day_unavailable",
                "cache_status": "expected_unavailable",
                "fallback_source": "wu_current,metar,eccc_swob,current_high_ledger",
                "fetched_at": "2026-06-21T15:36:00-04:00",
                "error": "WU history current day unavailable",
            }
        ],
    )

    payload = source_family_degradation(tmp_path)

    family = payload["families"]["wu_history"]
    assert payload["failed_source_count"] == 0
    assert payload["expected_unavailable_source_count"] == 1
    assert payload["blocking_family_count"] == 0
    assert payload["trading_evidence_allowed"]
    assert family["status"] == "expected_current_day_unavailable"
    assert family["failed_source_count"] == 0
    assert family["expected_unavailable_source_count"] == 1
    assert family["expected_unavailable_sources"] == ["wu_history"]
    assert family["source_details"][0]["bucket"] == "expected_unavailable"
    assert family["source_details"][0]["fallback_source"] == "wu_current,metar,eccc_swob,current_high_ledger"


def test_wu_history_paid_provider_disablement_is_not_cached_as_success():
    model = FakeWuHistoryModel("KATL:9:US", status_code=403)

    name, payload = fetch_source(
        "wu_history",
        model.fetch_wu_history,
        fetched_at="2026-06-21T15:36:00-04:00",
    )
    blended = model.blend_with_last_good({name: payload})

    row = blended["wu_history"]
    assert payload["status"] == "paid_provider_disabled"
    assert payload.get("http_status") is None
    assert row["status"] == "paid_provider_disabled"
    assert row["degradation_state"] == "paid_provider_disabled"
    assert row["cache_status"] == "expected_unavailable"
    assert row["source_family"] == "wu_history"
    assert not row["ok"]
