"""Read-only WU page-token scanner: finds token-shaped values, never prints them, honours caps.

Guards: OD15 (owner decision 2026-10-06) -- the production agent's leak scan over logs, tapes and
snapshots reports paths, counts and offsets only; docs/operations/HISTORY_DATA_DESIGN.md "Page access token".
"""

from __future__ import annotations

import json
import os
import secrets

import pytest

from weather.operations import wu_token_scan
from weather.operations.wu_token_scan import (
    EXIT_CLEAN,
    EXIT_ERROR,
    EXIT_FOUND,
    exit_code_for,
    main,
    scan,
    scan_file,
)


@pytest.fixture
def token():
    return "FAKEKEY" + secrets.token_hex(16)


def _run(capsys, argv):
    code = main([str(item) for item in argv])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _fixture_tree(root, token):
    (root / "logs").mkdir(parents=True)
    (root / "snapshots" / "2026-06-19").mkdir(parents=True)
    (root / "wunderground" / "klga").mkdir(parents=True)
    (root / "logs" / "clean.log").write_text("all good apiKey=<redacted>\n", encoding="utf-8")
    (root / "logs" / "leak.log").write_text(
        "x" * 100 + f"GET /v1/x?apiKey={token}&units=e\nagain apiKey={token}\n", encoding="utf-8"
    )
    (root / "wunderground" / "klga" / "backfill_errors.jsonl").write_text(
        json.dumps({"error": "boom", "payload": {"apiKey": token}}) + "\n", encoding="utf-8"
    )
    (root / "snapshots" / "2026-06-19" / "page.html").write_text(
        f'<script>const data = {{"API_URL":"https://api.example.invalid","API_KEY":"{token}"}};</script>',
        encoding="utf-8",
    )
    (root / "logs" / "dict_repr.log").write_text(
        f"params={{'apiKey': '{token}', 'units': 'e'}}\nconfig apiKey: {token}\n", encoding="utf-8"
    )
    (root / "snapshots" / "2026-06-19" / "angular.html").write_text(
        f"&q;API_KEY&q;:&q;{token}&q;", encoding="utf-8"
    )
    (root / "snapshots" / "2026-06-19" / "harmless.py").write_text(
        "def f(api_key=None):\n    return {'apiKey': '<redacted>'}\n", encoding="utf-8"
    )


def test_scanner_finds_fake_tokens_and_never_prints_them(tmp_path, token, capsys):
    _fixture_tree(tmp_path, token)

    code, out, err = _run(capsys, [tmp_path])

    assert code == EXIT_FOUND
    assert token not in out and token not in err
    assert token[7:] not in out  # not even the hex tail
    payload = json.loads(out)
    assert payload["status"] == "FOUND"
    assert payload["matched_text_reported"] is False
    by_name = {os.path.basename(row["path"]): row for row in payload["findings"]}
    assert set(by_name) == {"leak.log", "backfill_errors.jsonl", "page.html", "angular.html", "dict_repr.log"}
    leak = by_name["leak.log"]
    assert leak["matches"]["apikey_query_param"] == 2
    assert leak["first_match_offset"]["apikey_query_param"] == 100 + len("GET /v1/x?")
    assert by_name["backfill_errors.jsonl"]["matches"]["apikey_colon_field"] == 1
    assert by_name["dict_repr.log"]["matches"]["apikey_colon_field"] == 2
    assert by_name["page.html"]["matches"]["wu_page_api_key_block"] == 1
    assert by_name["angular.html"]["matches"]["wu_page_api_key_block"] == 1
    assert by_name["page.html"]["matches"]["hex32_near_apikey"] == 1
    for row in payload["findings"]:
        assert set(row) == {"path", "size_bytes", "matches", "first_match_offset"}


def test_scanner_reports_clean_tree(tmp_path, capsys):
    (tmp_path / "a.log").write_text("apiKey=<redacted> api_key=None API_KEY_STORAGE_REF\n", encoding="utf-8")

    code, out, _err = _run(capsys, [tmp_path])

    assert code == EXIT_CLEAN
    assert json.loads(out)["status"] == "CLEAN"


