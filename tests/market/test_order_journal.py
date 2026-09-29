"""Manual order journal: fixture-only reader/CLOB replies, no network or account."""
import ast
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest

from weather.market import order_journal
from weather.market.order_journal import record
from weather.market.order_journal_io import JournalError, WriterLock, read_tail, verify_chain
from weather.market.order_journal_report import build_report, markdown
from weather.market.order_journal_sources import PublicClob, SourceError, check_public
from weather.market.wallet_reader_client import ClientError

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = json.loads((ROOT / "tests/fixtures/manual_order_journal/three_runs.json").read_text(encoding="utf-8"))
IDS = FIXTURE["ids"]
MODULES = ("order_journal.py", "order_journal_io.py", "order_journal_sources.py", "order_journal_report.py",
           "wallet_reader_client.py")


class Response:
    def __init__(self, url, payload):
        self.url, self.raw, self.status = url, json.dumps(payload).encode(), 200

    def read(self, limit):
        return self.raw[:limit]

    def geturl(self):
        return self.url

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class Opener:
    """Serves recorded public replies keyed by path (+ token query for books)."""

    def __init__(self, replies):
        self.replies, self.urls = replies, []

    def open(self, request, timeout):
        url = request.full_url
        assert request.get_method() == "GET" and "Authorization" not in request.headers
        self.urls.append(url)
        path = url.split("clob.polymarket.com", 1)[1]
        key = path if path.startswith("/book") else path.split("?", 1)[0]
        if key not in self.replies:
            raise OSError("not in fixture")
        return Response(url, self.replies[key])


def reader_for(run, calls):
    def read(command, *, since=None, day=None, **_):
        calls.append((command, since, day))
        key = f"rewards:{day}" if command == "rewards" else command
        if key not in run["reader"]:
            raise ClientError("timeout")
        return json.loads(json.dumps(run["reader"][key]))
    return read


def run_all(out, runs=FIXTURE["runs"]):
    results = []
    for run in runs:
        calls, opener = [], Opener(run["public"])
        public = PublicClob(budget=40, deadline_seconds=150, opener=opener)
        results.append((record(out, reader=reader_for(run, calls), public=public, now=run["at"]), calls, opener))
    return results


def test_three_runs_record_orders_fills_markouts_and_settlement(tmp_path):
    results = run_all(tmp_path)
    assert [r[0]["sequence"] for r in results] == [0, 1, 2]
    records, head = verify_chain(tmp_path)
    assert head == results[-1][0]["sha256"]
    first, second, third = records
    assert all(r["scope"] == "owner-discretionary" for r in records)
    assert first["books"][IDS["T1"]]["mid"] == "0.86" and first["books"][IDS["T1"]]["spread"] == "0.02"
    assert first["books"][IDS["T1"]]["bids"][0] == ["0.85", "100"]
    assert first["reward_terms"][IDS["C1"]]["daily_rate"] == "73"
    assert first["reward_terms"][IDS["C2"]]["daily_rate"] == "10"
    assert {v["date"] for v in first["rewards"]} == {"2026-09-29", "2026-09-28"}
    assert [e["event"] for e in first["order_events"]] == ["appeared", "appeared"]

    [fill] = second["fills"]
    assert (fill["order_id"], fill["token_id"], fill["side"], fill["price"], fill["size"]) == (
        IDS["A"], IDS["T1"], "BUY", "0.85", "20")
    assert fill["liquidity_role"] == "maker" and fill["reference_mid"] == "0.86"
    [closed] = [e for e in second["order_events"] if e["event"] == "closed"]
    assert closed["order_id"] == IDS["B"] and closed["unattributed_size"] == "50"

    assert third["fills"] == []  # the overlapping trade page is deduplicated
    marks = {m["horizon"]: m for m in third["markouts"]}
    assert marks["5m"]["pusd"] == "0.2" and marks["5m"]["mark_price"] == "0.86"
    assert marks["30m"]["pusd"] == "-0.4"
    assert marks["settlement"]["pusd"] == "3" and marks["settlement"]["source"] == "clob_market_winner"
    assert third["state"]["pending"] == []
    # The prior-day reward read is hourly, not every five minutes.
    assert [c for c in results[1][1] if c[0] == "rewards"] == [("rewards", None, "2026-09-29")]


