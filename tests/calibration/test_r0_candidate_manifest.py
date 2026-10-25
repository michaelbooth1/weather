"""R0 candidate manifest writer (retrain memo R0.1 step 4, piece M13).

Guards: retrain memo R0.2 M13 - one self-hashed, write-once manifest per centre binds every trained
market's base-only coefs/HGB/report, allowlist and training_inputs plus the five served components'
bytes; any gap, mismatch or LFS pointer fails closed. R0 M7/M8 (owner 2026-10-23, r0_scope): only
US 11 markets in r0 allowlist mode, every US 11 market trained or excluded with a reason, Toronto
always excluded, and each market's served_model_differences bound. Fixture trees only.
"""

from __future__ import annotations

import json
import pickle

import pytest

from weather.calibration.r0_candidate_manifest import (
    MANIFEST_FILENAME,
    MANIFEST_RECORD_VERSION,
    R0CandidateManifestError,
    SERVED_COMPONENTS,
    build_r0_candidate_manifest,
    main,
    served_component_paths,
    verify_r0_candidate_manifest,
    write_r0_candidate_manifest,
)
from weather.calibration.r0_scope import (
    R0_MARKET_IDS,
    R0_OUT_OF_SCOPE_MARKETS,
    served_model_differences,
)

COMMIT = "a" * 40
CORPUS = {
    "corpora": [{"corpus_id": "c" * 64, "manifest_sha256": "d" * 64, "years": [2021, 2022]}],
    "union_sha256": "e" * 64,
}


def _inputs(centre="2026-11-24", corpus=CORPUS):
    return {
        "centre_date": centre,
        "centre_date_pinned": True,
        "training_years": [2021, 2022],
        "training_days_by_year": {"2021": 15, "2022": 15},
        "forecast_source": "pit_forecast_corpus",
        "pit_forecast_corpus": corpus,
    }


ALLOWLIST = {
    "mode": "r0",
    "sha256": "f" * 64,
    "feature_names": ["high_so_far"],
    "served_feature_names": ["high_so_far", "pressure"],
    "column_differences_from_served": [
        {"column": "pressure", "reason": "training_policy_exclusion", "decision": "fixture"},
    ],
}


def _trained(root, market, *, inputs=None, hgb_inputs=None, base_only=True, report=True,
             allowlist=ALLOWLIST, differences=True):
    folder = root / market
    folder.mkdir(parents=True)
    info = {"12": {"feature_names": ["high_so_far"]}, "training_column_allowlist": allowlist,
            "training_inputs": inputs or _inputs()}
    if differences:
        info["served_model_differences"] = served_model_differences(
            allowlist, info["training_inputs"], base_models_only=True,
        )
    if base_only:
        info["base_models_only"] = True
    (folder / f"feature_model_coefs_{market}.json").write_text(json.dumps(info), encoding="utf-8")
    hgb = dict(info, training_inputs=hgb_inputs or info["training_inputs"])
    (folder / f"feature_model_hgb_{market}.pkl").write_bytes(pickle.dumps(hgb))
    if report:
        (folder / f"feature_model_report_{market}.md").write_text("# report\n", encoding="utf-8")


def _served(repo, market, *, pointer=None):
    for component, path in served_component_paths(repo, market).items():
        path.parent.mkdir(parents=True, exist_ok=True)
        body = "version https://git-lfs.github.com/spec/v1\n" if component == pointer else json.dumps({component: market})
        path.write_text(body, encoding="utf-8")


@pytest.fixture
def tree(tmp_path):
    candidates, repo = tmp_path / "cand", tmp_path / "repo"
    for market in ("atlanta", "nyc"):
        _trained(candidates, market)
        _served(repo, market)
    return candidates, repo


def _rest(markets, reason="fixture: not trained"):
    return {market: reason for market in R0_MARKET_IDS if market not in markets}


def _build(candidates, repo, **overrides):
    markets = overrides.get("markets", ["nyc", "atlanta"])
    kwargs = dict(candidate_id="retrain-r0-2026-11-24", centre="2026-11-24", markets=markets,
                  build_commit=COMMIT, excluded_markets={"toronto": "no PIT corpus", **_rest(markets)},
                  repo_root=repo)
    kwargs.update(overrides)
    return build_r0_candidate_manifest(candidates, **kwargs)


