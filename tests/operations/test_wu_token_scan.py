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


# --- N3: nothing unread may be reported CLEAN ------------------------------------------

_PLACEHOLDER_SUFFIX = ".placeholder"


def _simulate_placeholders(monkeypatch):
    """Report any entry named ``*.placeholder`` as a non-link reparse point.

    That is how a OneDrive cloud placeholder or a deduplicated file looks: the
    reparse attribute is set but the tag is not a name surrogate (symlink or
    junction). Real ones cannot be made without OneDrive or the dedup role.
    """
    original = wu_token_scan._reparse_info

    def fake(info, path):
        if str(path).endswith(_PLACEHOLDER_SUFFIX):
            return wu_token_scan._FILE_ATTRIBUTE_REPARSE_POINT, 0x9000701A  # IO_REPARSE_TAG_CLOUD_7
        return original(info, path)

    monkeypatch.setattr(wu_token_scan, "_reparse_info", fake)


def _recording_scan_file(monkeypatch):
    read = []
    original = wu_token_scan.scan_file

    def recording(path, patterns):
        hits = original(path, patterns)
        read.append(os.path.normcase(os.path.abspath(path)))
        return hits

    monkeypatch.setattr(wu_token_scan, "scan_file", recording)
    return read


def _every_regular_file(paths):
    """Every regular file a complete scan must read (no links followed, default exclusions)."""
    excluded = {name.casefold() for name in wu_token_scan.DEFAULT_EXCLUDED_DIR_NAMES}
    expected = set()
    for path in paths:
        path = str(path)
        if os.path.isfile(path):
            expected.add(os.path.normcase(os.path.abspath(path)))
            continue
        for directory, dirnames, filenames in os.walk(path, followlinks=False):
            dirnames[:] = [name for name in dirnames if name.casefold() not in excluded]
            for name in filenames:
                expected.add(os.path.normcase(os.path.abspath(os.path.join(directory, name))))
    return expected


def _assert_clean_means_all_read(payload, read, expected):
    if payload["status"] == "CLEAN":
        unread = sorted(expected - set(read))
        assert unread == [], f"CLEAN with unread files: {unread}"


def _scenario_tree(root):
    (root / "logs").mkdir(parents=True)
    (root / "logs" / "a.log").write_text("clean apiKey=<redacted>\n", encoding="utf-8")
    (root / "logs" / "b.log").write_text("clean\n", encoding="utf-8")
    return root


class _SpecialEntry:
    """A directory entry that is neither a regular file nor a directory (a FIFO or socket)."""

    def __init__(self, entry):
        self._entry = entry
        self.name, self.path = entry.name, entry.path

    def __getattr__(self, name):
        return getattr(self._entry, name)

    def is_dir(self, *, follow_symlinks=True):
        return False

    def is_file(self, *, follow_symlinks=True):
        return False


def _scandir_with_special_entries(real_scandir):
    class _Scandir:
        """``os.scandir`` stand-in (context manager and iterator, like the real one)."""

        def __init__(self, path="."):
            self._inner = real_scandir(path)

        def __iter__(self):
            return self

        def __next__(self):
            entry = next(self._inner)
            return _SpecialEntry(entry) if entry.name.endswith(".special") else entry

        def close(self):
            self._inner.close()

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.close()

    return _Scandir