def test_report_rewards_markouts_cash_days_and_two_sided_baseline(tmp_path):
    run_all(tmp_path)
    report = build_report(verify_chain(tmp_path)[0])
    markets = {m["condition_id"]: m for m in report["markets"]}
    c1, c2 = markets[IDS["C1"]], markets[IDS["C2"]]
    assert c1["reward_accrued_pusd"] == "2.5" and c1["fills"] == 1
    assert c1["markouts_pusd"] == {"5m": "0.2", "30m": "-0.4", "settlement": "3"}
    assert c1["net_pusd"] == "5.5" and c1["net_status"] == "settled"
    assert c1["two_sided_baseline"]["reward_pusd"] == "7.5"
    assert c1["two_sided_baseline"]["symmetric_fill_pusd"] == "0.4"
    assert c1["two_sided_baseline"]["net_pusd"] == "7.9"
    assert [p["pct"] for p in c1["reward_share_path"]] == ["12.5"]
    assert c2["net_pusd"] == "0.4" and c2["net_status"] == "no_fills"
    # 09-28 earnings predate the journal and stay outside market totals.
    assert report["reward_outside_observation_pusd"] == "5"
    orders = {o["order_id"]: o for o in report["orders"]}
    a = orders[IDS["A"]]
    assert a["reward_accrued_pusd"] == "2.5" and a["reward_allocation"].startswith("size_seconds")
    order_seconds = Decimal("0.85") * 100 * 300 + Decimal("0.85") * 80 * 900
    position_seconds = Decimal("0.85") * 20 * 2200
    assert Decimal(a["cash_days"]) == pytest.approx((order_seconds + position_seconds) / 86400)
    assert report["unobserved_seconds"] == "1200"
    assert "owner-discretionary" in markdown(report)


def test_order_delta_fill_needs_two_trade_readable_runs(tmp_path):
    base = FIXTURE["runs"][0]
    runs = []
    for index, matched in enumerate(("0", "10", "10")):
        run = json.loads(json.dumps(base))
        run["at"] = base["at"] + 300 * index
        run["reader"]["summary"]["open_orders"] = [dict(run["reader"]["summary"]["open_orders"][0], size_matched=matched)]
        runs.append(run)
    run_all(tmp_path, runs)
    records, _ = verify_chain(tmp_path)
    assert [len(r["fills"]) for r in records] == [0, 0, 1]
    fill = records[2]["fills"][0]
    assert fill["source"] == "order_delta" and fill["size"] == "10" and fill["fill_time"] == base["at"] + 300


def test_reader_failure_is_recorded_without_closing_known_orders(tmp_path):
    run_all(tmp_path, FIXTURE["runs"][:1])
    down = dict(FIXTURE["runs"][1], at=FIXTURE["runs"][0]["at"] + 300, reader={})
    [(result, _, opener)] = run_all(tmp_path, [down])
    row = read_tail(tmp_path)[0]
    assert row["open_orders"] is None and row["order_events"] == [] and opener.urls == []
    assert row["errors"]["summary"] == "timeout" and row["errors"]["trades"] == "timeout"
    assert set(row["state"]["orders"]) == {IDS["A"], IDS["B"]}


def test_public_budget_defers_markouts_instead_of_losing_them(tmp_path):
    run_all(tmp_path, FIXTURE["runs"][:2])
    third = FIXTURE["runs"][2]
    public = PublicClob(budget=2, deadline_seconds=150, opener=Opener(third["public"]))
    record(tmp_path, reader=reader_for(third, []), public=public, now=third["at"])
    row = read_tail(tmp_path)[0]
    assert row["markouts"] == [] and "prices_history:" + IDS["T1"] in row["errors"]
    assert row["state"]["pending"][0]["needs"] == ["5m", "30m", "settlement"]


@pytest.mark.parametrize("history_available", [True, False])
def test_markout_gives_up_only_after_a_readable_history(tmp_path, history_available):
    run_all(tmp_path, FIXTURE["runs"][:2])
    late = json.loads(json.dumps(FIXTURE["runs"][2]))
    late["at"] = FIXTURE["ids"]["t0"] + 200 + 1800 + 7 * 3600
    late["public"]["/prices-history"] = {"history": []}
    if not history_available:
        del late["public"]["/prices-history"]
    run_all(tmp_path, [late])
    row = read_tail(tmp_path)[0]
    statuses = {m["horizon"]: m["status"] for m in row["markouts"]}
    if history_available:
        assert statuses == {"5m": "unavailable", "30m": "unavailable", "settlement": "observed"}
    else:
        assert statuses == {"settlement": "observed"}
        assert row["state"]["pending"][0]["needs"] == ["5m", "30m"]


def test_fill_keys_survive_a_long_reader_outage(tmp_path):
    run_all(tmp_path, FIXTURE["runs"][:2])
    outage = dict(FIXTURE["runs"][1], at=FIXTURE["ids"]["t0"] + 5 * 86400, reader={})
    back = dict(FIXTURE["runs"][1], at=FIXTURE["ids"]["t0"] + 5 * 86400 + 300, public=FIXTURE["runs"][1]["public"])
    run_all(tmp_path, [outage, back])
    records, _ = verify_chain(tmp_path)
    assert sum(len(r["fills"]) for r in records) == 1


