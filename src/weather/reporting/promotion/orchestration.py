"""Implementation slice extracted from src/weather/reporting/promotion_refresh.py."""

from weather.reporting.promotion.report import *  # noqa: F403
from weather.operations.long_job_guard import (
    DEFAULT_LOCK_PATH as DEFAULT_LONG_JOB_LOCK_PATH,
    DEFAULT_STATE_PATH as DEFAULT_LONG_JOB_STATE_PATH,
    long_job_guard,
)
from weather.reporting.serving_gates.runtime_identity_evidence import build_runtime_identity_evidence

# The extracted functions below intentionally resolve globals from the
# previous slice to preserve the original module namespace.

def _serving_gauntlet_args(args, corpus_path):
    return SimpleNamespace(
        corpus=str(corpus_path),
        snapshots_root=args.snapshots_root,
        baseline=args.baseline,
        no_baseline=args.no_baseline,
        forecast_tracker=args.forecast_tracker,
        out=args.serving_gauntlet_report,
        replay_report=args.serving_replay_report,
        tol=args.tol,
        market_tol=args.market_tol,
        min_days=args.min_days,
        min_trust=args.min_trust,
        max_fidelity_l1=args.max_fidelity_l1,
        require_exact_identity=args.require_exact_identity,
        require_all_markets=args.require_all_markets,
    )


def _candidate_args(args, corpus_path, long_job_guard_info=None):
    return SimpleNamespace(
        corpus=str(corpus_path),
        snapshots_root=args.snapshots_root,
        artifact=args.artifact,
        variant_registry=getattr(args, "variant_registry", str(DEFAULT_VARIANT_REGISTRY_PATH)),
        out=args.candidate_report,
        json_out=args.candidate_json,
        replay_report=args.current_replay_report,
        current_tol=args.current_tol,
        market_tol=args.market_tol,
        min_days=args.min_days,
        min_trust=args.min_trust,
        max_fidelity_l1=args.max_fidelity_l1,
        clob_max_age_seconds=args.clob_max_age_seconds,
        casebook=args.casebook,
        candidate_variant_out=getattr(args, "candidate_variant_out", None) or None,
        candidate_variant_id=getattr(args, "candidate_variant_id", None) or None,
        candidate_variant_family=getattr(args, "candidate_variant_family", None) or None,
        candidate_variant_uses_market_features=bool(
            getattr(args, "candidate_variant_uses_market_features", False)
        ),
        candidate_variant_control=bool(getattr(args, "candidate_variant_control", False)),
        disable_candidate_variant_export=bool(getattr(args, "disable_candidate_variant_export", False)),
        microstructure_artifact=args.microstructure_artifact or None,
        microstructure_min_train_rows=args.microstructure_min_train_rows,
        skip_microstructure_overlay=args.skip_microstructure_overlay,
        min_artifact_free_bytes=getattr(args, "min_artifact_free_bytes", 0),
        require_exact_identity=args.require_exact_identity,
        require_all_markets=args.require_all_markets,
        long_job_guard_info=long_job_guard_info,
        fail_on_block=False,
    )


def run_promotion_refresh(args):
    with long_job_guard(
        "promotion_refresh",
        state_path=getattr(args, "long_job_state", DEFAULT_LONG_JOB_STATE_PATH),
        lock_path=getattr(args, "long_job_lock", DEFAULT_LONG_JOB_LOCK_PATH),
        priority=getattr(args, "long_job_priority", "below_normal"),
        enabled=not getattr(args, "disable_long_job_guard", False),
        force_lock=getattr(args, "force_long_job_lock", False),
    ) as guard:
        try:
            _write_started_manifest(args, long_job_guard_info=guard)
            result = _run_promotion_refresh_guarded(args, long_job_guard_info=guard)
            payload, out_path, report_path = result
            _write_complete_manifest(
                args,
                payload,
                out_path,
                report_path,
                long_job_guard_info=guard,
            )
            return result
        except Exception as exc:
            _write_incomplete_manifest(args, exc, long_job_guard_info=guard)
            raise


def _incomplete_manifest_path(args):
    path = Path(getattr(args, "incomplete_manifest", DEFAULT_INCOMPLETE_MANIFEST) or DEFAULT_INCOMPLETE_MANIFEST)
    return path