def test_token_from_env_finds_exact_value_without_echo(tmp_path, token, capsys, monkeypatch):
    # A bare token with no apiKey name next to it: only the exact-token pattern can see it.
    (tmp_path / "tape.jsonl").write_text(f'{{"blob": "zz{token}zz"}}\n', encoding="utf-8")
    monkeypatch.setenv("WU_SCAN_FAKE_TOKEN", token)

    code, out, err = _run(capsys, [tmp_path, "--token-from-env", "WU_SCAN_FAKE_TOKEN"])

    assert code == EXIT_FOUND
    assert token not in out and token not in err
    payload = json.loads(out)
    assert payload["exact_token_env"] == "WU_SCAN_FAKE_TOKEN"
    assert payload["findings"][0]["matches"] == {"exact_env_token": 1}
    assert payload["findings"][0]["first_match_offset"] == {"exact_env_token": len('{"blob": "zz')}


def test_token_from_env_unset_is_an_error(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("WU_SCAN_MISSING", raising=False)

    code, out, _err = _run(capsys, [tmp_path, "--token-from-env", "WU_SCAN_MISSING"])

    assert code == EXIT_ERROR
    assert json.loads(out)["status"] == "ERROR"


def test_missing_root_is_incomplete_not_clean(tmp_path, capsys):
    code, out, _err = _run(capsys, [tmp_path / "absent"])

    assert code == EXIT_ERROR
    assert json.loads(out)["status"] == "INCOMPLETE"


def test_max_files_cap_truncates_and_is_never_clean(tmp_path, capsys):
    for index in range(5):
        (tmp_path / f"f{index}.log").write_text("clean\n", encoding="utf-8")

    code, out, _err = _run(capsys, [tmp_path, "--max-files", "3"])

    payload = json.loads(out)
    assert code == EXIT_ERROR
    assert payload["files_scanned"] == 3
    assert payload["truncated_reason"] == "max_files"


def test_max_file_bytes_skips_large_files_and_lists_them(tmp_path, token, capsys):
    (tmp_path / "big.log").write_text("x" * 5000 + f"apiKey={token}", encoding="utf-8")
    (tmp_path / "small.log").write_text("clean\n", encoding="utf-8")

    code, out, _err = _run(capsys, [tmp_path, "--max-file-bytes", "1000"])

    payload = json.loads(out)
    assert code == EXIT_ERROR
    assert [os.path.basename(row["path"]) for row in payload["skipped_oversize"]] == ["big.log"]
    assert payload["findings"] == []
    assert token not in out


def test_max_total_bytes_cap_truncates(tmp_path, capsys):
    for index in range(4):
        (tmp_path / f"f{index}.log").write_text("y" * 100, encoding="utf-8")

    code, out, _err = _run(capsys, [tmp_path, "--max-total-bytes", "250"])

    payload = json.loads(out)
    assert code == EXIT_ERROR
    assert payload["files_scanned"] == 2
    assert payload["truncated_reason"] == "max_total_bytes"


def test_symlinks_are_not_followed(tmp_path, token):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "leak.log").write_text(f"apiKey={token}", encoding="utf-8")
    inside = tmp_path / "inside"
    inside.mkdir()
    try:
        os.symlink(outside, inside / "link", target_is_directory=True)
        os.symlink(outside / "leak.log", inside / "file_link.log")
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation needs privileges on this host")

    result = scan([inside])

    assert result.findings == []
    assert result.skipped_links == 2
    assert sorted(os.path.basename(path) for path in result.skipped_link_paths) == ["file_link.log", "link"]
    # S1: a skipped link leaves a subtree unread, so the scan is never CLEAN by default.
    assert exit_code_for(result) == EXIT_ERROR
    assert exit_code_for(scan([inside], link_policy="ignore")) == EXIT_CLEAN
    # The target is outside the requested root, so following stays off.
    followed = scan([inside], link_policy="follow-within-root")
    assert followed.findings == [] and followed.skipped_links == 2
    assert exit_code_for(followed) == EXIT_ERROR


def test_unknown_link_policy_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        scan([tmp_path], link_policy="follow")


