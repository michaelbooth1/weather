from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ops" / "status.ps1"


def test_rearmed_one_shot_does_not_reuse_prior_failure_as_current_flag():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "$oneShot -and $ti.NextRunTime" in text
    assert '([datetime]$ti.NextRunTime) -gt (Get-Date)' in text
    assert "is re-armed for" in text
    assert "$ok = $true" in text


def test_running_task_does_not_report_its_stale_last_result_as_current_failure():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert '$st -eq "Running"' in text
    assert "LastTaskResult is a completed-run field" in text
    assert 'if (-not $ok -and $st -eq "Running") { $ok = $true }' in text


def test_stage_a_protected_window_teardown_is_an_expected_task_result():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert '"WeatherDailySettlementPromotionRefresh" = @("0x2", "0x4B")' in text
    assert "kill-on-close Job tore down the delegated child tree" in text
    assert "workload lease is the ownership signal" in text
    assert '$chainTaskResult -eq "0x4B"' in text
    assert "protected-window deadline; durable terminal status verified" in text


def test_capture_alert_flags_only_the_current_local_capture_day():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "$historicalCaptureDay = $alertTime.Date -lt (Get-Date).Date" in text
    assert "-not $historicalCaptureDay -and $ageH -lt 24" in text
    assert "capture alert raised today" in text


def test_disabled_on_demand_success_is_not_an_unexpected_disable():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "$noTriggers = ($null -eq $_.Triggers)" in text
    assert "$onDemandCompleted = ($noTriggers -and $res -eq \"0x0\"" in text
    assert "completed an on-demand run" in text


def test_exact_tip_merge_is_spent_only_when_tip_is_integrated() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "$integratedExactTipMerge = $false" in text
    assert '$actionArguments -like "*quiet_window_merge.ps1*"' in text
    assert '$actionArguments -like "*suite_gated_quiet_merge.ps1*"' in text
    assert "$isQuietMergeAction -and" in text
    assert "-ExpectedTip\\s+([0-9a-f]{40})" in text
    assert "merge-base --is-ancestor $integratedExactTip HEAD" in text
    assert "$integratedExactTipMerge = ($LASTEXITCODE -eq 0)" in text
    assert "retained as spent exact-tip merge evidence" in text
    assert (
        "-not $ok -and $integratedExactTipMerge -and $oneShot -and "
        "-not $ti.NextRunTime"
    ) in text
    assert "but exact tip $integratedExactTip is already in production history" in text


def test_only_active_scheduled_interactive_tasks_count_as_reboot_exposure():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "$scheduledWorkRemains = (-not $noTriggers" in text
    assert '$st -ne "Disabled"' in text
    assert "$scheduledWorkRemains)" in text


def test_status_flags_notify_only_windows_update_policy():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "$windowsUpdateAuOptions -eq 2" in text
    assert "policy-forced to notify-only" in text
    assert "unattended_updates_blocked = ($windowsUpdateAuOptions -eq 2)" in text


def test_operator_held_evidence_refresh_keeps_one_honest_warning():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert '"WeatherEveningEvidenceRefresh"' in text
    assert "$evidenceRefreshHeld = $true" in text
    assert "is operator-held DISABLED" in text


def test_quiet_merge_recovery_interval_cannot_overlap_sensitive_driver():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "$oneShot -and $ti.NextRunTime -and $isQuietMergeAction" in text
    assert "-SettleSeconds\\s+(\\d+)" in text
    assert "-RollbackRecoverySeconds\\s+(\\d+)" in text
    assert "$settleSeconds + 240" in text
    assert "$settleSeconds + $rollbackRecoverySeconds + 60" in text
    assert "[math]::Max($successProtectionSeconds, $rollbackProtectionSeconds)" in text
    assert "$sensitiveDriverNextRun -ge $mergeTask.at" in text
    assert "the driver can publish unverified local master" in text


def test_status_flags_unproven_rollback_recovery_separately() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert '$qw.stage -eq "rollback_recovery_failed"' in text
    assert "rollback recovery is UNPROVEN" in text
    assert '$qw.stage -eq "rolled_back"' in text


def test_settlement_scan_seeks_from_end_instead_of_rescanning_each_ledger():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "weather.operations.settlement_hole_check" in text
    assert "--window-days $windowDays --tail-lines 400 --json" in text
    assert "Get-Content -LiteralPath $ledger -Tail 400" not in text


def test_legacy_unbound_merge_drivers_are_intentionally_held() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert '"WeatherMergeQueueDriver", "WeatherMergeSensitiveDriver", "WeatherSuite0969a"' in text
    assert '$st -ne "Disabled"' in text