def _manifest_paths(args):
    return {
        "out": _as_path(getattr(args, "out", None)),
        "report": _as_path(getattr(args, "report", None)),
        "promotion_allowlist_out": _as_path(getattr(args, "promotion_allowlist_out", None)),
        "corpus_out": _as_path(getattr(args, "corpus_out", None)),
        "trust_out": _as_path(getattr(args, "trust_out", None)),
        "candidate_json": _as_path(getattr(args, "candidate_json", None)),
        "candidate_report": _as_path(getattr(args, "candidate_report", None)),
    }


def _write_started_manifest(args, long_job_guard_info=None):
    path = _incomplete_manifest_path(args)
    payload = {
        "schema_version": "promotion_refresh_incomplete_v0.1",
        "status": "STARTED",
        "generated_at_utc": _utc_now(),
        "family_unit": getattr(args, "family_unit", DEFAULT_FAMILY_UNIT),
        "paths": _manifest_paths(args),
        "min_artifact_free_bytes": int(getattr(args, "min_artifact_free_bytes", 0) or 0),
        "long_job_guard": long_job_guard_info or {},
    }
    try:
        return _write_json(
            path,
            payload,
            min_free_bytes=0,
            context="promotion refresh started manifest export",
        )
    except OSError:
        return None


def _write_complete_manifest(args, payload, out_path, report_path, long_job_guard_info=None):
    path = _incomplete_manifest_path(args)
    readiness = payload.get("readiness") or {}
    decisions = payload.get("decisions") or {}
    summary = {
        "readiness_status": readiness.get("status"),
        "promote_count": len(decisions.get("promote_markets") or []),
        "shadow_count": len(decisions.get("shadow_markets") or []),
        "blocked_count": len(decisions.get("blocked_markets") or []),
    }
    manifest = {
        "schema_version": "promotion_refresh_incomplete_v0.1",
        "status": "COMPLETE",
        "generated_at_utc": _utc_now(),
        "family_unit": getattr(args, "family_unit", DEFAULT_FAMILY_UNIT),
        "paths": {
            **_manifest_paths(args),
            "written_out": _as_path(out_path),
            "written_report": _as_path(report_path),
        },
        "summary": summary,
        "min_artifact_free_bytes": int(getattr(args, "min_artifact_free_bytes", 0) or 0),
        "long_job_guard": long_job_guard_info or {},
    }
    try:
        return _write_json(
            path,
            manifest,
            min_free_bytes=0,
            context="promotion refresh completion manifest export",
        )
    except OSError:
        return None


def _write_incomplete_manifest(args, exc, long_job_guard_info=None):
    path = _incomplete_manifest_path(args)
    payload = {
        "schema_version": "promotion_refresh_incomplete_v0.1",
        "status": "INCOMPLETE",
        "generated_at_utc": _utc_now(),
        "error_type": type(exc).__name__,
        "error": str(exc),
        "family_unit": getattr(args, "family_unit", DEFAULT_FAMILY_UNIT),
        "paths": _manifest_paths(args),
        "min_artifact_free_bytes": int(getattr(args, "min_artifact_free_bytes", 0) or 0),
        "long_job_guard": long_job_guard_info or {},
    }
    try:
        return _write_json(
            path,
            payload,
            min_free_bytes=0,
            context="promotion refresh incomplete manifest export",
        )
    except OSError:
        return None