@pytest.mark.parametrize("policy", wu_token_scan.LINK_POLICIES)
@pytest.mark.parametrize(
    "scenario",
    ["plain", "placeholder_file", "placeholder_dir", "files_dir", "files_missing", "unreadable",
     "special_entry", "oversize", "max_files"],
)
def test_ratchet_nothing_unread_is_ever_clean(tmp_path, monkeypatch, policy, scenario):
    """N3 invariant: a CLEAN report means every regular file under the request was read.

    Not marked ``ratchet``: it runs in the ordinary suite shards; the repository
    ratchet (test_wu_token_repository_scan) asserts the same on every tracked file.
    """
    _simulate_placeholders(monkeypatch)
    root = _scenario_tree(tmp_path / "root")
    kwargs = {"link_policy": policy}
    roots, files = [root], None
    must_be_clean = scenario in {"plain", "files_dir"}
    extra_expected = []
    if scenario == "placeholder_file":
        (root / "logs" / ("cloud" + _PLACEHOLDER_SUFFIX)).write_text("hydrated text\n", encoding="utf-8")
        # Following within the root reads it in place; the other policies leave it unread.
        must_be_clean = policy == wu_token_scan.LINKS_FOLLOW_WITHIN_ROOT
    elif scenario == "placeholder_dir":
        hidden = root / ("synced" + _PLACEHOLDER_SUFFIX)
        hidden.mkdir()
        (hidden / "inner.log").write_text("clean\n", encoding="utf-8")
        must_be_clean = policy == wu_token_scan.LINKS_FOLLOW_WITHIN_ROOT
    elif scenario == "files_dir":
        roots, files = [], [root / "logs"]
    elif scenario == "files_missing":
        roots, files = [], [root / "logs" / "a.log", root / "gone.log"]
    elif scenario == "unreadable":
        (root / "logs" / "locked.log").write_text("x\n", encoding="utf-8")
        original = wu_token_scan.scan_file

        def locked(path, patterns):
            if str(path).endswith("locked.log"):
                raise PermissionError(13, "locked")
            return original(path, patterns)

        monkeypatch.setattr(wu_token_scan, "scan_file", locked)
    elif scenario == "special_entry":
        (root / "logs" / "pipe.special").write_text("", encoding="utf-8")
        monkeypatch.setattr(wu_token_scan.os, "scandir", _scandir_with_special_entries(os.scandir))
    elif scenario == "oversize":
        (root / "logs" / "big.log").write_text("y" * 4096, encoding="utf-8")
        kwargs["max_file_bytes"] = 1024
    elif scenario == "max_files":
        kwargs["max_files"] = 1

    read = _recording_scan_file(monkeypatch)
    result = scan(roots, files=files, **kwargs)
    payload = wu_token_scan.report(result, roots or files)

    expected = _every_regular_file(roots if files is None else [p for p in files if os.path.exists(p)])
    expected.update(extra_expected)
    _assert_clean_means_all_read(payload, read, expected)
    assert (payload["status"] == "CLEAN") is must_be_clean, (payload["status"], payload["unread_reasons"])
    assert (payload["unread_reasons"] == []) is must_be_clean


def test_mutant_unrecorded_placeholder_is_caught_by_the_ratchet(tmp_path, monkeypatch):
    """If a skipped placeholder were not recorded, the ratchet check would fail."""
    _simulate_placeholders(monkeypatch)
    root = _scenario_tree(tmp_path / "root")
    (root / "logs" / ("cloud" + _PLACEHOLDER_SUFFIX)).write_text("x\n", encoding="utf-8")
    monkeypatch.setattr(wu_token_scan, "_record_skipped_reparse", lambda result, path: None)
    read = _recording_scan_file(monkeypatch)

    payload = wu_token_scan.report(scan([root], link_policy="ignore"), [root])

    assert payload["status"] == "CLEAN"
    with pytest.raises(AssertionError):
        _assert_clean_means_all_read(payload, read, _every_regular_file([root]))


def test_files_list_directory_is_walked_not_dropped(tmp_path, token):
    """N3 (a): a directory in ``files=`` is walked; it never vanishes from a CLEAN scan."""
    (tmp_path / "d" / "sub").mkdir(parents=True)
    (tmp_path / "d" / "sub" / "leak.log").write_text(f"apiKey={token}\n", encoding="utf-8")

    result = scan([], files=[tmp_path / "d"])

    assert exit_code_for(result) == EXIT_FOUND
    assert [os.path.basename(row["path"]) for row in result.findings] == ["leak.log"]