def test_chain_detects_edit_truncation_and_busy_writer(tmp_path):
    run_all(tmp_path)
    path = next(tmp_path.glob("*.jsonl"))
    raw = path.read_bytes()
    path.write_bytes(raw.replace(b'"cash_pusd":"283.95"', b'"cash_pusd":"999.95"', 1))
    with pytest.raises(JournalError, match="journal_chain_invalid"):
        verify_chain(tmp_path)
    path.write_bytes(raw[:-5])
    with pytest.raises(JournalError, match="journal_tail_truncated"):
        read_tail(tmp_path)
    path.write_bytes(raw)
    with WriterLock(tmp_path):
        with pytest.raises(JournalError, match="journal_writer_busy"):
            run_all(tmp_path, FIXTURE["runs"][:1])


def test_cli_refuses_clock_regression_and_verifies(tmp_path, capsys):
    run_all(tmp_path)
    with pytest.raises(JournalError, match="journal_clock_not_monotonic"):
        run_all(tmp_path, FIXTURE["runs"][:1])
    assert order_journal.main(["verify", "--out", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)["records"] == 3
    report = tmp_path / "report.json"
    assert order_journal.main(["report", "--out", str(tmp_path), "--json", str(report)]) == 0
    assert json.loads(report.read_text(encoding="utf-8"))["scope"] == "owner-discretionary"


@pytest.mark.parametrize("path,params", [
    ("/order", {}), ("/orders", {}), ("/data/orders", {}), ("/book", {"token_id": "x"}),
    ("/book", {"token_id": "1", "extra": "1"}), ("/prices-history", {"market": "1", "startTs": "1"}),
    ("/markets/0x12", {}), ("/rewards/markets/" + "0x" + "1" * 64 + "/x", {}),
])
def test_public_reads_are_an_exact_get_allowlist(path, params):
    with pytest.raises(SourceError, match="public_request_refused"):
        check_public(path, params)


def test_journal_modules_have_no_order_signing_or_credential_path():
    forbidden = ("mm_exchange", "mm_official", "mm_credentials", "py_clob_client", "live_sdk", "load_owner_credentials",
                 "mm_live")
    for name in MODULES[:4]:
        tree = ast.parse((ROOT / "src/weather/market" / name).read_text(encoding="utf-8"))
        imported = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        imported += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
        imported += [a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names]
        assert not [m for m in imported if any(f in m for f in forbidden)], name
        source = (ROOT / "src/weather/market" / name).read_text(encoding="utf-8")
        assert "POST" not in source and "DELETE" not in source and ".env" not in source


def modules_sha256(root):
    lines = [f"src/weather/market/{name}:" + hashlib.sha256((root / "src/weather/market" / name).read_bytes()).hexdigest()
             for name in MODULES]
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


def fixture_repo(tmp_path):
    (tmp_path / "scripts/ops").mkdir(parents=True)
    (tmp_path / "src/weather/market").mkdir(parents=True)
    for name in ("manual_order_journal.ps1", "register_manual_order_journal.ps1"):
        (tmp_path / "scripts/ops" / name).write_bytes((ROOT / "scripts/ops" / name).read_bytes())
    for name in MODULES:
        (tmp_path / "src/weather/market" / name).write_bytes((ROOT / "src/weather/market" / name).read_bytes())
    runner = hashlib.sha256((tmp_path / "scripts/ops/manual_order_journal.ps1").read_bytes()).hexdigest()
    return runner, modules_sha256(tmp_path)


def powershell(source, **env):
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", source],
                            env={**os.environ, **env}, capture_output=True, text=True, timeout=60)
    return result