def test_manifest_binds_trained_and_served_bytes(tree):
    candidates, repo = tree
    manifest = _build(candidates, repo)
    assert manifest["window"] == {"centre": "2026-11-24", "half_width_days": 7,
                                  "prior_year_month_day_start": "11-17", "prior_year_month_day_end": "12-01"}
    assert list(manifest["markets"]) == ["atlanta", "nyc"]
    nyc = manifest["markets"]["nyc"]
    assert set(nyc["trained"]) == {"feature_hgb", "feature_lr_coefficients", "report"}
    assert set(nyc["served_components"]) == set(SERVED_COMPONENTS)
    assert nyc["served_components"]["late_day_lr_coefficients"]["path"] == "artifacts/models/coefs/late_day_model_coefs_nyc.json"
    assert nyc["training_column_allowlist_sha256"] == "f" * 64
    assert manifest["pit_forecast_corpora"][0]["corpus_id"] == "c" * 64
    assert manifest["training_years"] == [2021, 2022]
    assert manifest["record_version"] == MANIFEST_RECORD_VERSION == 2
    assert manifest["excluded_markets"]["toronto"] == (
        f"{R0_OUT_OF_SCOPE_MARKETS['toronto']}; caller: no PIT corpus"
    )
    assert manifest["excluded_markets"]["miami"] == "fixture: not trained"
    assert set(manifest["excluded_markets"]) == (set(R0_MARKET_IDS) - {"nyc", "atlanta"}) | {"toronto"}
    assert manifest["scope"]["r0_market_ids"] == list(R0_MARKET_IDS)
    assert manifest["scope"]["allowlist_mode"] == "r0"
    differences = nyc["served_model_differences"]
    assert differences["columns_removed"] == ALLOWLIST["column_differences_from_served"]
    assert differences["base_models_only"] is True
    assert differences["centre_date"] == "2026-11-24"
    out = write_r0_candidate_manifest(manifest, candidates / MANIFEST_FILENAME)
    assert verify_r0_candidate_manifest(out, repo_root=repo) == manifest
    with pytest.raises(R0CandidateManifestError, match="never overwritten"):
        write_r0_candidate_manifest(manifest, out)


def test_verify_detects_changed_candidate_and_served_bytes(tree):
    candidates, repo = tree
    out = write_r0_candidate_manifest(_build(candidates, repo), candidates / MANIFEST_FILENAME)
    (candidates / "nyc" / "feature_model_report_nyc.md").write_text("# edited\n", encoding="utf-8")
    with pytest.raises(R0CandidateManifestError, match="nyc report bytes differ"):
        verify_r0_candidate_manifest(out)
    (candidates / "nyc" / "feature_model_report_nyc.md").write_text("# report\n", encoding="utf-8")
    verify_r0_candidate_manifest(out)
    served_component_paths(repo, "atlanta")["settlement_lag_model"].write_text("{}", encoding="utf-8")
    verify_r0_candidate_manifest(out)  # served bytes are checked only with repo_root
    with pytest.raises(R0CandidateManifestError, match="served settlement_lag_model differs"):
        verify_r0_candidate_manifest(out, repo_root=repo)
    body = json.loads(out.read_text(encoding="utf-8"))
    body["build_commit"] = "b" * 40
    out.write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(R0CandidateManifestError, match="self-hash"):
        verify_r0_candidate_manifest(out)


@pytest.mark.parametrize(
    "setup, message",
    [
        (lambda c, r: (c / "nyc" / "feature_model_report_nyc.md").unlink(), "nyc report is missing"),
        (lambda c, r: _served(r, "nyc", pointer="forecast_error_model"), "LFS pointer"),
    ],
)
def test_missing_or_pointer_files_fail_closed(tree, setup, message):
    candidates, repo = tree
    setup(candidates, repo)
    with pytest.raises(R0CandidateManifestError, match=message):
        _build(candidates, repo)


def test_wrong_centre_or_unpinned_fit_fails_closed(tmp_path):
    repo = tmp_path / "repo"
    _served(repo, "nyc")
    _trained(tmp_path / "a", "nyc", inputs=_inputs(centre="2026-12-10"))
    with pytest.raises(R0CandidateManifestError, match="not pinned 2026-11-24"):
        _build(tmp_path / "a", repo, markets=["nyc"])
    unpinned = dict(_inputs(), centre_date_pinned=False)
    _trained(tmp_path / "b", "nyc", inputs=unpinned)
    with pytest.raises(R0CandidateManifestError, match="not pinned"):
        _build(tmp_path / "b", repo, markets=["nyc"])


def test_inconsistent_artifacts_fail_closed(tmp_path):
    repo = tmp_path / "repo"
    for market in ("nyc", "atlanta"):
        _served(repo, market)
    _trained(tmp_path / "a", "nyc", hgb_inputs=dict(_inputs(), training_days_by_year={"2021": 1}))
    with pytest.raises(R0CandidateManifestError, match="coefs and HGB training_inputs differ"):
        _build(tmp_path / "a", repo, markets=["nyc"])
    _trained(tmp_path / "b", "nyc", base_only=False)
    with pytest.raises(R0CandidateManifestError, match="not a base-models-only fit"):
        _build(tmp_path / "b", repo, markets=["nyc"])
    other = dict(CORPUS, union_sha256="0" * 64)
    _trained(tmp_path / "c", "nyc")
    _trained(tmp_path / "c", "atlanta", inputs=_inputs(corpus=other))
    with pytest.raises(R0CandidateManifestError, match="different corpora"):
        _build(tmp_path / "c", repo)


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"build_commit": "abc"}, "40-hex"),
        ({"candidate_id": "R0 bad"}, "plain slug"),
        ({"markets": []}, "non-empty"),
        ({"markets": ["nyc", "nyc"]}, "without repeats"),
        ({"excluded_markets": {"nyc": "x"}}, "both trained and excluded"),
        ({"excluded_markets": {}}, "neither trained nor excluded"),
        ({"markets": ["nyc", "toronto"], "excluded_markets": _rest(["nyc"])}, "outside R0"),
    ],
)
def test_invalid_arguments_fail_closed(tree, overrides, message):
    candidates, repo = tree
    with pytest.raises(R0CandidateManifestError, match=message):
        _build(candidates, repo, **overrides)


