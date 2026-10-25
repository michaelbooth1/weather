"""Research-only release bound to R0's base models (retrain memo R0.1 step 5, piece M14).

Guards: retrain memo R0.2 M14 - a research-only candidate may bind trained feature_hgb and
feature_lr_coefficients bytes per market from an R0 candidate manifest; the other five base components
(served late-day coefficients included) stay the served bytes the manifest hashed; production candidates
and every other component refuse overrides. R0 M7/M8 (2026-10-23): the r0-mode allowlist and the
served_model_differences record ride inside the frozen artifacts (the leakage audit passes them) and
the release provenance carries each market's differences. Fixture trees only.
"""

from __future__ import annotations

import json
import pickle

import pytest

from tests.operations.test_release_candidate_contract import _fixture
from weather.calibration.r0_candidate_manifest import (
    MANIFEST_FILENAME,
    build_r0_candidate_manifest,
    write_r0_candidate_manifest,
)
from weather.calibration.r0_scope import (
    R0_MARKET_IDS,
    R0_OUT_OF_SCOPE_MARKETS,
    served_model_differences,
)
from weather.operations.all_shadow_release_bootstrap import (
    AllShadowBootstrapError,
    r0_candidate_binding,
    verify_r0_frozen_components,
)
from weather.operations.release_candidate_contract import (
    CandidateContractError,
    freeze_candidate_semantic_contract,
)
from weather.release_artifacts import sha256_file
from weather.release_contract import PRODUCTION_CANDIDATE_MODE, RESEARCH_ONLY_CANDIDATE_MODE

CANDIDATE = "retrain-r0-2026-11-24"


def _r0_tree(root, market="nyc", *, marker="r0"):
    folder = root / market
    folder.mkdir(parents=True)
    inputs = {
        "centre_date": "2026-11-24",
        "centre_date_pinned": True,
        "training_years": [2021, 2022, 2023],
        "forecast_source": "pit_forecast_corpus",
        "pit_forecast_corpus": {"corpora": [], "union_sha256": "e" * 64},
    }
    allowlist = {
        "mode": "r0",
        "sha256": "f" * 64,
        "feature_names": ["forecast_high", "high_so_far"],
        "served_feature_names": ["forecast_high", "high_so_far", "pressure", "forecast_source_count"],
        "column_differences_from_served": [
            {"column": "pressure", "reason": "training_policy_exclusion", "decision": "fixture"},
            {"column": "forecast_source_count", "reason": "single_provider_pit_corpus_cannot_express",
             "decision": "fixture"},
        ],
    }
    info = {"base_models_only": True, "training_inputs": inputs, "training_column_allowlist": allowlist,
            "served_model_differences": served_model_differences(allowlist, inputs, base_models_only=True)}
    hgb = dict(info, **{"12": {"feature_names": ["forecast_high", "high_so_far"], "fixture_component": marker}})
    coefs = dict(info, **{"12": {"feature_names": ["forecast_high", "high_so_far"], "fixture_component": marker}})
    (folder / f"feature_model_hgb_{market}.pkl").write_bytes(pickle.dumps(hgb))
    (folder / f"feature_model_coefs_{market}.json").write_text(json.dumps(coefs), encoding="utf-8")
    (folder / f"feature_model_report_{market}.md").write_text("# r0\n", encoding="utf-8")
    return {"feature_hgb": folder / f"feature_model_hgb_{market}.pkl",
            "feature_lr_coefficients": folder / f"feature_model_coefs_{market}.json"}


def _freeze(paths, *, overrides=None, mode=RESEARCH_ONLY_CANDIDATE_MODE):
    return freeze_candidate_semantic_contract(
        candidate_dir=paths["candidate"],
        model_bundle_path=paths["bundle"],
        family_secondary_path=paths["family"],
        artifact_registry_path=paths["registry"],
        repo_root=paths["repo"],
        candidate_id="r1",
        parent_release=None,
        promotion={"verdict": "promote_ready", "promote_markets": ["nyc"], "shadow_markets": [],
                   "blocked_markets": []},
        family_unit="F",
        candidate_mode=mode,
        base_model_component_overrides=overrides,
    )


def _json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_overrides_bind_trained_bytes_and_keep_the_served_five(tmp_path):
    paths = _fixture(tmp_path)
    r0 = _r0_tree(tmp_path / "r0")
    frozen = _freeze(paths, overrides={"nyc": r0})
    assert frozen["status"] == "PASS"
    base = paths["candidate"] / "base_model" / "nyc"
    assert sha256_file(base / "feature_model_hgb_nyc.pkl") == sha256_file(r0["feature_hgb"])
    assert _json(base / "feature_model_coefs_nyc.json") == _json(r0["feature_lr_coefficients"])
    served = paths["base_artifacts"]
    for component in ("late_day_lr_coefficients", "calibrated_weights", "probability_calibration",
                      "forecast_error_model", "settlement_lag_model"):
        assert _json(base / served[component].name) == _json(served[component])