MOCK_SCHEDULER = r"""
$ErrorActionPreference = 'Stop'
$global:mutations = 0
function New-ScheduledTaskAction { param($Execute,$Argument,$WorkingDirectory)
    $global:action = [pscustomobject]@{Execute=$Execute;Arguments=$Argument;WorkingDirectory=$WorkingDirectory}; $global:action }
function New-ScheduledTaskTrigger { param([switch]$Once,$At,$RepetitionInterval)
    [pscustomobject]@{Repetition=[pscustomobject]@{Interval=('PT{0}M' -f [int]$RepetitionInterval.TotalMinutes)}} }
function New-ScheduledTaskPrincipal { param($UserId,$LogonType,$RunLevel)
    $global:principal = [pscustomobject]@{UserId=$UserId;LogonType=$LogonType;RunLevel=$RunLevel}; $global:principal }
function New-ScheduledTaskSettingsSet { param([switch]$AllowStartIfOnBatteries,[switch]$DontStopIfGoingOnBatteries,
    $ExecutionTimeLimit,$MultipleInstances)
    [pscustomobject]@{ExecutionTimeLimit=('PT{0}M' -f [int]$ExecutionTimeLimit.TotalMinutes);MultipleInstances=$MultipleInstances} }
function Register-ScheduledTask { param($TaskName,$Action,$Trigger,$Principal,$Settings,[switch]$Force,$Description)
    $global:mutations++; $global:trigger = $Trigger; $global:settings = $Settings }
function Unregister-ScheduledTask { param($TaskName,[switch]$Confirm,$ErrorAction) $global:mutations++ }
function Disable-ScheduledTask { param($TaskName,$ErrorAction) $global:mutations++ }
function Get-ScheduledTask { param($TaskName)
    [pscustomobject]@{Actions=@($global:action);Triggers=@($global:trigger);Principal=$global:principal;State='Ready';
        Settings=$global:settings} }
$failure = ''
try { $null = & (Join-Path $env:FIXTURE_ROOT 'scripts\ops\register_manual_order_journal.ps1') -RepoRoot $env:FIXTURE_ROOT `
        -ExpectedRunnerSha256 $env:RUNNER_HASH -ExpectedModulesSha256 $env:MODULES_HASH @(if ($env:WHATIF) { '-WhatIf' }) }
catch { $failure = $_.Exception.Message }
@{mutations=$global:mutations;error=$failure;arguments=$global:action.Arguments} | ConvertTo-Json -Compress
"""


@pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell qualification")
@pytest.mark.parametrize("case", ["valid", "whatif", "wrong_runner", "wrong_modules", "missing"])
def test_registrar_requires_pins_before_mock_scheduler(tmp_path, case):
    runner, modules = fixture_repo(tmp_path)
    if case == "wrong_runner":
        runner = "0" * 64
    if case == "wrong_modules":
        modules = "0" * 64
    if case == "missing":
        runner = ""
    result = powershell(MOCK_SCHEDULER.replace("@(if ($env:WHATIF) { '-WhatIf' })",
                                               "-WhatIf" if case == "whatif" else ""),
                        FIXTURE_ROOT=str(tmp_path), RUNNER_HASH=runner, MODULES_HASH=modules)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    if case == "valid":
        assert payload["mutations"] == 1 and payload["error"] == ""
        assert runner in payload["arguments"] and modules in payload["arguments"]
        assert "-StateRoot" in payload["arguments"]
    else:
        assert payload["mutations"] == 0
        assert bool(payload["error"]) == (case != "whatif")


@pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell qualification")
@pytest.mark.parametrize("case", ["wrong_modules", "matching_pins_no_interpreter"])
def test_runner_refuses_unpinned_source_before_python(tmp_path, case):
    runner, modules = fixture_repo(tmp_path)
    if case == "wrong_modules":
        modules = "0" * 64
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                             str(tmp_path / "scripts/ops/manual_order_journal.ps1"), "-RepoRoot", str(tmp_path),
                             "-ExpectedSelfSha256", runner, "-ExpectedModulesSha256", modules],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 3
    line = json.loads((tmp_path / "data/manual_order_journal/runner.log").read_text(encoding="utf-8-sig").splitlines()[-1])
    expected = "journal modules differ" if case == "wrong_modules" else "project interpreter missing"
    assert line["status"] == "refused" and expected in line["detail"]


@pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell qualification")
def test_runner_records_into_state_root_without_reader_config(tmp_path):
    """Real runner and interpreter; the reader config is absent, so no network read happens."""
    import sys
    state = tmp_path / "state"
    state.mkdir()
    if sys.prefix != sys.base_prefix:
        link, target = state / "venv", Path(sys.prefix)
    else:
        (state / "venv").mkdir()
        link, target = state / "venv" / "Scripts", Path(sys.executable).parent
    subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], check=True, capture_output=True)
    try:
        runner = hashlib.sha256((ROOT / "scripts/ops/manual_order_journal.ps1").read_bytes()).hexdigest()
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                                 str(ROOT / "scripts/ops/manual_order_journal.ps1"), "-RepoRoot", str(ROOT),
                                 "-StateRoot", str(state), "-ExpectedSelfSha256", runner,
                                 "-ExpectedModulesSha256", modules_sha256(ROOT)],
                                capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, result.stdout + result.stderr
        journal = state / "data/manual_order_journal"
        line = json.loads((journal / "runner.log").read_text(encoding="utf-8-sig").splitlines()[-1])
        assert line["status"] == "recorded"
        [row] = verify_chain(journal)[0]
        assert row["errors"]["summary"] == "config" and row["reads"]["public_gets_used"] == 0
    finally:
        os.rmdir(link)
