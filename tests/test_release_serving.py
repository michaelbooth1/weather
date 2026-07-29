import json
import pickle
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from tests.operations.test_release_candidate_contract import (
    _fixture,
    _freeze,
    _production_evidence,
)
from weather.collection.live_variant_predictions import build_live_variant_prediction_rows
from weather.collection.snapshot_store import _assert_snapshot_model_serving_binding
from weather.operations.release_manifest import create_release
from weather.model.toronto_model import TorontoHighTempModel
from weather.release_artifacts import (
    ACTIVE_POINTER_SCHEMA_VERSION,
    ReleaseArtifactVerificationError,
    pointer_content_sha256,
)
from weather.release_contract import (
    PRODUCTION_CANDIDATE_MODE,
    RESEARCH_ONLY_CANDIDATE_MODE,
    SERVING_IDENTITY_BOOTSTRAP_RELEASE_KIND,
)
from weather.operations.release_promotion import resolve_active_release
from weather.release_serving import (
    STATUS_BLOCKED,
    STATUS_BOUND,
    STATUS_INACTIVE_SHADOW_BOUND,
    STATUS_RESEARCH_UNBOUND,
    STATUS_RESTART_REQUIRED,
    ReleaseServingBindingError,
    VerifiedServingBundle,
    clear_process_serving_bundle_cache,
    get_process_active_serving_bundle,
    load_verified_active_serving_bundle,
    load_verified_inactive_serving_bundle,
    materialize_verified_base_model_market,
    serving_bundle_lineage,
)


class IdentityImputer:
    strategy = "median"
    keep_empty_features = True
    n_features_in_ = 2
    statistics_ = [80.0, 0.0]

    def transform(self, frame):
        return frame


class ConstantClassifier:
    classes_ = [0, 1]

    def predict_proba(self, rows):
        return [[0.23, 0.77] for _ in range(len(rows))]


class FakeClient:
    target_date = date(2026, 6, 18)

    def bin_probability(self, distribution, bin_data, calibration_context=None):
        del distribution, bin_data, calibration_context
        return 0.5


def _runtime_versions():
    return {
        "python": "3.13.0",
        "implementation": "CPython",
        "platform": "test",
        "direct_dependencies": {
            "scikit-learn": {"version": "1.7.0", "declared": "scikit-learn"}
        },
    }


def _runtime_identity():
    return {"source_fingerprint": "source", "git_commit": "a" * 40}


def _functionalize(paths: dict) -> None:
    with paths["bundle"].open("rb") as handle:
        bundle = pickle.load(handle)
    original = bundle["models"].pop("8")
    bundle["models"]["12"] = {
        **original,
        "model": ConstantClassifier(),
        "imputer": IdentityImputer(),
        "classes": [0, 1],
        "temperature": 1.0,
    }
    bundle["postprocess"] = {
        "partition_normalization_enabled": False,
        "current_blend_enabled": False,
    }
    with paths["bundle"].open("wb") as handle:
        pickle.dump(bundle, handle)