def test_links_flag_is_reported_in_caps_and_payload(tmp_path, capsys):
    (tmp_path / "a.log").write_text("clean\n", encoding="utf-8")

    code, out, _err = _run(capsys, [tmp_path, "--links", "ignore"])

    payload = json.loads(out)
    assert code == EXIT_CLEAN
    assert payload["caps"]["links"] == "ignore"
    assert payload["link_policy"] == "ignore"
    assert payload["skipped_link_paths"] == [] and payload["links_incomplete"] is False


@pytest.mark.parametrize(
    "template",
    [
        "%22apiKey%22%3A%22{t}%22",  # URL-encoded JSON (Defender S2 f3)
        "apiKey%3A{t}",  # URL-encoded colon
        "q=%22apikey%22%3A%22{t}%22&x=1",
        "%27apiKey%27%3A%20%27{t}%27",
    ],
)
def test_token_after_percent_escape_is_found(tmp_path, capsys, template):
    hex_token = secrets.token_hex(16)
    (tmp_path / "enc.log").write_text("prefix " + template.format(t=hex_token) + "\n", encoding="utf-8")

    code, out, err = _run(capsys, [tmp_path])

    assert code == EXIT_FOUND
    assert hex_token not in out and hex_token not in err
    assert json.loads(out)["findings"][0]["matches"].get("hex32_near_apikey", 0) >= 1


def test_hex32_safety_net_alone_catches_percent_escaped_token(tmp_path):
    hex_token = secrets.token_hex(16)
    path = tmp_path / "enc.log"
    path.write_text(f"%22apiKey%22%3A%22{hex_token}%22", encoding="utf-8")

    hits = scan_file(path, {"hex32_near_apikey": wu_token_scan.PATTERNS["hex32_near_apikey"]})

    assert hits == {"hex32_near_apikey": (1, len("%22"))}


def test_percent_escape_does_not_make_longer_hex_runs_match(tmp_path):
    # A 40-hex run (for example a git SHA) after an apiKey name is not a 32-hex token.
    path = tmp_path / "sha.log"
    path.write_text(f"apiKey docs %22{secrets.token_hex(20)}%22", encoding="utf-8")

    assert scan_file(path, {"hex32_near_apikey": wu_token_scan.PATTERNS["hex32_near_apikey"]}) == {}


def test_mutant_old_hex_lookbehind_misses_percent_escaped_token(tmp_path):
    """The pre-fix hex32 pattern must fail the S2 form, so the new test is meaningful."""
    import re

    old = re.compile(rb"(?is)api_?key.{0,64}?(?<![0-9a-f])[0-9a-f]{32}(?![0-9a-f])")
    path = tmp_path / "enc.log"
    path.write_text(f"%22apiKey%22%3A%22{secrets.token_hex(16)}%22", encoding="utf-8")

    assert scan_file(path, {"hex32_near_apikey": old}) == {}


def test_excluded_directory_names_are_skipped(tmp_path, token):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "leak").write_text(f"apiKey={token}", encoding="utf-8")

    assert scan([tmp_path]).findings == []
    assert len(scan([tmp_path], excluded_dir_names=()).findings) == 1


def test_match_straddling_a_chunk_boundary_is_counted_once(tmp_path, token, monkeypatch):
    monkeypatch.setattr(wu_token_scan, "CHUNK_BYTES", 64)
    monkeypatch.setattr(wu_token_scan, "OVERLAP_BYTES", 48)
    body = "a" * 49 + "?" + f"apiKey={token}" + "b" * 89 + "&" + f"apiKey={token}" + "c" * 7
    path = tmp_path / "chunks.log"
    path.write_text(body, encoding="utf-8")

    hits = scan_file(path, {"apikey_query_param": wu_token_scan.PATTERNS["apikey_query_param"]})

    assert hits["apikey_query_param"] == (2, 50)


def test_mutant_scanner_echoing_matches_is_detected(tmp_path, token, capsys, monkeypatch):
    """A scanner that reported matched text would fail the no-echo assertion."""
    _fixture_tree(tmp_path, token)
    original = wu_token_scan.report

    def leaky_report(result, roots, **kwargs):
        payload = original(result, roots, **kwargs)
        payload["leaked"] = [open(row["path"], encoding="utf-8").read() for row in result.findings]
        return payload

    monkeypatch.setattr(wu_token_scan, "report", leaky_report)
    _code, out, _err = _run(capsys, [tmp_path])
    assert token in out