@pytest.mark.parametrize("policy", wu_token_scan.LINK_POLICIES)
def test_placeholder_file_is_never_clean_unread(tmp_path, token, monkeypatch, capsys, policy):
    """N3 (b): ``--links ignore`` may skip links, but an unread placeholder makes the scan INCOMPLETE."""
    _simulate_placeholders(monkeypatch)
    (tmp_path / "plain.log").write_text("clean\n", encoding="utf-8")
    placeholder = tmp_path / ("cloud" + _PLACEHOLDER_SUFFIX)
    placeholder.write_text(f"apiKey={token}\n", encoding="utf-8")

    code, out, err = _run(capsys, [tmp_path, "--links", policy])

    payload = json.loads(out)
    assert token not in out and token not in err
    if policy == wu_token_scan.LINKS_FOLLOW_WITHIN_ROOT:
        assert code == EXIT_FOUND  # read in place: its resolved path is itself, inside the root
        return
    assert code == EXIT_ERROR and payload["status"] == "INCOMPLETE"
    assert payload["skipped_reparse_points"] == 1
    assert payload["skipped_reparse_paths"] == [str(placeholder)]
    assert payload["reparse_incomplete"] is True
    assert "reparse_points_unread" in payload["unread_reasons"]
    # A placeholder is not a link: the link counters stay untouched.
    assert payload["skipped_links"] == 0


def test_unclassifiable_entry_is_not_waived_by_ignore(tmp_path, monkeypatch):
    """An entry whose type cannot be read is unread content, not a waivable link."""
    (tmp_path / "a.log").write_text("clean\n", encoding="utf-8")

    def broken(info, path):
        raise OSError("cannot read attributes")

    monkeypatch.setattr(wu_token_scan, "_reparse_info", broken)

    result = scan([tmp_path], link_policy="ignore")

    assert exit_code_for(result) == EXIT_ERROR


# --- N3 P2: encoded key forms ----------------------------------------------------------


@pytest.mark.parametrize(
    "template",
    [
        "%2522apiKey%2522%253A%2522{t}%2522",  # double URL-encoded JSON
        "apiKey%253D{t}",  # double URL-encoded '='
        "apikey%253a{t}",
        "\\u0022apiKey\\u0022:\\u0022{t}\\u0022",  # JSON-escaped quotes
        "\\u0022apiKey\\u0022\\u003a\\u0022{t}\\u0022",
        "X-Api-Key: {t}",  # header names
        "x-api-key={t}",
        "{{'X-Api-Key': '{t}'}}",
        "apiKey&#61;{t}",
    ],
)
def test_n3_encoded_and_header_forms_are_found(tmp_path, capsys, template):
    hex_token = secrets.token_hex(16)
    (tmp_path / "enc.log").write_text("prefix " + template.format(t=hex_token) + "\n", encoding="utf-8")

    code, out, err = _run(capsys, [tmp_path])

    assert code == EXIT_FOUND, template
    assert hex_token not in out and hex_token not in err


@pytest.mark.parametrize(
    "template",
    [
        "commit%253D{sha40}",
        "%2522commit%2522%253A%2522{sha40}%2522",
        "\\u0022sha256\\u0022:\\u0022{sha256}\\u0022",
        "X-Request-Id: {uuid}",
        "X-Api-Key: {uuid}",  # a dashed uuid is not token-shaped
        "X-Api-Key-Version: 2" + " " * 70 + "{sha40}",
        "x-api-key=<redacted> ref%2522{sha40}%2522",
        "apiKey%253D%2522{sha40}",
    ],
)
def test_n3_new_forms_do_not_match_shas_or_uuids(tmp_path, capsys, template):
    import uuid

    text = template.format(sha40=secrets.token_hex(20), sha256=secrets.token_hex(32), uuid=uuid.uuid4())
    (tmp_path / "fp.log").write_text("prefix " + text + "\n", encoding="utf-8")

    code, out, _err = _run(capsys, [tmp_path])

    assert code == EXIT_CLEAN, (template, json.loads(out)["findings"])