def _write_pointer(
    path: Path,
    *,
    release_id: str,
    manifest_sha256: str,
    sequence: int = 1,
    release_kind: str | None = None,
    release_kind_provenance: dict | None = None,
) -> None:
    payload = {
        "schema_version": ACTIVE_POINTER_SCHEMA_VERSION,
        "sequence": sequence,
        "action": "PROMOTE",
        "changed_at_utc": datetime(2026, 7, 12, 0, sequence, tzinfo=timezone.utc).isoformat(),
        "active_release_id": release_id,
        "active_manifest_sha256": manifest_sha256,
        "previous_release_id": None,
        "previous_manifest_sha256": None,
    }
    if release_kind is not None:
        payload["release_kind"] = release_kind
    if release_kind_provenance is not None:
        payload["release_kind_provenance"] = release_kind_provenance
        payload["promotion_decision_sha256"] = release_kind_provenance[
            "promotion_decision_sha256"
        ]
        payload["market_day_boundary_sha256"] = release_kind_provenance[
            "market_day_boundary_sha256"
        ]
        payload["reviewed_by"] = release_kind_provenance["reviewed_by"]
    payload["pointer_sha256"] = pointer_content_sha256(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _active_fixture(
    tmp_path: Path,
    *,
    functional: bool = False,
    mutate_declarations=None,
    manifest_route=None,
    candidate_mode: str = PRODUCTION_CANDIDATE_MODE,
    release_kind: str | None = None,
    release_kind_provenance: dict | None = None,
):
    paths = _fixture(tmp_path)
    if functional:
        _functionalize(paths)
    frozen = _freeze(
        paths,
        candidate_mode=candidate_mode,
        point_in_time_artifacts=(
            _production_evidence(paths)
            if candidate_mode == PRODUCTION_CANDIDATE_MODE
            else None
        ),
    )
    declarations = list(frozen["declarations"])
    if mutate_declarations:
        declarations = mutate_declarations(declarations)
    releases = tmp_path / "releases"
    result = create_release(
        release_id="r1",
        candidate_dir=paths["candidate"],
        declarations=declarations,
        route=manifest_route or frozen["route"],
        expected_live_runtimes=["snapshot_loop"],
        releases_root=releases,
        repo_root=paths["repo"],
        code_identity={
            "git_commit": "a" * 40,
            "git_branch": "main",
            "git_dirty": False,
            "dirty_fingerprint": None,
        },
        runtime_versions=_runtime_versions(),
        runtime_identity=_runtime_identity(),
    )
    pointer = releases / "current_release.json"
    _write_pointer(
        pointer,
        release_id="r1",
        manifest_sha256=result["manifest_sha256"],
        release_kind=release_kind,
        release_kind_provenance=(
            {
                **release_kind_provenance,
                "origin_release_id": "r1",
                "origin_manifest_sha256": result["manifest_sha256"],
            }
            if release_kind_provenance is not None
            else None
        ),
    )
    return paths, frozen, result, releases, pointer


def _bootstrap_provenance() -> dict:
    return {
        "origin_action": "PROMOTE",
        "origin_sequence": 1,
        "promotion_decision_sha256": "d" * 64,
        "market_day_boundary_sha256": "e" * 64,
        "reviewed_by": "test-reviewer",
    }


def _load(pointer: Path, releases: Path, repo: Path):
    return load_verified_active_serving_bundle(
        pointer_path=pointer,
        releases_root=releases,
        repo_root=repo,
        check_runtime=False,
    )


def test_verified_loader_binds_exact_manifest_roles_before_deserialization(tmp_path: Path):
    paths, _frozen, result, releases, pointer = _active_fixture(tmp_path)

    bundle = _load(pointer, releases, paths["repo"])

    assert bundle.status == STATUS_BOUND
    assert bundle.release_id == "r1"
    assert bundle.manifest_sha256 == result["manifest_sha256"]
    assert bundle.release_kind == "production"
    assert bundle.candidate_mode == PRODUCTION_CANDIDATE_MODE
    assert bundle.production_capable is True
    assert bundle.route["markets"]["nyc"]["candidate_variant_id"] == "r1.pooled_band"
    assert bundle.model_variant_registry["variants"][0]["variant_id"] == "candidate"
    assert Path(bundle.artifact_paths["pooled_band_model"]).is_relative_to(releases / "r1")
    assert bundle.base_model_bound is True
    assert set(bundle.base_model_artifacts["nyc"]) == {
        "feature_hgb",
        "feature_lr_coefficients",
        "late_day_lr_coefficients",
        "calibrated_weights",
        "probability_calibration",
        "forecast_error_model",
        "settlement_lag_model",
    }
    assert bundle.base_model_artifacts["nyc"]["calibrated_weights"][
        "fixture_component"
    ] == "calibrated_weights"
    assert bundle.base_model_artifacts["nyc"]["feature_hgb"]["binding"] == (
        "verified_release_pickle_binding_v0.1"
    )
    assert materialize_verified_base_model_market(bundle, "nyc")["feature_hgb"]["12"][
        "fixture_component"
    ] == "feature_hgb"
    assert set(bundle.base_model_shared_artifacts) == {
        "afternoon_residual_centering",
        "family_secondary_artifacts",
    }


def test_inactive_shadow_loader_binds_release_without_pointer_authority(
    tmp_path: Path,
):
    paths, _frozen, result, releases, pointer = _active_fixture(tmp_path)
    release_dir = releases / "r1"

    with pytest.raises(
        ReleaseServingBindingError,
        match="currently active release",
    ):
        load_verified_inactive_serving_bundle(
            release_dir,
            expected_manifest_sha256=result["manifest_sha256"],
            active_pointer_path=pointer,
            repo_root=paths["repo"],
            check_runtime=False,
        )

    pointer.unlink()
    bundle = load_verified_inactive_serving_bundle(
        release_dir,
        expected_manifest_sha256=result["manifest_sha256"],
        active_pointer_path=pointer,
        repo_root=paths["repo"],
        check_runtime=False,
    )

    assert bundle.status == STATUS_INACTIVE_SHADOW_BOUND
    assert bundle.pointer_present is False
    assert bundle.pointer_sha256 == ""
    assert bundle.sequence is None
    assert bundle.release_id == "r1"
    assert bundle.manifest_sha256 == result["manifest_sha256"]
    assert bundle.production_capable is True
    assert bundle.base_model_bound is True
    assert (
        serving_bundle_lineage(bundle)["release_identity_status"]
        == "verified_inactive_shadow_bundle"
    )
    assert materialize_verified_base_model_market(bundle, "nyc")[
        "feature_hgb"
    ]["12"]["fixture_component"] == "feature_hgb"
    model = TorontoHighTempModel(
        target_date=date(2026, 6, 18),
        market_id="nyc",
        serving_bundle=bundle,
    )
    assert model.load_feature_model_hgb()["12"]["fixture_component"] == "feature_hgb"


def test_research_release_without_valid_bootstrap_provenance_is_rejected(
    tmp_path: Path,
):
    paths, _frozen, result, releases, pointer = _active_fixture(
        tmp_path,
        candidate_mode=RESEARCH_ONLY_CANDIDATE_MODE,
    )

    with pytest.raises(ReleaseServingBindingError, match="research-only"):
        _load(pointer, releases, paths["repo"])
    with pytest.raises(
        ReleaseArtifactVerificationError,
        match="research-only active release lacks",
    ):
        resolve_active_release(
            pointer_path=pointer,
            releases_root=releases,
            repo_root=paths["repo"],
            current_runtime_versions=_runtime_versions(),
            current_runtime_identity=_runtime_identity(),
        )

    _write_pointer(
        pointer,
        release_id="r1",
        manifest_sha256=result["manifest_sha256"],
        release_kind=SERVING_IDENTITY_BOOTSTRAP_RELEASE_KIND,
    )
    with pytest.raises(
        ReleaseArtifactVerificationError,
        match="bootstrap pointer provenance is invalid",
    ):
        _load(pointer, releases, paths["repo"])

    _write_pointer(
        pointer,
        release_id="r1",
        manifest_sha256=result["manifest_sha256"],
        release_kind="serving_identity_bootstrap_typo",
    )
    with pytest.raises(
        ReleaseArtifactVerificationError,
        match="release_kind is invalid",
    ):
        _load(pointer, releases, paths["repo"])


def test_reviewed_bootstrap_research_release_binds_as_non_production(
    tmp_path: Path,
):
    paths, _frozen, _result, releases, pointer = _active_fixture(
        tmp_path,
        candidate_mode=RESEARCH_ONLY_CANDIDATE_MODE,
        release_kind=SERVING_IDENTITY_BOOTSTRAP_RELEASE_KIND,
        release_kind_provenance=_bootstrap_provenance(),
    )

    bundle = _load(pointer, releases, paths["repo"])
    active = resolve_active_release(
        pointer_path=pointer,
        releases_root=releases,
        repo_root=paths["repo"],
        current_runtime_versions=_runtime_versions(),
        current_runtime_identity=_runtime_identity(),
    )

    assert bundle.status == STATUS_BOUND
    assert bundle.release_kind == SERVING_IDENTITY_BOOTSTRAP_RELEASE_KIND
    assert bundle.candidate_mode == RESEARCH_ONLY_CANDIDATE_MODE
    assert bundle.production_capable is False
    assert bundle.base_model_bound is True
    assert "research-only" in bundle.reason
    assert "non-capital" in bundle.reason
    lineage = serving_bundle_lineage(bundle)
    assert lineage["release_kind"] == SERVING_IDENTITY_BOOTSTRAP_RELEASE_KIND
    assert lineage["release_candidate_mode"] == RESEARCH_ONLY_CANDIDATE_MODE
    assert lineage["release_production_capable"] is False
    assert active["release_kind"] == SERVING_IDENTITY_BOOTSTRAP_RELEASE_KIND
    assert active["candidate_mode"] == RESEARCH_ONLY_CANDIDATE_MODE
    assert active["production_capable"] is False


def test_production_release_cannot_be_mislabeled_as_bootstrap(tmp_path: Path):
    paths, _frozen, _result, releases, pointer = _active_fixture(
        tmp_path,
        release_kind=SERVING_IDENTITY_BOOTSTRAP_RELEASE_KIND,
        release_kind_provenance=_bootstrap_provenance(),
    )

    with pytest.raises(
        ReleaseServingBindingError,
        match="production-capable release cannot use serving-identity bootstrap",
    ):
        _load(pointer, releases, paths["repo"])
    with pytest.raises(
        ReleaseArtifactVerificationError,
        match="bootstrap pointer does not bind a research-only release",
    ):
        resolve_active_release(
            pointer_path=pointer,
            releases_root=releases,
            repo_root=paths["repo"],
            current_runtime_versions=_runtime_versions(),
            current_runtime_identity=_runtime_identity(),
        )


@pytest.mark.parametrize(
    "role",
    [
        "pooled_band_model",
        "market_route_table",
        "base_model.nyc.feature_hgb",
        "base_model.nyc.probability_calibration",
        "base_model.shared.afternoon_residual_centering",
    ],
)
def test_verified_loader_rejects_model_or_route_hash_tampering(tmp_path: Path, role: str):
    paths, frozen, _result, releases, pointer = _active_fixture(tmp_path)
    declaration = next(row for row in frozen["declarations"] if row["role"] == role)
    path = releases / "r1" / declaration["path"]
    path.write_bytes(path.read_bytes() + b"tamper")

    with pytest.raises(ReleaseArtifactVerificationError, match="mismatch"):
        _load(pointer, releases, paths["repo"])


def test_verified_loader_rejects_role_path_substitution(tmp_path: Path):
    def swap_roles(rows):
        output = []
        for row in rows:
            row = dict(row)
            if row["role"] == "pooled_band_model":
                row["role"] = "locations_config"
            elif row["role"] == "locations_config":
                row["role"] = "pooled_band_model"
            output.append(row)
        return output

    paths, _frozen, _result, releases, pointer = _active_fixture(
        tmp_path,
        mutate_declarations=swap_roles,
    )

    with pytest.raises(ReleaseArtifactVerificationError, match="semantic serving contract"):
        _load(pointer, releases, paths["repo"])


def test_verified_loader_rejects_swapped_base_calibration_roles(tmp_path: Path):
    first = "base_model.nyc.probability_calibration"
    second = "base_model.nyc.forecast_error_model"

    def swap_roles(rows):
        output = []
        for original in rows:
            row = dict(original)
            if row["role"] == first:
                row["role"] = second
            elif row["role"] == second:
                row["role"] = first
            output.append(row)
        return output

    paths, _frozen, _result, releases, pointer = _active_fixture(
        tmp_path,
        mutate_declarations=swap_roles,
    )

    with pytest.raises(ReleaseArtifactVerificationError, match="semantic serving contract"):
        _load(pointer, releases, paths["repo"])


def test_verified_loader_rejects_omitted_base_component_role(tmp_path: Path):
    omitted = "base_model.nyc.settlement_lag_model"

    def omit_role(rows):
        return [row for row in rows if row["role"] != omitted]

    paths, _frozen, _result, releases, pointer = _active_fixture(
        tmp_path,
        mutate_declarations=omit_role,
    )

    with pytest.raises(ReleaseArtifactVerificationError, match="missing declared roles"):
        _load(pointer, releases, paths["repo"])


def test_verified_loader_rejects_manifest_to_route_artifact_mismatch(tmp_path: Path):
    paths, _frozen, _result, releases, pointer = _active_fixture(
        tmp_path,
        manifest_route={"schema_version": "release_market_route_table_v0.1", "markets": {}},
    )

    with pytest.raises(ReleaseArtifactVerificationError, match="exactly match"):
        _load(pointer, releases, paths["repo"])


def test_process_binding_requires_restart_after_pointer_change(tmp_path: Path):
    paths, _frozen, result, releases, pointer = _active_fixture(tmp_path)
    clear_process_serving_bundle_cache()
    first = get_process_active_serving_bundle(
        pointer_path=pointer,
        releases_root=releases,
        repo_root=paths["repo"],
        check_runtime=False,
    )
    _write_pointer(
        pointer,
        release_id="r1",
        manifest_sha256=result["manifest_sha256"],
        sequence=2,
    )
    second = get_process_active_serving_bundle(
        pointer_path=pointer,
        releases_root=releases,
        repo_root=paths["repo"],
        check_runtime=False,
    )
    clear_process_serving_bundle_cache()

    assert first.status == STATUS_BOUND
    assert second.status == STATUS_RESTART_REQUIRED
    assert serving_bundle_lineage(second)["release_id"] == ""


def test_no_pointer_is_explicit_non_countable_research_state(tmp_path: Path):
    bundle = load_verified_active_serving_bundle(
        pointer_path=tmp_path / "releases" / "current_release.json",
        releases_root=tmp_path / "releases",
        repo_root=tmp_path,
        check_runtime=False,
    )

    assert bundle.status == STATUS_RESEARCH_UNBOUND
    assert serving_bundle_lineage(bundle)["release_id"] == ""
    assert "non-countable" in bundle.reason


def test_release_bound_live_variant_ignores_malicious_legacy_registry_path(tmp_path: Path):
    paths, _frozen, _result, releases, pointer = _active_fixture(tmp_path, functional=True)
    bundle = _load(pointer, releases, paths["repo"])
    malicious_registry = tmp_path / "malicious_registry.json"
    malicious_registry.write_text(
        json.dumps(
            {
                "schema_version": "model_variant_registry_v0.1",
                "variants": [
                    {
                        "variant_id": "attacker",
                        "lifecycle": "active",
                        "track": "no_market",
                        "active_for_headline": True,
                        "artifact_path": str(tmp_path / "attacker.pkl"),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    captured_at = datetime(2026, 6, 18, 12, 0, tzinfo=timezone.utc)
    rows = build_live_variant_prediction_rows(
        snapshot_id="s1",
        captured_at=captured_at,
        event={"updatedAt": "u1"},
        model={
            "feature_vector": {
                "cutoff_hour": 12,
                "forecast_high": 80.0,
                "market_id": "nyc",
            }
        },
        model_client=FakeClient(),
        band_rows=[
            {
                "range_label": "80 F",
                "bin_kind": "eq",
                "bin_value_c": 80,
                "bin_value_hi_c": 80,
                "model_probability": 0.4,
                "market_yes": 0.3,
            }
        ],
        event_slug="highest-temperature-in-nyc-on-june-18-2026",
        market_id="nyc",
        target_date=date(2026, 6, 18),
        serving_model_version="legacy-base",
        release_lineage={"release_id": "attacker"},
        registry_path=malicious_registry,
        serving_bundle=bundle,
    )

    assert rows[0]["variant_id"] == "r1.pooled_band"
    assert rows[0]["prediction_status"] == "predicted"
    assert rows[0]["variant_probability"] == pytest.approx(0.77)
    assert rows[0]["release_id"] == "r1"
    assert rows[0]["artifact_path"] == bundle.artifact_paths["pooled_band_model"]
    assert rows[0]["serving_model_binding_status"] == "verified_release_base_model"


def test_bound_base_model_construction_never_reads_global_artifact_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    paths, _frozen, _result, releases, pointer = _active_fixture(tmp_path)
    bundle = _load(pointer, releases, paths["repo"])

    def forbidden_global_path(*_args, **_kwargs):
        raise AssertionError("global artifact path must not be resolved for an active release")

    monkeypatch.setattr(
        "weather.model.toronto_model.resolve_artifact_path",
        forbidden_global_path,
    )
    monkeypatch.setattr(
        "weather.model.model_features.resolve_artifact_path",
        forbidden_global_path,
    )

    model = TorontoHighTempModel(
        target_date=date(2026, 6, 18),
        market_id="nyc",
        serving_bundle=bundle,
    )

    assert model.load_feature_model_hgb()["12"]["fixture_component"] == "feature_hgb"
    assert model.load_feature_model_coefs()["fixture_component"] == "feature_lr_coefficients"
    assert model.load_late_day_model_coefs()["fixture_component"] == "late_day_lr_coefficients"
    assert model.calibrated_weights["fixture_component"] == "calibrated_weights"
    assert model.probability_calibration["fixture_component"] == "probability_calibration"
    assert model.forecast_error_model["fixture_component"] == "forecast_error_model"
    assert model.settlement_lag_model["fixture_component"] == "settlement_lag_model"
    assert model.afternoon_residual_centering["fixture_component"] == (
        "afternoon_residual_centering"
    )
    assert (
        model.family_secondary_artifacts["schema_version"]
        == "family_secondary_artifacts_v0.1"
    )


@pytest.mark.parametrize("mode", ["partial_components", "base_flag_unbound"])
def test_bound_base_model_rejects_mixed_bound_unbound_construction(
    tmp_path: Path,
    mode: str,
):
    paths, _frozen, _result, releases, pointer = _active_fixture(tmp_path)
    bundle = _load(pointer, releases, paths["repo"])
    if mode == "partial_components":
        components = dict(bundle.base_model_artifacts["nyc"])
        components.pop("probability_calibration")
        bundle = replace(bundle, base_model_artifacts={"nyc": components})
    else:
        bundle = replace(bundle, base_model_bound=False)

    with pytest.raises(ReleaseServingBindingError, match="base-model"):
        TorontoHighTempModel(
            target_date=date(2026, 6, 18),
            market_id="nyc",
            serving_bundle=bundle,
        )


def test_snapshot_store_requires_the_exact_bundle_used_to_construct_the_base_model(
    tmp_path: Path,
):
    paths, _frozen, _result, releases, pointer = _active_fixture(tmp_path)
    bundle = _load(pointer, releases, paths["repo"])
    model = TorontoHighTempModel(
        target_date=date(2026, 6, 18),
        market_id="nyc",
        serving_bundle=bundle,
    )

    _assert_snapshot_model_serving_binding(bundle, model)
    with pytest.raises(ReleaseServingBindingError, match="do not share"):
        _assert_snapshot_model_serving_binding(replace(bundle), model)


def test_failed_active_binding_emits_skip_without_legacy_fallback_or_identity(tmp_path: Path):
    blocked = VerifiedServingBundle(
        status=STATUS_BLOCKED,
        reason="route hash mismatch",
        pointer_present=True,
    )
    rows = build_live_variant_prediction_rows(
        snapshot_id="s1",
        captured_at=datetime(2026, 6, 18, 12, 0, tzinfo=timezone.utc),
        event={},
        model={"feature_vector": {"cutoff_hour": 12}},
        model_client=FakeClient(),
        band_rows=[{"bin_kind": "eq", "bin_value_c": 80, "model_probability": 0.4}],
        event_slug="event",
        market_id="nyc",
        target_date=date(2026, 6, 18),
        serving_model_version="legacy-base",
        registry_path=tmp_path / "must-not-be-read.json",
        serving_bundle=blocked,
    )

    assert rows[0]["prediction_status"] == "skipped"
    assert rows[0]["failure_reason"] == "release_binding_failed"
    assert rows[0]["release_id"] == ""