def _run_promotion_refresh_guarded(args, long_job_guard_info=None):
    quality_grades = parse_quality_grades(args.quality_grades)
    manifest = build_promotion_corpus(
        folders=args.folders,
        snapshots_root=args.snapshots_root,
        as_of=args.as_of,
        quality_grades=quality_grades,
        include_reconstructed=args.include_reconstructed,
        allow_unsettled=args.allow_unsettled,
        market_id=None,
        min_snapshots=args.min_snapshots,
    )
    corpus_path = write_manifest(manifest, args.corpus_out)

    trust_rows = score_all_markets(
        root=args.snapshots_root,
        as_of=manifest.get("as_of"),
    )
    trust_path = _write_json(args.trust_out, trust_rows)

    precomputed_candidate_json = getattr(args, "precomputed_candidate_json", None)
    precomputed_candidate = None
    if precomputed_candidate_json:
        candidate_report = load_precomputed_candidate_report(
            precomputed_candidate_json,
            manifest,
        )
        candidate_json_path = precomputed_candidate_json
        candidate_report_path = (
            getattr(args, "precomputed_candidate_report", None)
            or args.candidate_report
        )
        precomputed_candidate = {
            "enabled": True,
            "json_path": _as_path(candidate_json_path),
            "report_path": _as_path(candidate_report_path),
            "corpus_hash": (candidate_report.get("corpus") or {}).get("corpus_hash"),
        }
    else:
        candidate_report = run_pooled_candidate_replay(
            _candidate_args(args, corpus_path, long_job_guard_info=long_job_guard_info)
        )
        candidate_json_path = args.candidate_json
        candidate_report_path = args.candidate_report

    serving_report = None
    if not args.skip_serving_gauntlet:
        serving_report = run_promotion_gauntlet(_serving_gauntlet_args(args, corpus_path))

    family_ids = [spec.id for spec in _family_specs(args.family_unit)]
    candidate_summary = _candidate_summary(
        candidate_report,
        candidate_json_path,
        candidate_report_path,
    )
    serving_summary = _serving_gauntlet_summary(
        serving_report,
        args.serving_gauntlet_report,
        args.serving_replay_report,
    )
    extra_location_transfer = _read_extra_location_transfer_report(
        getattr(args, "extra_location_transfer_report", None)
    )
    hourly_performance = _read_hourly_performance_report(
        getattr(args, "hourly_performance_report", DEFAULT_HOURLY_PERFORMANCE)
    )
    candidate_hourly_performance = _read_candidate_hourly_performance_report(
        getattr(args, "candidate_hourly_performance_report", DEFAULT_CANDIDATE_HOURLY_PERFORMANCE)
    )
    ten_minute_performance = _read_ten_minute_performance_report(
        getattr(args, "ten_minute_performance_report", DEFAULT_TEN_MINUTE_PERFORMANCE)
    )
    candidate_ten_minute_performance = _read_candidate_ten_minute_performance_report(
        getattr(args, "candidate_ten_minute_performance_report", DEFAULT_CANDIDATE_TEN_MINUTE_PERFORMANCE)
    )
    source_family_inventory = _read_source_family_inventory(
        getattr(args, "source_family_inventory", DEFAULT_SOURCE_FAMILY_INVENTORY)
    )
    physical_feature_family_ratchet = _read_physical_feature_family_ratchet(
        getattr(args, "physical_feature_family_ratchet", DEFAULT_PHYSICAL_FEATURE_FAMILY_RATCHET)
    )
    fleet_observability = _read_fleet_observability(
        getattr(args, "fleet_observability_report", DEFAULT_FLEET_OBSERVABILITY)
    )
    settled_day_freshness = _read_settled_day_freshness(
        getattr(args, "settled_day_freshness_report", DEFAULT_SETTLED_DAY_FRESHNESS)
    )
    data_layer_audit = _read_data_layer_audit(
        getattr(args, "data_layer_audit_report", DEFAULT_DATA_LAYER_AUDIT)
    )
    ingest_quality_gate = _read_ingest_quality_gate(
        getattr(args, "ingest_quality_gate_report", DEFAULT_INGEST_QUALITY_GATE)
    )
    daily_learning = _read_daily_learning(
        getattr(args, "daily_learning_report", DEFAULT_DAILY_LEARNING)
    )
    per_location_artifact_quarantine = _read_per_location_artifact_quarantine(
        getattr(
            args,
            "per_location_artifact_quarantine_report",
            DEFAULT_PER_LOCATION_ARTIFACT_QUARANTINE,
        )
    )
    disk_headroom = _disk_headroom(
        getattr(args, "out", DEFAULT_OUT),
        getattr(args, "min_artifact_free_bytes", 0),
    )
    evidence_freshness = build_evidence_freshness_gate(
        settled_day_freshness=settled_day_freshness,
        data_layer_audit=data_layer_audit,
        ingest_quality_gate=ingest_quality_gate,
        fleet_observability=fleet_observability,
        daily_learning=daily_learning,
        disk_headroom=disk_headroom,
    )
    early_hour_promotion_blocker = build_early_hour_promotion_blocker(
        candidate=candidate_summary,
        hourly_performance=hourly_performance,
        candidate_hourly_performance=candidate_hourly_performance,
        ten_minute_performance=ten_minute_performance,
        candidate_ten_minute_performance=candidate_ten_minute_performance,
        fleet_observability=fleet_observability,
        market_tolerance=getattr(args, "market_tol", 0.003),
    )
    source_missingness_location_gate = build_source_missingness_location_gate(
        candidate_summary,
        market_tolerance=getattr(args, "market_tol", 0.003),
    )
    decisions = build_family_decisions(
        manifest,
        trust_rows,
        candidate_report,
        family_unit=args.family_unit,
    )
    generated_at = _utc_now()
    promotion_allowlist = build_promotion_allowlist(
        decisions,
        candidate_summary,
        family_unit=args.family_unit,
        generated_at_utc=generated_at,
        path=getattr(args, "promotion_allowlist_out", DEFAULT_PROMOTION_ALLOWLIST),
    )
    allowlist_path = _write_json(
        getattr(args, "promotion_allowlist_out", DEFAULT_PROMOTION_ALLOWLIST),
        promotion_allowlist,
        min_free_bytes=getattr(args, "min_artifact_free_bytes", 0),
        context="promotion allowlist JSON export",
    )
    runtime_identity_evidence = build_runtime_identity_evidence(
        snapshots_root=args.snapshots_root,
        snapshot_manifest=manifest,
        reconciliation_path=Path(args.out).parent / "runtime_identity_reconciliation.json",
    )
    gap_drivers = _candidate_gap_driver_rows(candidate_summary)
    gap_owner_table = build_gap_owner_table(gap_drivers, decisions)
    claim_lanes = model_skill_claims(candidate_summary, gap_owner_table)
    market_diagnostics = market_skill_diagnostics(candidate_summary, decisions)
    gap_experiment_artifacts = write_gap_experiment_artifacts(
        [*gap_owner_table, *market_diagnostics],
        min_free_bytes=getattr(args, "min_artifact_free_bytes", 0),
    )
    readiness = promotion_readiness(
        candidate_summary,
        serving_summary,
        decisions,
        extra_location_transfer=extra_location_transfer,
        hourly_performance=hourly_performance,
        candidate_hourly_performance=candidate_hourly_performance,
        ten_minute_performance=ten_minute_performance,
        candidate_ten_minute_performance=candidate_ten_minute_performance,
        source_family_inventory=source_family_inventory,
        physical_feature_family_ratchet=physical_feature_family_ratchet,
        fleet_observability=fleet_observability,
        runtime_identity_evidence=runtime_identity_evidence,
        evidence_freshness=evidence_freshness,
        per_location_artifact_quarantine=per_location_artifact_quarantine,
        early_hour_promotion_blocker=early_hour_promotion_blocker,
        source_missingness_location_gate=source_missingness_location_gate,
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at,
        "family_unit": args.family_unit,
        "corpus": _manifest_summary(manifest, corpus_path),
        "trust": _trust_summary(trust_rows, trust_path, family_ids),
        "candidate": candidate_summary,
        "precomputed_candidate": precomputed_candidate or {"enabled": False},
        "serving_gauntlet": serving_summary,
        "decisions": decisions,
        "promotion_allowlist": promotion_allowlist,
        "extra_location_transfer": extra_location_transfer,
        "hourly_performance": hourly_performance,
        "candidate_hourly_performance": candidate_hourly_performance,
        "ten_minute_performance": ten_minute_performance,
        "candidate_ten_minute_performance": candidate_ten_minute_performance,
        "source_family_inventory": source_family_inventory,
        "physical_feature_family_ratchet": physical_feature_family_ratchet,
        "fleet_observability": fleet_observability,
        "settled_day_freshness": settled_day_freshness,
        "data_layer_audit": data_layer_audit,
        "ingest_quality_gate": ingest_quality_gate,
        "daily_learning": daily_learning,
        "per_location_artifact_quarantine": per_location_artifact_quarantine,
        "disk_headroom": disk_headroom,
        "evidence_freshness": evidence_freshness,
        "early_hour_promotion_blocker": early_hour_promotion_blocker,
        "source_missingness_location_gate": source_missingness_location_gate,
        "runtime_identity_evidence": runtime_identity_evidence,
        "readiness": readiness,
        "gap_owner_table": gap_owner_table,
        "gap_experiment_artifacts": gap_experiment_artifacts,
        "market_skill_diagnostics": market_diagnostics,
        "model_skill_claims": claim_lanes,
        "long_job_guard": long_job_guard_info or {},
    }
    out_path = _write_json(
        args.out,
        payload,
        min_free_bytes=getattr(args, "min_artifact_free_bytes", 0),
        context="promotion refresh summary JSON export",
    )
    report_path = write_report(
        args.report,
        payload,
        min_free_bytes=getattr(args, "min_artifact_free_bytes", 0),
    )
    payload["promotion_allowlist"]["path"] = _as_path(allowlist_path)
    return payload, out_path, report_path

# Re-export imported dependency names as well because later slices intentionally
# share the original module global namespace while the public facade remains stable.
__all__ = [name for name in globals() if not name.startswith("__")]

