"""Paired R0-vs-served replay bound to an R0 research release (retrain memo R0.2, piece M15).

Guards: retrain memo R0.2 M15 - the R0 arm differs from served only in feature_hgb and
feature_lr_coefficients from a verified research-only R0 release; the arm is chosen by target date from
a non-overlapping schedule; folders after --max-target-date are never opened; output is write-once.
Fixtures and fakes only; no captured data, settlement or LFS artifact is read.
"""

from __future__ import annotations

import hashlib
import json
import pickle
from datetime import date
from pathlib import Path

import pytest

import weather.backtesting.r0_paired_replay as paired
from weather.backtesting.r0_paired_replay import (
    R0BoundModel,
    R0PairedReplayError,
    SERVED_COMPONENT_FILES,
    arm_for_date,
    load_r0_release,
    load_schedule,
    run_paired_replay,
)
from weather.market.market_config import event_slug_for_date

SERVED = {component: {"served": component} for component in SERVED_COMPONENT_FILES}
R0_HGB = {"12": {"feature_names": ["high_so_far"], "r0": True}}
R0_COEFS = {"12": {"feature_names": ["high_so_far"], "r0": "coefs"}}


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _release_dir(tmp_path, market="nyc"):
    root = tmp_path / "release"
    inventory = []
    payloads = {"feature_hgb": R0_HGB, "feature_lr_coefficients": R0_COEFS, **SERVED}
    for component, payload in payloads.items():
        relative = f"base_model/{market}/{component}" + (".pkl" if component == "feature_hgb" else ".json")
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if component == "feature_hgb":
            path.write_bytes(pickle.dumps(payload))
        else:
            path.write_text(json.dumps(payload), encoding="utf-8")
        inventory.append({"role": f"base_model.{market}.{component}", "path": relative, "sha256": _sha(path)})
    manifest = {
        "artifacts": {"inventory": inventory},
        "lineage": {"source_provenance": {"r0_candidate": {
            "markets": [market], "manifest_sha256": "c" * 64, "window": {"centre": "2026-11-24"}}}},
    }
    return root, manifest


def _verifier(manifest, *, mode="research_only", status="PASS"):
    def verify(release_dir, **kwargs):
        assert kwargs["expected_manifest_sha256"] == "m" * 64
        return {"status": status, "release_id": "retrain-r0-2026-11-24", "manifest_sha256": "m" * 64,
                "semantic_contract": {"candidate_mode": mode}, "manifest": manifest}
    return verify


def test_release_loader_returns_verified_market_components(tmp_path):
    root, manifest = _release_dir(tmp_path)
    release = load_r0_release(root, expected_manifest_sha256="m" * 64, verifier=_verifier(manifest))
    assert release["release_id"] == "retrain-r0-2026-11-24"
    assert release["candidate_manifest_sha256"] == "c" * 64
    assert release["markets"]["nyc"]["feature_hgb"] == R0_HGB
    assert release["markets"]["nyc"]["late_day_lr_coefficients"] == SERVED["late_day_lr_coefficients"]


def test_release_loader_fails_closed(tmp_path):
    root, manifest = _release_dir(tmp_path)
    with pytest.raises(R0PairedReplayError, match="research_only"):
        load_r0_release(root, expected_manifest_sha256="m" * 64, verifier=_verifier(manifest, mode="production"))
    no_r0 = dict(manifest, lineage={})
    with pytest.raises(R0PairedReplayError, match="R0 candidate manifest"):
        load_r0_release(root, expected_manifest_sha256="m" * 64, verifier=_verifier(no_r0))
    (root / "base_model" / "nyc" / "feature_lr_coefficients.json").write_text("{}", encoding="utf-8")
    with pytest.raises(R0PairedReplayError, match="do not verify"):
        load_r0_release(root, expected_manifest_sha256="m" * 64, verifier=_verifier(manifest))


def _served_files(tmp_path, monkeypatch, payloads=SERVED):
    served = tmp_path / "served"
    served.mkdir()
    for component, template in SERVED_COMPONENT_FILES.items():
        (served / template.format(suffix="_nyc")).write_text(json.dumps(payloads[component]), encoding="utf-8")
    monkeypatch.setattr(paired, "resolve_artifact_path", lambda name: served / name)


def test_bound_model_swaps_exactly_the_two_r0_components(tmp_path, monkeypatch):
    _served_files(tmp_path, monkeypatch)
    release = {"markets": {"nyc": {"feature_hgb": R0_HGB, "feature_lr_coefficients": R0_COEFS, **SERVED}}}
    model = R0BoundModel(r0_release=release, market_id="nyc", target_date="2026-09-20")
    assert model.load_feature_model_hgb() == R0_HGB
    assert model.load_feature_model_coefs() == R0_COEFS
    model.set_target_date("2026-09-21")
    assert model.load_feature_model_hgb() == R0_HGB
    with pytest.raises(R0PairedReplayError, match="no market"):
        R0BoundModel(r0_release=release, market_id="chicago")


def test_bound_model_refuses_a_release_whose_served_five_differ(tmp_path, monkeypatch):
    drifted = dict(SERVED, calibrated_weights={"served": "other"})
    _served_files(tmp_path, monkeypatch, payloads=drifted)
    release = {"markets": {"nyc": {"feature_hgb": R0_HGB, "feature_lr_coefficients": R0_COEFS, **SERVED}}}
    with pytest.raises(R0PairedReplayError, match="calibrated_weights for nyc differs"):
        R0BoundModel(r0_release=release, market_id="nyc")


