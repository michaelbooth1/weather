"""Landing preflight pilots (non-binding shadows) and the adopted M3a receipt and docs-transaction pre-check.

Guards: the owner-approved Swarm L pilots and their Defender (OD) conditions. M13: the byte-exact
EOF-newline-only predicate admits the 05:51 precedent (6c6ab479 on 202245b4) and refuses every OD attack
(Python indentation, whitespace inside triple-quoted strings and here-strings, YAML ``|+``, LF->CRLF and
hash-frozen files); it reports ``suite_skip_eligible`` as INFO and never changes a verdict or an exit code.
M3b: the final-tip binding shadow can never turn a FAIL into a PASS. M5: the dual-run recorder disqualifies
host-only tests and hash-pinned scripts and counts toward "the later of 5 concordant landings or 14 days",
any discordance resetting. M3a: ``docs_transaction`` is a real check and a stale or edited receipt is refused.

Fixture repositories are built with git plumbing (``test_landing_preflight.FixtureRepo``); no test starts
PowerShell (Linux CI runs this module).
"""

from __future__ import annotations

import itertools
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tests.operations.test_landing_preflight import (  # noqa: F401  (fx is a fixture)
    CAPTURE_HOST,
    NO_TESTS,
    OBJECT_CHECKS,
    WORKSTATION,
    FixtureRepo,
    _run_git,
    fx,
    registry_of,
    run,
)
from weather.operations import landing_preflight as lp
from weather.operations import landing_preflight_m5 as m5
from weather.operations import landing_preflight_pilots as pilots
from weather.paths import REPO_ROOT

pytestmark = pytest.mark.spawns

PILOT_CHECKS = OBJECT_CHECKS + ("eof_newline_only",)
SOP = "docs/operations/STATE_OF_PLAY.md"


def _eof(doc: dict) -> dict:
    return doc["checks"]["eof_newline_only"]


def _reasons(check: dict) -> list[str]:
    return [d["reason"] for d in check["evidence"]["disqualifiers"]]


# --------------------------------------------------------------------------- M13: the byte-exact predicate


@pytest.mark.parametrize(("old", "new", "expected"), [
    (b"a\n\n", b"a\n", True),                      # the 05:51 class: one blank line at EOF removed
    (b"a\n\n\n\n", b"a\n", True),
    (b"a", b"a\n", True),                          # a missing final newline added
    (b"a\n", b"a", False),                         # final newline removed
    (b"a\n", b"a\n\n", False),                     # blank line at EOF added
    (b"a\r\n", b"a\n", False),                     # CR change at EOF
    (b"a\n", b"a\r\n", False),
    (b"a\r\n\r\n", b"a\r\n", False),               # CRLF tail: never qualifies
    (b"a\nb\n", b"a\r\nb\r\n", False),             # whole file LF -> CRLF
    (b"a  \nb\n\n", b"a\nb\n", False),             # a mid-file trailing-space change rides along
    (b"a\n", b"a\n", False),                       # unchanged is not a change
])
def test_eof_newline_only_change_is_byte_exact(old, new, expected):
    assert pilots.eof_newline_only_change(old, new) is expected


def _eof_base(fx: FixtureRepo, extra: dict[str, str] | None = None) -> str:
    files = {f"docs/ws/{i:02d}.md": f"line {i}\n\n" for i in range(37)}
    files.update(extra or {})
    base = fx.commit(fx.base, files, "files ending in a blank line")
    _run_git(fx.repo, "update-ref", "refs/heads/master", base)
    return base


def test_eof_newline_only_true_for_37_eof_blank_line_deletions_and_never_changes_the_verdict(fx):
    base = _eof_base(fx)
    head = fx.commit(base, {f"docs/ws/{i:02d}.md": f"line {i}\n" for i in range(37)}, "drop EOF blank lines")
    code, doc = run(fx, fx.options(head), registry=registry_of(*PILOT_CHECKS))
    check = _eof(doc)
    assert check["status"] == "INFO" and check["evidence"]["suite_skip_eligible"] is True, check["summary"]
    assert check["evidence"]["file_count"] == 37 and check["evidence"]["binding"] is False
    code_without, doc_without = run(fx, fx.options(head, out="without.json"), registry=registry_of(*OBJECT_CHECKS))
    assert (code, doc["verdict"]["status"]) == (code_without, doc_without["verdict"]["status"]) == (
        NO_TESTS, "PASS_NO_TESTS")
    assert "eof_newline_only" not in doc["verdict"]["failing_checks"] + doc["verdict"]["warnings"]


