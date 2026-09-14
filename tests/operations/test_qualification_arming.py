"""Planned adoption must fit the actual retained import and certificate graph."""

from datetime import timedelta
from pathlib import Path

import pytest

from tests.operations.test_qualification_evidence import NOW, bundle
from tests.operations.test_qualification_importer import run_import
from weather.operations.qualification import arming, records
from weather.operations.qualification.contracts import Graph


def checked(bundle, tmp_path, monkeypatch, *, merge="2026-09-15T01:05:00-04:00"):
    imported = run_import(bundle, tmp_path, monkeypatch)
    return {"manifest": {"schedule": {"merge_at_local": merge}, "qualification": {
        "policy": bundle.refs["policy"], "review": bundle.refs["review"],
        "certificate": bundle.refs["certificate"], "import": imported["receipt"]}},
        "policy": bundle.values["policy"], "graph": Graph(Path(imported["root"]))}


def test_complete_graph_fits_latest_quiet_window_not_only_trigger(bundle, tmp_path, monkeypatch):
    value = checked(bundle, tmp_path, monkeypatch)
    assert arming.planned_expiry(value, now=NOW) == "2026-09-15T08:00:00Z"


@pytest.mark.parametrize("case", ["late-day", "naive", "elapsed", "arming-stale"])
def test_expired_or_ambiguous_planned_adoption_cannot_arm(bundle, tmp_path, monkeypatch, case):
    merge = {"late-day": "2026-09-16T01:05:00-04:00", "naive": "2026-09-15T01:05:00",
             "elapsed": "2026-09-14T01:05:00-04:00", "arming-stale": "2026-09-15T01:05:00-04:00"}[case]
    value = checked(bundle, tmp_path, monkeypatch, merge=merge)
    now = NOW + timedelta(hours=1, seconds=1) if case == "arming-stale" else NOW
    with pytest.raises(records.QualificationError):
        arming.planned_expiry(value, now=now)