def _schedule(tmp_path, arms):
    path = tmp_path / "schedule.json"
    path.write_text(json.dumps({"arms": arms}), encoding="utf-8")
    return load_schedule(path)


ARMS = [
    {"name": "R0b", "release_dir": "rb", "manifest_sha256": "b" * 64,
     "first_target_date": "2026-09-16", "last_target_date": "2026-09-29"},
    {"name": "R0a", "release_dir": "ra", "manifest_sha256": "a" * 64,
     "first_target_date": "2026-09-01", "last_target_date": "2026-09-15"},
]


def test_schedule_picks_the_arm_by_date_and_refuses_overlap(tmp_path):
    schedule = _schedule(tmp_path, ARMS)
    assert [arm["name"] for arm in schedule["arms"]] == ["R0a", "R0b"]
    assert arm_for_date(schedule, date(2026, 9, 15))["name"] == "R0a"
    assert arm_for_date(schedule, date(2026, 9, 16))["name"] == "R0b"
    assert arm_for_date(schedule, date(2026, 8, 31)) is None
    overlap = [dict(ARMS[0], first_target_date="2026-09-15"), ARMS[1]]
    with pytest.raises(R0PairedReplayError, match="overlap"):
        _schedule(tmp_path, overlap)
    with pytest.raises(R0PairedReplayError, match="reversed"):
        _schedule(tmp_path, [dict(ARMS[0], last_target_date="2026-09-01")])


class _FakeModel:
    def __init__(self, value, **kwargs):
        self.value = value

    def set_target_date(self, target_date):
        self.target_date = target_date

    def estimate_distribution(self, sources, now=None):
        return {70: self.value, 71: 1.0 - self.value}


def _folder(root, day, market="nyc", record_count=2):
    folder = root / event_slug_for_date(day, market)
    folder.mkdir(parents=True)
    lines = [json.dumps({"snapshot_id": f"s{index}", "target_date": day.isoformat(), "sources": {"x": 1},
                         "built_at": f"{day.isoformat()}T12:00:00-04:00"}) for index in range(record_count)]
    lines.append(json.dumps({"snapshot_id": "rec", "source": "reconstructed", "sources": {"x": 1}}))
    (folder / "replay_inputs.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return folder


def test_paired_run_pairs_per_arm_and_never_opens_later_folders(tmp_path):
    schedule = _schedule(tmp_path, ARMS)
    snapshots = tmp_path / "snapshots"
    early = _folder(snapshots, date(2026, 9, 10))
    late = _folder(snapshots, date(2026, 9, 20))
    guarded = _folder(snapshots, date(2026, 9, 27))
    (guarded / "replay_inputs.jsonl").write_text("not json, must never be read\n", encoding="utf-8")
    outside = _folder(snapshots, date(2026, 8, 20))
    loaded = []

    def loader(release_dir, **kwargs):
        loaded.append(release_dir)
        return {"release_id": f"rel-{release_dir}", "candidate_manifest_sha256": "c" * 64,
                "markets": {"nyc": {}}}

    out = tmp_path / "out" / "pairs.jsonl"
    header = run_paired_replay(
        [early, late, guarded, outside], schedule, max_target_date=date(2026, 9, 25), out_path=out,
        release_loader=loader,
        served_model_factory=lambda **kwargs: _FakeModel(0.5),
        r0_model_factory=lambda **kwargs: _FakeModel(0.75),
    )
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert rows[0] == header and header["pairs"] == 4
    pairs = rows[1:]
    assert [(row["arm"], row["target_date"]) for row in pairs] == [("R0a", "2026-09-10")] * 2 + [("R0b", "2026-09-20")] * 2
    assert pairs[0]["l1_r0_vs_served"] == pytest.approx(0.5)
    assert pairs[0]["served_distribution"] == {"70": 0.5, "71": 0.5}
    assert all(row["reconstructed"] is False for row in pairs)
    assert loaded == ["ra", "rb"]
    reasons = {row["folder"]: row["reason"] for row in header["skipped"]}
    assert reasons[guarded.name].startswith("after --max-target-date")
    assert reasons[outside.name] == "no R0 arm covers this date"
    assert header["schedule_sha256"] == schedule["schedule_sha256"]
    with pytest.raises(R0PairedReplayError, match="never overwritten"):
        run_paired_replay([early], schedule, max_target_date=date(2026, 9, 29), out_path=out,
                          release_loader=loader)


def test_markets_outside_the_release_are_skipped(tmp_path):
    schedule = _schedule(tmp_path, ARMS)
    folder = _folder(tmp_path / "snapshots", date(2026, 9, 10), market="toronto")
    header = run_paired_replay(
        [folder], schedule, max_target_date=date(2026, 9, 29), out_path=tmp_path / "o.jsonl",
        release_loader=lambda *args, **kwargs: {"release_id": "r", "candidate_manifest_sha256": None,
                                                "markets": {"nyc": {}}},
        served_model_factory=lambda **kwargs: pytest.fail("no model for a skipped market"),
    )
    assert header["pairs"] == 0
    assert header["skipped"][0]["reason"] == "market not in R0 arm R0a"