QUIET = "scripts/ops/quiet_window_merge.ps1"
REGISTERED = "scripts/ops/nightly_thing.ps1"
CONFIG_PINNED = "scripts/ops/pinned_helper.ps1"
ATTACK_BASE = {
    "src/weather/attack.py": "def f(x):\n    if x:\n        x += 1\n    return x\n",
    "src/weather/literal.py": 'TEXT = """first  \n\nsecond\n"""\nN = 1\n',
    "scripts/ops/here.ps1": "$t = @'\nfirst\n\nsecond\n'@\nWrite-Output $t\n",
    "config/block.yaml": "key: |+\n  kept\n\n\n",
    "scripts/ops/crlf.ps1": "Write-Output 1\nWrite-Output 2\n",
    QUIET: "param([string]$ExpectedSelfSha256 = '')\nWrite-Output merge\n\n",
    REGISTERED: "Write-Output nightly\n\n",
    "scripts/ops/register_nightly_thing.ps1": (
        "param([string]$ExpectedScriptSha256 = '')\n$script = Join-Path $repo 'scripts\\ops\\nightly_thing.ps1'\n"),
    CONFIG_PINNED: "Write-Output pinned\n\n",
    "config/pins.json": json.dumps({"helpers": [{"path": CONFIG_PINNED, "sha256": "0" * 64}]}),
}


@pytest.mark.parametrize(("case", "files", "reason", "path"), [
    ("python_indentation", {"src/weather/attack.py": "def f(x):\n    if x:\n        x += 1\n        return x\n"},
     "not_eof_newline_only", "src/weather/attack.py"),
    ("triple_quoted_whitespace", {"src/weather/literal.py": 'TEXT = """first\nsecond\n"""\nN = 1\n'},
     "not_eof_newline_only", "src/weather/literal.py"),
    ("here_string_blank_line", {"scripts/ops/here.ps1": "$t = @'\nfirst\nsecond\n'@\nWrite-Output $t\n"},
     "not_eof_newline_only", "scripts/ops/here.ps1"),
    ("yaml_keep_chomping", {"config/block.yaml": "key: |+\n  kept\n"}, "yaml_excluded", "config/block.yaml"),
    ("lf_to_crlf", {"scripts/ops/crlf.ps1": "Write-Output 1\r\nWrite-Output 2\r\n"},
     "not_eof_newline_only", "scripts/ops/crlf.ps1"),
    ("hash_frozen_merge_tool", {QUIET: "param([string]$ExpectedSelfSha256 = '')\nWrite-Output merge\n"},
     "hash_frozen", QUIET),
    ("register_pinned_script", {REGISTERED: "Write-Output nightly\n"}, "hash_frozen", REGISTERED),
    ("config_pinned_script", {CONFIG_PINNED: "Write-Output pinned\n"}, "hash_frozen", CONFIG_PINNED),
])
def test_every_od_attack_is_ineligible(fx, case, files, reason, path):
    base = _eof_base(fx, ATTACK_BASE)
    eof_fix = {f"docs/ws/{i:02d}.md": f"line {i}\n" for i in range(3)}  # an eligible part rides along
    head = fx.commit(base, {**eof_fix, **files}, f"attack {case}")
    code, doc = run(fx, fx.options(head), registry=registry_of(*PILOT_CHECKS))
    check = _eof(doc)
    assert check["status"] == "INFO" and check["evidence"]["suite_skip_eligible"] is False
    rows = [(d["reason"], d["path"]) for d in check["evidence"]["disqualifiers"]]
    assert (reason, path) in rows, rows
    _, doc_without = run(fx, fx.options(head, out="without.json"), registry=registry_of(*OBJECT_CHECKS))
    assert doc["verdict"]["status"] == doc_without["verdict"]["status"] and code == doc_without["verdict"]["exit_code"]


def test_hash_frozen_list_is_derived_from_the_tree(fx):
    base = _eof_base(fx, ATTACK_BASE)
    git = pilots.git_bytes_runner(["-C", str(fx.repo)])
    tree = _run_git(fx.repo, "rev-parse", f"{base}^{{tree}}")
    frozen = pilots.hash_frozen_paths(git, tree, [CONFIG_PINNED, "docs/ws/00.md"])
    assert {QUIET, REGISTERED, CONFIG_PINNED} <= set(frozen) and "docs/ws/00.md" not in frozen
    assert "ExpectedSelfSha256" in frozen[QUIET] or "named" in frozen[QUIET]
    assert "register_nightly_thing.ps1" in frozen[REGISTERED] and "config/pins.json" in frozen[CONFIG_PINNED]
    assert set(pilots.NAMED_HASH_FROZEN) <= set(frozen)


