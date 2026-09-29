from datetime import datetime
import json

import pytest

from maker_core.evidence.journal import canonical_bytes
from maker_core.replay import authorization
from maker_core.replay.bundle import BundleError, sha256
from maker_core.replay.__main__ import main
from .fixtures.replay_authorization import sign_fixture


def fixture(tmp_path, monkeypatch):
    doc = dict(owner="FICTIONAL TEST OWNER", signed_at="2019-12-31T00:00:00Z", hurdles={"fixture_only": True},
               clusters=["date", "date_x_market"], policies=list(authorization.POLICIES))
    return sign_fixture(tmp_path, doc, monkeypatch)


def test_valid_row_checks_exact_document_bytes(tmp_path, monkeypatch):
    path, key, paths = fixture(tmp_path, monkeypatch)
    result = authorization.read_authorization(path, key, **paths)
    assert result["owner_decision"]["authorization_id"] == "fixture-1"
    assert "signature" not in result


@pytest.mark.parametrize("target", ["frozen_protocol", "execution_addendum"])
def test_changed_bytes_or_newlines_refuse_before_bundle_io(tmp_path, monkeypatch, target):
    import maker_core.replay.__main__ as cli
    path, key, paths = fixture(tmp_path, monkeypatch)
    paths[target].write_bytes(paths[target].read_bytes().replace(b"\n", b"\r\n"))
    monkeypatch.setattr(cli, "load_bundle", lambda *a, **k: pytest.fail("bundle was opened"))
    monkeypatch.setattr(cli, "comparison_report", lambda *a, **k: pytest.fail("scorer was invoked"))
    args = ["run", "--compare", "--bundle", "missing", "--out", str(tmp_path/"out"),
            "--pre-registration", str(path), "--pre-registration-sha256", key]
    for field, value in paths.items():
        args += ["--"+field.replace("_", "-"), str(value)]
    with pytest.raises(SystemExit) as exc:
        main(args)
    assert exc.value.code == 2 and not (tmp_path/"out").exists()


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "revoked", "superseded", "owner", "purpose", "hash", "duplicate_json", "fenced", "fenced_table", "commented"])
def test_log_missing_ambiguous_tampered_or_superseded_refuses(tmp_path, monkeypatch, mutation):
    path, key, paths = fixture(tmp_path, monkeypatch)
    text = paths["decision_log"].read_text(encoding="utf-8")
    row = text.splitlines(keepends=True)[-1]
    if mutation == "missing":
        text = text.replace(row, "")
    elif mutation == "duplicate":
        text += row
    elif mutation == "revoked":
        text = text.replace("APPROVE_MAKER_REPLAY", "REVOKE_MAKER_REPLAY")
    elif mutation == "superseded":
        text += row.replace("APPROVE_MAKER_REPLAY", "REVOKE_MAKER_REPLAY")
    elif mutation == "owner":
        text = text.replace("FICTIONAL TEST OWNER", "other owner")
    elif mutation == "purpose":
        text = text.replace("offline replay only", "live")
    elif mutation == "hash":
        text = text.replace(json.loads(path.read_bytes())["owner_decision"]["addendum_sha256"], "0"*64)
    elif mutation == "duplicate_json":
        text = text.replace('"authorization_id":', '"authorization_id":"duplicate","authorization_id":')
    elif mutation == "fenced":
        text = text.replace(row, "\n```text\n" + row + "```\n")
    elif mutation == "fenced_table":
        text = "```markdown\n" + text + "```\n"
    elif mutation == "commented":
        text = "<!--\n" + text + "-->\n"
    paths["decision_log"].write_text(text, encoding="utf-8")
    with pytest.raises(BundleError):
        authorization.read_authorization(path, key, **paths)


@pytest.mark.parametrize("now", ["2019-12-30T12:00:00+00:00", "2020-01-05T04:59:59+00:00", "2020-01-06T05:00:00+00:00"])
def test_not_yet_signed_wrong_local_date_and_expiry_refuse(tmp_path, monkeypatch, now):
    path, key, paths = fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(authorization, "_utc_now", lambda: datetime.fromisoformat(now))
    with pytest.raises(BundleError, match="time_window"):
        authorization.read_authorization(path, key, **paths)


def test_old_signature_string_missing_paths_and_unapproved_hash_cannot_grant_authority(tmp_path, monkeypatch):
    path, key, paths = fixture(tmp_path, monkeypatch)
    with pytest.raises(BundleError, match="paths_required"):
        authorization.read_authorization(path, key)
    doc = json.loads(path.read_bytes())
    del doc["owner_decision"]
    doc["signature"] = "a nonempty review URL is not a row"
    raw = canonical_bytes(doc)
    path.write_bytes(raw)
    monkeypatch.setitem(authorization.APPROVED_REGISTRATIONS, sha256(raw), doc["owner"])
    with pytest.raises(BundleError, match="invalid_owner_decision"):
        authorization.read_authorization(path, sha256(raw), **paths)
    monkeypatch.setattr(authorization._Reader, "read", lambda *a, **k: pytest.fail("unapproved IO"))
    with pytest.raises(BundleError, match="not_approved"):
        authorization.read_authorization(path, "0"*64, **paths)


@pytest.mark.parametrize("flag", ["--decision-log", "--frozen-protocol", "--execution-addendum"])
def test_diagnostic_mode_does_not_accept_authorization_flags(flag):
    with pytest.raises(SystemExit) as exc:
        main(["run", "--bundle", "missing", "--out", "missing", flag, "missing"])
    assert exc.value.code == 2