def test_cli_writes_the_default_path(tree, capsys):
    candidates, repo = tree
    rest = [arg for market, reason in _rest(["nyc"]).items()
            for arg in ("--exclude-market", f"{market}={reason}")]
    code = main(["--candidate-root", str(candidates), "--candidate-id", "retrain-r0-2026-11-24",
                 "--centre", "2026-11-24", "--build-commit", COMMIT, "--market", "nyc",
                 *rest, "--repo-root", str(repo)])
    assert code == 0
    printed = json.loads(capsys.readouterr().out)
    manifest = verify_r0_candidate_manifest(candidates / MANIFEST_FILENAME, repo_root=repo)
    assert printed["manifest_sha256"] == manifest["manifest_sha256"]
    assert list(manifest["markets"]) == ["nyc"]
    assert manifest["excluded_markets"]["toronto"] == R0_OUT_OF_SCOPE_MARKETS["toronto"]


def test_toronto_cannot_be_trained_and_other_modes_are_refused(tmp_path):
    repo = tmp_path / "repo"
    _served(repo, "nyc")
    served_policy = dict(ALLOWLIST, mode="served-policy")
    _trained(tmp_path / "a", "nyc", allowlist=served_policy)
    with pytest.raises(R0CandidateManifestError, match="not 'r0:nyc'"):
        _build(tmp_path / "a", repo, markets=["nyc"])
    _trained(tmp_path / "b", "nyc", differences=False)
    with pytest.raises(R0CandidateManifestError, match="no served_model_differences"):
        _build(tmp_path / "b", repo, markets=["nyc"])
    with pytest.raises(ValueError, match="unknown market id"):
        _build(tmp_path / "b", repo, markets=["nyc"], excluded_markets={"mars": "x", **_rest(["nyc"])})


def test_tampered_differences_record_fails_closed(tmp_path):
    repo = tmp_path / "repo"
    _served(repo, "nyc")
    folder = tmp_path / "a"
    _trained(folder, "nyc")
    coefs_path = folder / "nyc" / "feature_model_coefs_nyc.json"
    body = json.loads(coefs_path.read_text(encoding="utf-8"))
    body["served_model_differences"]["columns_removed"] = []
    coefs_path.write_text(json.dumps(body), encoding="utf-8")
    hgb_path = folder / "nyc" / "feature_model_hgb_nyc.pkl"
    hgb = pickle.loads(hgb_path.read_bytes())
    hgb["served_model_differences"]["columns_removed"] = []
    hgb_path.write_bytes(pickle.dumps(hgb))
    with pytest.raises(R0CandidateManifestError, match="does not match the allowlist"):
        _build(folder, repo, markets=["nyc"])


def _set_leaf(folder, market, leaf):
    """Rewrite one fixture fit as an R0 leaf-sweep fit at ``leaf`` (both artifacts)."""
    params = {"max_iter": 50, "max_leaf_nodes": 15, "learning_rate": 0.05,
              "min_samples_leaf": leaf, "served_min_samples_leaf": 20}
    coefs_path = folder / market / f"feature_model_coefs_{market}.json"
    hgb_path = folder / market / f"feature_model_hgb_{market}.pkl"
    coefs = json.loads(coefs_path.read_text(encoding="utf-8"))
    hgb = pickle.loads(hgb_path.read_bytes())
    for info in (coefs, hgb):
        info["hgb_hyperparameters"] = params
        info["served_model_differences"] = served_model_differences(
            info["training_column_allowlist"], info["training_inputs"], base_models_only=True,
            hgb_min_samples_leaf=leaf,
        )
    coefs_path.write_text(json.dumps(coefs), encoding="utf-8")
    hgb_path.write_bytes(pickle.dumps(hgb))


def test_leaf_sweep_value_is_bound_and_must_agree_across_markets(tree):
    candidates, repo = tree
    _set_leaf(candidates, "nyc", 10)
    with pytest.raises(R0CandidateManifestError, match="different HGB leaf floors"):
        _build(candidates, repo)
    _set_leaf(candidates, "atlanta", 10)
    manifest = _build(candidates, repo)
    assert manifest["hgb_min_samples_leaf"] == 10
    assert manifest["markets"]["nyc"]["hgb_min_samples_leaf"] == 10
    assert manifest["markets"]["nyc"]["served_model_differences"]["hyperparameters"]["hgb_min_samples_leaf"] == 10


def test_fits_without_a_leaf_record_bind_at_the_served_floor(tree):
    candidates, repo = tree
    assert _build(candidates, repo)["hgb_min_samples_leaf"] == 20