def test_a_crashing_pilot_is_info_never_an_error(fx, monkeypatch):
    base = _eof_base(fx)
    head = fx.commit(base, {"docs/ws/00.md": "line 0\n"}, "one EOF fix")

    def boom(*_a, **_k):
        raise RuntimeError("pilot bug")

    monkeypatch.setattr(pilots, "evaluate_eof_newline_only", boom)
    code, doc = run(fx, fx.options(head), registry=registry_of(*PILOT_CHECKS))
    assert _eof(doc)["status"] == "INFO" and _eof(doc)["evidence"]["suite_skip_eligible"] is False
    assert code == NO_TESTS and doc["verdict"]["status"] == "PASS_NO_TESTS"


def _have(sha: str) -> bool:
    try:
        _run_git(REPO_ROOT, "cat-file", "-e", f"{sha}^{{commit}}")
        return True
    except Exception:
        return False


@pytest.mark.skipif(not (_have("6c6ab479") and _have("202245b4")), reason="05:51 precedent commits not in this clone")
def test_the_0551_precedent_is_eligible_on_the_real_objects():
    git = pilots.git_bytes_runner(["-C", str(REPO_ROOT)])
    tree = lambda ref: git("rev-parse", f"{ref}^{{tree}}").decode().strip()  # noqa: E731
    result = pilots.evaluate_eof_newline_only(git, tree("202245b4"), tree("6c6ab479"))
    assert result["eof_newline_only"] is True, result["disqualifiers"][:5]
    assert result["file_count"] == 37 and all(r["newlines_removed"] == 1 for r in result["per_file"])


# --------------------------------------------------------------------------- M3a: docs_transaction is a real check


def test_docs_transaction_fails_when_a_required_document_is_absent(fx):
    head = fx.commit(fx.base, {SOP: None}, "drop STATE_OF_PLAY")
    code, doc = run(fx, fx.options(head))
    check = doc["checks"]["docs_transaction"]
    assert check["status"] == "FAIL" and any(SOP in f for f in check["evidence"]["failures"])
    assert "docs_transaction" in doc["verdict"]["failing_checks"] and code == lp.EXIT_FAIL


def test_docs_transaction_fails_with_the_transactions_git_diff_check(fx):
    head = fx.commit(fx.base, {"docs/x.md": "x\n\n"}, "EOF blank line")
    code, doc = run(fx, fx.options(head))
    check = doc["checks"]["docs_transaction"]
    assert check["status"] == "FAIL" and any("git_diff_check" in f for f in check["evidence"]["failures"])
    assert code == lp.EXIT_FAIL


def test_docs_transaction_warns_on_a_later_slots_check_hit(fx):
    head = fx.commit(fx.base, {"docs/y.md": "y\n"}, "head")
    later = fx.commit(head, {"docs/z.md": "z  \n"}, "later with trailing space")
    path = fx.plan([{"head": "h", "sha": head, "prs": [1]}, {"head": "l", "sha": later, "prs": [2]}])
    _, doc = run(fx, fx.options(head, "--night-plan", str(path)))
    check = doc["checks"]["docs_transaction"]
    assert check["status"] == "WARN" and check["evidence"]["later_diff_check_hits"]


# --------------------------------------------------------------------------- M3b: binding shadow never relaxes


def test_m3b_shadow_fails_a_night_whose_later_integration_moves_state_of_play(fx):
    """The OD no-relaxation case: without a review bound to the FINAL tip the night still fails."""

    head = fx.commit(fx.base, {"docs/y.md": "y\n"}, "head")
    later = fx.commit(head, {SOP: "# State\nlater edit\n"}, "later integration moves STATE_OF_PLAY")
    path = fx.plan([{"head": "h", "sha": head, "prs": [1]}, {"head": "l", "sha": later, "prs": [2]}])
    _, doc = run(fx, fx.options(head, "--night-plan", str(path)))
    check = doc["checks"]["docs_transaction"]
    shadow = check["evidence"]["m3b_binding_shadow"]
    assert shadow["status"] == "INFO" and shadow["binding"] is False
    assert shadow["would_conclude"] == "FAIL" and SOP in shadow["failing_documents"]
    assert shadow["effective_if_adopted"] == "FAIL"
    assert check["status"] == "WARN"  # the shadow did not change the real check
    rows = {r["path"]: r for r in check["evidence"]["documents"]}
    final = rows[SOP]["final_tip_oid"]
    bound_final = {p: r["final_tip_oid"] for p, r in rows.items()}
    assert pilots.m3b_binding_shadow(check["evidence"]["documents"], "WARN", final_tip_known=True,
                                     reviews=bound_final)["would_conclude"] == "PASS"
    assert final != rows[SOP]["landing_oid"]


