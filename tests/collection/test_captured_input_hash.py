import json
import os
import time
from unittest.mock import patch

import pytest

from weather.captured_input_hash import captured_input_payload_sha256
from weather.collection.snapshot_store import SnapshotStore
from weather.release_artifacts import (
    ReleaseArtifactVerificationError,
    canonical_payload_sha256,
)


def test_captured_input_hash_survives_integer_bucket_json_round_trip():
    writer_payload = {
        "schema_version": "toronto_replay_inputs_v0.2",
        "snapshot_id": "snapshot-1",
        "recorded_distribution": {8: 0.2, 9: 0.3, 10: 0.5},
        "sources": {
            "fixture": {
                "ok": True,
                "bucket_counts": {81: 2, 82: 3, 103: 1},
            }
        },
    }
    writer_digest = canonical_payload_sha256(writer_payload)
    persisted_payload = json.loads(json.dumps(writer_payload, sort_keys=True))

    assert canonical_payload_sha256(persisted_payload) != writer_digest
    assert (
        captured_input_payload_sha256(writer_payload, persisted=False)
        == writer_digest
    )
    assert (
        captured_input_payload_sha256(persisted_payload, persisted=True)
        == writer_digest
    )


def test_captured_input_hash_preserves_genuine_numeric_string_key_order():
    writer_payload = {
        "recorded_distribution": {8: 0.5, 10: 0.5},
        "sources": {
            "fixture": {
                "string_codes": {"10": "ten", "2": "two"},
            }
        },
    }
    persisted_payload = json.loads(json.dumps(writer_payload, sort_keys=True))

    assert captured_input_payload_sha256(
        persisted_payload,
        persisted=True,
    ) == (
        captured_input_payload_sha256(writer_payload, persisted=False)
    )


def test_captured_input_hash_omits_its_self_hash():
    payload = {
        "recorded_distribution": {"8": 0.4, "10": 0.6},
        "captured_input_hash": "claimed",
    }

    assert captured_input_payload_sha256(
        payload,
        persisted=True,
    ) == captured_input_payload_sha256(
        {key: value for key, value in payload.items() if key != "captured_input_hash"},
        persisted=True,
    )


@pytest.mark.parametrize("bucket", [True, "-0", "08", "8.0", "not-a-bucket"])
def test_captured_input_hash_rejects_noncanonical_bucket_keys(bucket):
    with pytest.raises(ReleaseArtifactVerificationError):
        captured_input_payload_sha256(
            {"recorded_distribution": {bucket: 1.0}},
            persisted=True,
        )


def test_snapshot_lock_does_not_expire_while_owner_is_alive(tmp_path):
    store = SnapshotStore(root=tmp_path, event_slug="fixture")
    store.lock_path.write_text(str(os.getpid()), encoding="ascii")
    old = time.time() - 600
    os.utime(store.lock_path, (old, old))

    with patch(
        "weather.collection.snapshot_store._process_is_running",
        return_value=True,
    ):
        assert store.lock_is_stale() is False


def test_snapshot_lock_recovers_a_dead_owner_without_waiting_for_age(tmp_path):
    store = SnapshotStore(root=tmp_path, event_slug="fixture")
    store.lock_path.write_text("999999", encoding="ascii")

    with patch(
        "weather.collection.snapshot_store._process_is_running",
        return_value=False,
    ):
        assert store.lock_is_stale() is True
