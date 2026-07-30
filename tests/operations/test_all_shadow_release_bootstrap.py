from weather.operations.all_shadow_release_bootstrap import (
    _runtime_market_inventory,
    _verified_release_role_source,
    all_shadow_promotion,
)


def test_runtime_inventory_is_exact_twelve_market_native_unit_fleet():
    inventory = _runtime_market_inventory()

    assert inventory["market_count"] == 12
    assert inventory["fahrenheit_market_count"] == 11
    assert inventory["toronto_unit"] == "C"
    assert inventory["market_ids"] == sorted(inventory["market_ids"])


def test_all_shadow_promotion_has_no_promote_or_blocked_market():
    promotion = all_shadow_promotion()

    assert promotion["verdict"] == "shadow"
    assert promotion["promote_markets"] == []
    assert promotion["blocked_markets"] == []
    assert len(promotion["shadow_markets"]) == 12
    assert "toronto" in promotion["shadow_markets"]


def test_verified_source_release_selects_exact_hash_bound_model_role(
    tmp_path,
    monkeypatch,
):
    release = tmp_path / "r1"
    model = release / "model" / "bundle.pkl"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"verified bundle")
    from weather.release_artifacts import sha256_file

    digest = sha256_file(model)
    monkeypatch.setattr(
        "weather.operations.all_shadow_release_bootstrap.verify_release",
        lambda *_args, **_kwargs: {
            "status": "PASS",
            "manifest_sha256": "a" * 64,
            "manifest": {
                "release_id": "r1",
                "artifacts": {
                    "inventory": [
                        {
                            "role": "pooled_band_model",
                            "path": "model/bundle.pkl",
                            "sha256": digest,
                        }
                    ]
                },
            },
        },
    )

    source, proof = _verified_release_role_source(
        release,
        role="pooled_band_model",
    )

    assert source == model
    assert proof["release_id"] == "r1"
    assert proof["role_sha256"] == digest
    assert proof["integrity_verification_status"] == "PASS"