STATUSES = ("PASS", "INFO", "WARN", "ERROR", "FAIL", "SKIP")


@pytest.mark.parametrize(("current", "landing", "final", "known", "review"), list(itertools.product(
    STATUSES, ("a" * 40, None), ("a" * 40, "b" * 40, None), (True, False), ("landing", "final", "none"))))
def test_m3b_shadow_can_never_turn_a_fail_into_a_pass(current, landing, final, known, review):
    docs = [{"path": SOP, "required_disposition": True, "landing_oid": landing, "final_tip_oid": final},
            {"path": "docs/roadmap/active-backlog.md", "required_disposition": True, "landing_oid": "c" * 40,
             "final_tip_oid": "c" * 40}]
    reviews = None if review == "landing" else ({d["path"]: d["final_tip_oid"] for d in docs} if review == "final"
                                                else {})
    shadow = pilots.m3b_binding_shadow(docs, current, final_tip_known=known, reviews=reviews)
    rank = {"PASS": 0, "INFO": 0, "SKIP": 0, "WARN": 1, "ERROR": 2, "FAIL": 3}
    assert rank[shadow["effective_if_adopted"]] >= rank[current]
    if current == "FAIL":
        assert shadow["effective_if_adopted"] == "FAIL"
    assert shadow["status"] == "INFO" and shadow["binding"] is False


# --------------------------------------------------------------------------- M3a: the receipt for the handback


def test_receipt_is_refused_when_stale_or_edited(fx, tmp_path, capsys):
    head = fx.commit(fx.base, {"docs/y.md": "y\n"}, "head")
    _, doc = run(fx, fx.options(head))
    assert lp.verify_receipt(doc, origin_master=fx.base, expect_head=head) == []
    assert any(p.startswith("stale") for p in lp.verify_receipt(doc, origin_master="f" * 40))
    edited = json.loads(json.dumps(doc))
    edited["verdict"]["status"] = "PASS"
    assert any("does not match" in p for p in lp.verify_receipt(edited, origin_master=fx.base))
    out = Path(doc["receipt"]["out_path"])
    assert lp.main(["--verify-receipt", str(out), "--origin-master", fx.base, "--expect-head", head]) == lp.EXIT_PASS
    assert lp.main(["--verify-receipt", str(out), "--origin-master", "f" * 40]) == lp.EXIT_ERROR
    assert "REFUSED: stale" in capsys.readouterr().out
    assert doc["receipt"]["sha256"] in doc["receipt"]["handback_line"]


# --------------------------------------------------------------------------- M5: shadow dual-run recorder


def _workflow(*files: str) -> str:
    body = "\n".join(f"              {f}" for f in files)
    return ("jobs:\n  native-launch:\n    strategy:\n      matrix:\n        include:\n          - shard: a\n"
            f"            files: >-\n{body}\n")


HOST_TESTS = {
    "tests/test_win_unsharded.py": '"""Guards: x."""\nimport os\nimport pytest\n'
                                   'pytestmark = pytest.mark.skipif(os.name != "nt", reason="w")\n',
    "tests/test_win_sharded.py": '"""Guards: x."""\nimport os\nimport pytest\n'
                                 'pytestmark = pytest.mark.skipif(os.name != "nt", reason="w")\n',
    "tests/test_ci_skip.py": '"""Guards: x."""\nimport os\nSKIP = os.environ.get("GITHUB_ACTIONS")\n',
    "tests/test_identity.py": '"""Guards: x."""\nfrom weather.free import MODE\nCMD = "icacls x /grant"\n',
    ".github/workflows/windows-qualification.yml": _workflow("tests/test_win_sharded.py"),
}


