"""Production enrollment procedure regression: synthetic bytes, no real authority."""
import json
import re

import pytest

from maker_core.evidence.journal import canonical_bytes
from maker_core.replay import authorization
from maker_core.replay.approved_registrations import APPROVED_REGISTRATIONS
from maker_core.replay.bundle import BundleError, sha256
from .fixtures.replay_authorization import sign_fixture


def test_enrollment_entries_are_only_raw_manifest_hashes_to_the_reviewed_owner():
    assert all(re.fullmatch(r"[0-9a-f]{64}", key) and owner == "michaelbooth1"
               for key, owner in APPROVED_REGISTRATIONS.items())


def test_empty_enrolled_changed_and_revoked_old_id(tmp_path, monkeypatch):
    monkeypatch.setattr(authorization, "APPROVED_REGISTRATIONS", {})
    doc = dict(owner="michaelbooth1", signed_at="2019-12-31T00:00:00Z", hurdles={"fixture_only": True},
               clusters=["date", "date_x_market"], policies=list(authorization.POLICIES))
    path, key, paths = sign_fixture(tmp_path, doc, monkeypatch)
    doc["owner_decision"]["authorization_id"] = "maker-replay-2026-10-12-v1"
    path.write_bytes(canonical_bytes(doc))
    key = sha256(path.read_bytes())
    log = paths["decision_log"]
    log.write_text(log.read_text(encoding="utf8").replace("fixture-1", "maker-replay-2026-10-12-v1"), encoding="utf8")
    monkeypatch.setattr(authorization, "APPROVED_REGISTRATIONS", {})
    with pytest.raises(BundleError, match="not_approved"):
        authorization.read_authorization(path, key, **paths)
    authorization.APPROVED_REGISTRATIONS[key] = "michaelbooth1"
    assert authorization.read_authorization(path, key, **paths) == doc
    path.write_bytes(path.read_bytes()+b"\n")
    with pytest.raises(BundleError, match="hash_mismatch"):
        authorization.read_authorization(path, key, **paths)
    path.write_bytes(canonical_bytes(doc))
    source = json.dumps({"authorization_id": "maker-replay-2026-10-12-v1"})
    log.write_text(log.read_text(encoding="utf8")+
        "| 2020-01-05 | REVOKE_MAKER_REPLAY | offline replay only | `"+source+"` | — |\n", encoding="utf8")
    with pytest.raises(BundleError, match="revoked"):
        authorization.read_authorization(path, key, **paths)
