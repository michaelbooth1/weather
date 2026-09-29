"""Fictional owner attestation; never enrolls authority outside pytest monkeypatch."""
from datetime import datetime, timezone
import json

from maker_core.evidence.journal import canonical_bytes
from maker_core.replay import authorization
from maker_core.replay.bundle import sha256


def sign_fixture(root, doc, monkeypatch):
    protocol, addendum, log = root/"protocol.md", root/"addendum.md", root/"DECISION_LOG.md"
    protocol.write_bytes(b"# FICTIONAL PROTOCOL\n")
    addendum.write_bytes(b"# FICTIONAL ADDENDUM\n")
    doc["owner_decision"] = dict(authorization_id="fixture-1", owner=doc["owner"],
        protocol_sha256=sha256(protocol.read_bytes()), addendum_sha256=sha256(addendum.read_bytes()),
        signed_at=doc["signed_at"], scoring_date="2020-01-05", expires_at="2020-01-06T05:00:00Z")
    row = ("| 2019-12-31 | APPROVE_MAKER_REPLAY | offline replay only | `"
           + json.dumps(doc["owner_decision"], sort_keys=True, separators=(",", ":")) + "` | — |\n")
    log.write_text("# FICTIONAL owner log\n\n" + authorization.LOG_HEADER
                   + "\n| --- | --- | --- | --- | --- |\n" + row, encoding="utf-8", newline="\n")
    path = root/"registration.json"
    path.write_bytes(canonical_bytes(doc))
    key = sha256(path.read_bytes())
    monkeypatch.setitem(authorization.APPROVED_REGISTRATIONS, key, doc["owner"])
    monkeypatch.setattr(authorization, "_utc_now", lambda: datetime(2020, 1, 5, 12, tzinfo=timezone.utc))
    return path, key, dict(decision_log=log, frozen_protocol=protocol, execution_addendum=addendum)