def test_host_only_tests_are_enumerated_mechanically(fx):
    base = fx.commit(fx.base, HOST_TESTS, "host tests")
    git = pilots.git_bytes_runner(["-C", str(fx.repo)])
    tree = _run_git(fx.repo, "rev-parse", f"{base}^{{tree}}")
    found = m5.host_only_tests(git, tree, ["tests/test_free.py"])
    assert found == {
        "tests/test_ci_skip.py": ["skipped_on_ci"],
        "tests/test_free.py": ["junit_host_only"],
        "tests/test_identity.py": ["host_identity_api"],
        "tests/test_win_unsharded.py": ["windows_only_not_in_ci_windows_lane"],
    }


def test_junit_host_only_nodeids(tmp_path):
    def junit(name: str, cases: str) -> Path:
        path = tmp_path / name
        path.write_text(f"<testsuites><testsuite>{cases}</testsuite></testsuites>", encoding="utf-8")
        return path

    host = junit("host.xml", '<testcase classname="tests.operations.test_a" name="t1"/>'
                             '<testcase classname="tests.operations.test_a.TestK" name="t2"/>'
                             '<testcase classname="tests.test_b" name="t3"/>')
    ci = junit("ci.xml", '<testcase classname="tests.operations.test_a" name="t1"/>'
                         '<testcase classname="tests.test_b" name="t3"><skipped/></testcase>')
    ids = m5.junit_host_only_nodeids([host], [ci])
    assert ids == ["tests.operations.test_a.TestK::t2", "tests.test_b::t3"]
    assert m5.nodeid_files(ids, ["tests/operations/test_a.py", "tests/test_b.py"]) == [
        "tests/operations/test_a.py", "tests/test_b.py"]


def _ci(tmp_path: Path, sha: str, windows: str = "success", other: str = "success") -> Path:
    path = tmp_path / f"ci-{sha[:8]}-{windows}-{other}.json"
    path.write_text(json.dumps({"check_runs": [
        {"name": "native-launch (launch)", "conclusion": windows, "head_sha": sha},
        {"name": "test", "conclusion": other, "head_sha": sha}]}), encoding="utf-8")
    return path


def _host(tmp_path: Path, sha: str, outcome: str = "PASS", roll: str = "ROLL-FREE",
          landed: str = "2026-10-07T03:10:00+00:00") -> Path:
    path = tmp_path / f"host-{sha[:8]}.json"
    path.write_text(json.dumps({"tip_sha": sha, "roll_verdict": roll, "landed_at": landed,
                                "bounded_suite": {"outcome": outcome, "failed_nodeids": []},
                                "source": "production agent handback"}), encoding="utf-8")
    return path


def _record(fx: FixtureRepo, head: str, ci: Path, host: Path, ledger: Path, host_id: str = WORKSTATION,
            out: str | None = None) -> tuple[int, dict]:
    _, doc = run(fx, fx.options(head, out=out or f"pf-{head[:8]}.json"))
    args = m5.build_parser().parse_args([
        "record", "--preflight", doc["receipt"]["out_path"], "--host-outcome", str(host), "--ci-checks", str(ci),
        "--repo", str(fx.repo), "--ledger", str(ledger)])
    return m5.record(args, host_id_fn=lambda: host_id)


def test_m5_records_a_concordant_landing_and_refuses_duplicates_and_bad_inputs(fx, tmp_path):
    ledger = tmp_path / "ledger" / "m5.jsonl"
    head = fx.commit(fx.base, {"docs/y.md": "y\n"}, "roll-free docs tip")
    code, payload = _record(fx, head, _ci(tmp_path, head), _host(tmp_path, head), ledger)
    assert code == m5.EXIT_OK, payload
    row = payload["row"]
    assert row["schema"] == m5.LEDGER_SCHEMA and row["binding"] is False
    assert (row["predicted_suite_pass"], row["host_suite_pass"], row["concordant"], row["counted"]) == (
        True, True, True, True)
    assert row["ci"]["windows_lane"] == "success" and row["preflight"]["status"] == "PASS_NO_TESTS"
    assert payload["progress"]["concordant_since_reset"] == 1 and payload["progress"]["threshold_met"] is False
    code, payload = _record(fx, head, _ci(tmp_path, head), _host(tmp_path, head), ledger, out="again.json")
    assert code == m5.EXIT_REFUSED and "already in the ledger" in payload["error"]

    other = fx.commit(fx.base, {"docs/w.md": "w\n"}, "another tip")
    code, payload = _record(fx, other, _ci(tmp_path, head), _host(tmp_path, other), ledger)
    assert code == m5.EXIT_REFUSED and "not " + other in payload["error"]  # CI for another SHA
    code, payload = _record(fx, other, _ci(tmp_path, other), _host(tmp_path, other), ledger,
                            host_id=CAPTURE_HOST)
    assert code == m5.EXIT_REFUSED and "capture host" in payload["error"]
    assert len(m5.read_ledger(ledger)) == 1


