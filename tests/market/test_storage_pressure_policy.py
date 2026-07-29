import json

from weather.market.storage_pressure_policy import (
    POLICY_SCHEMA_VERSION,
    load_storage_pressure_policy,
)


def test_configured_policy_can_disable_only_the_long_csv_projection(tmp_path):
    path = tmp_path / "storage_pressure.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": POLICY_SCHEMA_VERSION,
                "capture": {"write_order_books_long_csv": False},
            }
        ),
        encoding="utf-8",
    )

    policy = load_storage_pressure_policy(path)

    assert policy.status == "configured"
    assert policy.write_order_books_long_csv is False


def test_missing_or_ambiguous_policy_preserves_current_capture(tmp_path):
    missing = load_storage_pressure_policy(tmp_path / "missing.json")
    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text(
        json.dumps(
            {
                "schema_version": POLICY_SCHEMA_VERSION,
                "capture": {"write_order_books_long_csv": "false"},
            }
        ),
        encoding="utf-8",
    )
    invalid = load_storage_pressure_policy(invalid_path)

    assert missing.write_order_books_long_csv is True
    assert invalid.write_order_books_long_csv is True
    assert "fail_safe" in missing.status
    assert "fail_safe" in invalid.status


def test_duplicate_activation_key_is_ambiguous_and_fails_safe(tmp_path):
    path = tmp_path / "storage_pressure.json"
    path.write_text(
        (
            '{"schema_version":"storage_pressure_policy_v0.1",'
            '"capture":{"write_order_books_long_csv":true,'
            '"write_order_books_long_csv":false}}'
        ),
        encoding="utf-8",
    )

    policy = load_storage_pressure_policy(path)

    assert policy.write_order_books_long_csv is True
    assert "fail_safe" in policy.status
    assert "duplicate JSON key" in str(policy.detail)


def test_non_finite_json_is_ambiguous_and_fails_safe(tmp_path):
    path = tmp_path / "storage_pressure.json"
    path.write_text(
        (
            '{"schema_version":"storage_pressure_policy_v0.1",'
            '"capture":{"write_order_books_long_csv":true},'
            '"invalid":NaN}'
        ),
        encoding="utf-8",
    )

    policy = load_storage_pressure_policy(path)

    assert policy.write_order_books_long_csv is True
    assert "fail_safe" in policy.status
    assert "non-finite JSON constant" in str(policy.detail)