def test_temporary_training_hold_requires_an_exact_bounded_reenable() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert 'Get-ScheduledTask -TaskName "WeatherTrainingWindowReenable*"' in text
    assert "$trainingReenableDeadline = $trainingReenableNow.AddHours(30)" in text
    assert '[string]$candidate.TaskPath -ne "\\"' in text
    assert "$candidateActions.Count -ne 1" in text
    assert "$candidateTriggers.Count -ne 1" in text
    assert 'Join-Path $PSHOME "powershell.exe"' in text
    assert "Enable-ScheduledTask -TaskName 'WeatherTrainingWindow'" in text
    assert "Disable-ScheduledTask -TaskName '$([string]$candidate.TaskName)'" in text
    assert '[string]$candidateAction.Arguments -cne $expectedArguments' in text
    assert '$expDisabled += "WeatherTrainingWindow"' in text
    assert "automatic re-enable is armed" in text


def test_optional_chain_readiness_is_safe_for_strict_mode_callers() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert '$chain.PSObject.Properties["production_readiness"]' in text
    assert '$chain.PSObject.Properties["summary"]' in text
    assert '$value.PSObject.Properties["status"]' in text
    assert '$f.PSObject.Properties["result"]' in text
    assert '$fResult.PSObject.Properties["reason"]' in text
    assert '$f.PSObject.Properties["error"]' in text
    assert "$f.result.reason" not in text
    assert "if ($chain -and $chain.production_readiness)" not in text


def test_status_reports_only_an_os_held_heavy_workload_lease() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "Get-WeatherHeavyWorkloadLeaseState" in text
    assert "heavy workload lease active" in text


def test_status_snapshot_fallback_matches_the_twelve_minute_capture_contract() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert '"snapshot_tracker"      = @{ Status = "loop_status.json"; Lock = ".loop_status.json.writer.lock"; MaxAge = 720.0 }' in text
    assert '"market_microstructure" = @{ Status = "clob_loop_status.json"; Lock = ".clob_loop_status.json.writer.lock"; MaxAge = 180.0 }' in text
    assert '"observation_trigger"   = @{ Status = "observation_trigger_status.json"; Lock = ".observation_trigger_status.json.writer.lock"; MaxAge = 180.0 }' in text


def test_status_fails_closed_on_unsynchronized_windows_clock() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert 'ProviderName = "Microsoft-Windows-Time-Service"' in text
    assert "Id = 35, 37" in text
    assert 'Get-Service -Name W32Time' in text
    assert "$clockQueryExit = $LASTEXITCODE" in text
    assert "Last Successful Sync Time:" in text
    assert "[datetime]::TryParse" in text
    assert "$clockLastSync = $liveSync" in text
    assert 'if ($clockQueryExit -ne 0 -or -not $sourceMatch.Success)' in text
    assert 'Leap Indicator:\\s*3' in text
    assert 'Source:\\s*Local CMOS Clock' in text
    assert "system clock is not synchronized" in text
    assert 'Write-Output ("  CLOCK     : {0}"' in text


def test_failed_disabled_one_shot_reports_the_run_not_the_terminal_state() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "$name spent one-shot FAILED $res" in text
    assert "verify its artifact" in text
    assert "(Get-Date).AddHours(-24)" in text


def test_complete_overnight_audit_receipt_replaces_stale_verify_artifact_flag() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert '"*audit_overnight_integration_chain.ps1*"' in text
    assert "-ReportPath\\s+" in text
    assert '"overnight_integration_chain_audit_v1"' in text
    assert "$candidateAuditReceipt.complete -eq $true" in text
    assert "$knownRetainedGapOnly" in text
    assert "complete audit remains BLOCK only for retained execution-tape gaps" in text
    assert "complete audit verdict is BLOCK" in text


def test_status_monitors_execution_tape_only_after_it_is_armed() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert 'Get-ScheduledTask -TaskName "WeatherExecutionTapeSupervisor"' in text
    assert '$executionTapeState.armed = [string]$executionTapeTask.State -ne "Disabled"' in text
    assert '"execution_tape_status.json"' in text
    assert '".execution_tape_status.json.writer.lock"' in text
    assert '"execution_tape_supervisor_status.json"' in text
    assert '$executionAge -le 180' in text
    assert 'public execution-tape evidence integrity is BLOCKED_EVIDENCE_LOSS' in text
    assert 'execution_tape = $executionTapeState' in text