def test_m5_disqualifies_host_only_tests_and_hash_pinned_scripts_without_counting(fx, tmp_path):
    base = fx.commit(fx.base, {**HOST_TESTS, QUIET: "param([string]$ExpectedSelfSha256 = '')\n"}, "host tests")
    _run_git(fx.repo, "update-ref", "refs/heads/master", base)
    ledger = tmp_path / "m5.jsonl"
    tests_tip = fx.commit(base, {"tests/test_identity.py": HOST_TESTS["tests/test_identity.py"] + "X = 1\n"},
                          "edit a host-identity test")
    code, payload = _record(fx, tests_tip, _ci(tmp_path, tests_tip), _host(tmp_path, tests_tip), ledger)
    assert code == m5.EXIT_OK and payload["row"]["counted"] is False
    assert ("host_only_test_changed", "tests/test_identity.py") in [
        (d["reason"], d["path"]) for d in payload["row"]["disqualifiers"]]
    import_tip = fx.commit(base, {"src/weather/free.py": 'MODE = "obs2"\n'}, "module a host-only test imports")
    code, payload = _record(fx, import_tip, _ci(tmp_path, import_tip), _host(tmp_path, import_tip), ledger)
    assert ("host_only_test_imports", "src/weather/free.py") in [
        (d["reason"], d["path"]) for d in payload["row"]["disqualifiers"]]
    pinned_tip = fx.commit(base, {QUIET: "param([string]$ExpectedSelfSha256 = '')\n# c\n"}, "merge tool")
    code, payload = _record(fx, pinned_tip, _ci(tmp_path, pinned_tip), _host(tmp_path, pinned_tip), ledger)
    assert ("hash_pinned_script", QUIET) in [(d["reason"], d["path"]) for d in payload["row"]["disqualifiers"]]
    assert m5.progress(m5.read_ledger(ledger))["counted_rows"] == 0


def _row(tip: int, concordant: bool, landed: datetime, counted: bool = True) -> dict:
    return {"tip_sha": f"{tip:040x}", "concordant": concordant, "counted": counted,
            "host": {"landed_at": landed.isoformat()}}


def test_m5_threshold_is_the_later_of_5_concordant_landings_or_14_days_and_discordance_resets():
    t0 = datetime(2026, 10, 7, 3, tzinfo=timezone.utc)
    five_fast = [_row(i, True, t0 + timedelta(days=i)) for i in range(5)]
    assert m5.progress(five_fast, now=t0 + timedelta(days=10))["threshold_met"] is False  # 5 landings, 10 days
    assert m5.progress(five_fast, now=t0 + timedelta(days=14))["threshold_met"] is True
    four_slow = [_row(i, True, t0 + timedelta(days=4 * i)) for i in range(4)]
    assert m5.progress(four_slow, now=t0 + timedelta(days=30))["threshold_met"] is False  # 30 days, 4 landings
    reset = five_fast + [_row(9, False, t0 + timedelta(days=6))]
    state = m5.progress(reset, now=t0 + timedelta(days=30))
    assert (state["concordant_since_reset"], state["discordances"], state["threshold_met"]) == (0, 1, False)
    skipped = five_fast + [_row(10, False, t0 + timedelta(days=6), counted=False)]
    assert m5.progress(skipped, now=t0 + timedelta(days=14))["threshold_met"] is True  # disqualified rows never reset
    assert m5.progress(skipped)["binding"] is False


def test_m5_a_discordant_landing_is_recorded(fx, tmp_path):
    ledger = tmp_path / "m5.jsonl"
    head = fx.commit(fx.base, {"docs/y.md": "y\n"}, "tip the host suite failed")
    code, payload = _record(fx, head, _ci(tmp_path, head), _host(tmp_path, head, outcome="FAIL"), ledger)
    assert code == m5.EXIT_OK and payload["row"]["concordant"] is False and payload["row"]["counted"] is True
    assert payload["progress"]["discordances"] == 1
    sensitive = fx.commit(fx.base, {"docs/v.md": "v\n"}, "roll-sensitive on the host")
    code, payload = _record(fx, sensitive, _ci(tmp_path, sensitive),
                            _host(tmp_path, sensitive, roll="ROLL-SENSITIVE"), ledger)
    assert payload["row"]["applicable"] is False and payload["row"]["counted"] is False