def test_without_overrides_the_served_models_are_frozen(tmp_path):
    paths = _fixture(tmp_path)
    _freeze(paths)
    base = paths["candidate"] / "base_model" / "nyc"
    assert sha256_file(base / "feature_model_hgb_nyc.pkl") == sha256_file(paths["base_artifacts"]["feature_hgb"])


@pytest.mark.parametrize(
    "build, message",
    [
        (lambda r0, served: {"nyc": {"late_day_lr_coefficients": served["late_day_lr_coefficients"]}},
         "cannot be overridden"),
        (lambda r0, served: {"nyc": {"feature_hgb": r0["feature_lr_coefficients"]}}, "must be named"),
        (lambda r0, served: {"atlanta": {"feature_hgb": r0["feature_hgb"]}}, "without a candidate route"),
    ],
)
def test_invalid_overrides_fail_closed(tmp_path, build, message):
    paths = _fixture(tmp_path)
    r0 = _r0_tree(tmp_path / "r0")
    with pytest.raises(CandidateContractError, match=message):
        _freeze(paths, overrides=build(r0, paths["base_artifacts"]))


def test_production_candidates_refuse_overrides(tmp_path):
    paths = _fixture(tmp_path)
    r0 = _r0_tree(tmp_path / "r0")
    with pytest.raises(CandidateContractError, match="research-only"):
        _freeze(paths, overrides={"nyc": r0}, mode=PRODUCTION_CANDIDATE_MODE)


def _manifest(tmp_path, paths):
    root = tmp_path / "cand" / CANDIDATE
    _r0_tree(root)
    manifest = build_r0_candidate_manifest(
        root, candidate_id=CANDIDATE, centre="2026-11-24", markets=["nyc"], build_commit="a" * 40,
        excluded_markets={market: "fixture: not trained" for market in R0_MARKET_IDS if market != "nyc"},
        repo_root=paths["repo"],
    )
    return write_r0_candidate_manifest(manifest, root / MANIFEST_FILENAME)


def test_manifest_binding_freezes_and_reverifies_exact_components(tmp_path):
    paths = _fixture(tmp_path)
    manifest_path = _manifest(tmp_path, paths)
    binding = r0_candidate_binding(manifest_path, candidate_id=CANDIDATE, repo_root=paths["repo"])
    assert set(binding["overrides"]["nyc"]) == {"feature_hgb", "feature_lr_coefficients"}
    assert binding["provenance"]["manifest_sha256"] == binding["manifest"]["manifest_sha256"]
    assert binding["provenance"]["excluded_markets"]["toronto"] == R0_OUT_OF_SCOPE_MARKETS["toronto"]
    differences = binding["provenance"]["served_model_differences"]
    assert list(differences) == ["nyc"]
    assert [row["column"] for row in differences["nyc"]["columns_removed"]] == [
        "pressure", "forecast_source_count",
    ]
    _freeze(paths, overrides=binding["overrides"])
    verify = dict(manifest_dir=binding["manifest_dir"], repo_root=paths["repo"])
    verify_r0_frozen_components(paths["candidate"], binding["manifest"], **verify)

    late_day = paths["candidate"] / "base_model" / "nyc" / "late_day_model_coefs_nyc.json"
    late_day.write_text(json.dumps({"tampered": True}), encoding="utf-8")
    with pytest.raises(AllShadowBootstrapError, match="late_day_model_coefs_nyc.json differs"):
        verify_r0_frozen_components(paths["candidate"], binding["manifest"], **verify)


def test_binding_refuses_another_candidate_or_drifted_served_bytes(tmp_path):
    paths = _fixture(tmp_path)
    manifest_path = _manifest(tmp_path, paths)
    with pytest.raises(AllShadowBootstrapError, match="not 'retrain-r0-2026-12-10'"):
        r0_candidate_binding(manifest_path, candidate_id="retrain-r0-2026-12-10", repo_root=paths["repo"])
    paths["base_artifacts"]["late_day_lr_coefficients"].write_text("{}", encoding="utf-8")
    with pytest.raises(AllShadowBootstrapError, match="does not verify"):
        r0_candidate_binding(manifest_path, candidate_id=CANDIDATE, repo_root=paths["repo"])
    assert r0_candidate_binding(None, candidate_id=CANDIDATE, repo_root=paths["repo"]) is None
