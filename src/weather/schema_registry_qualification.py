"""Schemas for split qualification; registration never confers adoption authority."""

from weather.schema_registry_types import SchemaSpec


QUALIFICATION_REGISTERED_SCHEMAS = tuple(
    SchemaSpec(name, name + "_v2", "weather.operations.qualification." + owner, "active", description)
    for name, owner, description in (
        ("weather_integration_attempt_manifest", "attempt", "Explicit split qualification attempt with separate host proof and frozen adopted control authority."),
        ("qualification_host_measurement", "host_acceptance", "Reviewed actual native host envelopes and current-input feasibility."),
        ("qualification_current_feasibility", "host_acceptance", "Complete current-corpus throughput and unchanged-generation measurement."),
        ("qualification_s4u_invocation", "host_acceptance", "Native batch-token, process lineage and exact Scheduler instance observations."),
        ("qualification_host_probe", "host_acceptance", "One fixed disposable native host probe result."),
        ("qualification_host_environment", "host_runtime", "Independently reviewed native host tool/runtime and retained wheel bindings."),
        ("qualification_host_phase", "host_session", "Fixed admitted parent phase data; native completion remains required."),
        ("weather_integration_attempt_host_receipt", "host_acceptance", "Separate complete native host proof; never a legacy full suite or standalone merge grant."),
        ("qualification_git_policy", "git_policy", "Frozen local Git interpretation, attributes, empty hooks and exact qualified native LFS tool."),
        ("qualification_control_closure", "frozen", "Exact adopted B source-only execution copy checked against actual Git blobs before deferred launches."),
        ("qualification_audit_preparation", "host_audit", "Strict complete current-input preparation and cumulative read accounting."),
        ("qualification_host_audit_plan", "host", "Pinned fixed three-phase host audit with cumulative byte and absolute elapsed budgets."),
        ("qualification_host_plan", "attempt", "Exact source, scope, native host, local adoption day and measured phase references."),
        ("qualification_audit_current", "host", "Complete final current-generation validation bound to exact staging and computation."),
        ("qualification_audit_pipeline", "host", "One fixed native-contained staging, candidate computation and final input validation chain."),
        ("qualification_audit_computation", "host_audit", "Sealed candidate audit computation preserving complete semantic output; current validation still required."),
        ("qualification_audit_imports", "host_audit", "Actual before/after isolated candidate audit import bytes and computation reference."),
        ("qualification_configuration", "merge_tree", "Frozen generated configuration pair and complete current dependency reference."),
        ("qualification_effective_tree", "merge_tree", "Deterministic reviewed source plus exact generated configuration Git tree."),
        ("qualification_merge_boundary", "merge_session", "Actual guarded primitive source/config/index/parent check with separately proved native completion."),
        ("qualification_terminal_current", "reconciliation", "Read-only exact commit disposition and native current health, without retry or historical proof upgrade."),
        ("weather_integration_attempt_reconciliation_receipt", "reconciliation", "Immutable non-authorizing split terminal observation retaining original evidence and marker bytes."),
        ("qualification_arming_proof", "arming", "Actual offline code/source/environment/configuration proof and latest planned merge expiry."),
        ("qualification_preparation_proof", "arming", "Adopted B verification of copied control closure before registration can reference it."),
        ("qualification_measurement_request", "measurement", "Fixed admitted feasibility request without prior measurement or attempt authority."),
        ("qualification_measurement_observation", "measurement", "Actual candidate/configuration/current-input phase observation awaiting native proof."),
        ("qualification_measurement_result", "measurement", "Native measurement evidence requiring independent review before host planning."),
        ("qualification_planning_request", "planning", "Reviewed fixed configuration or draft preparation inside adopted native admission."),
        ("qualification_planning_result", "planning", "Inert actual Q or constructed B-bound manifest with separate native completion."),
        ("weather_integration_attempt_preparation_receipt", "arming", "Immutable native preparation proof for an inert exact-byte attempt manifest."),
        ("weather_integration_attempt_arming_receipt", "arming", "Create-once native arming authority; separate host and guarded merge proof remain mandatory."),
        ("qualification_dispatch", "workflow", "Independently reviewed producer inputs, native profiles and installer closure."),
        ("qualification_process", "runner", "Native bounded execution and zero-descendant cleanup bound to retained output."),
        ("qualification_process_request", "process", "Trusted-parent native Windows command request, never host authority."),
        ("qualification_dependency_lock", "installation", "Complete exact offline wheel set and installer interpreter binding."),
        ("qualification_policy", "contracts", "Independently approved policy, producer, native verifier and host ceilings."),
        ("qualification_review", "contracts", "Exact candidate/baseline, complete coverage and environment review."),
        ("qualification_source_inventory", "source", "Full tracked Git tree and corresponding raw working bytes."),
        ("qualification_test_inventory", "contracts", "Complete tracked tests subset of the source inventory."),
        ("qualification_artifacts", "contracts", "Independently reviewed external test/runtime artifact identities."),
        ("qualification_runtime_files", "environment", "Complete raw-byte file identities under explicit installation roots."),
        ("qualification_environment", "evidence", "Exact native interpreter, package, wheel and executable identities."),
        ("qualification_source_witness", "evidence", "Before/after isolated source, environment and actual import witness."),
        ("qualification_coverage_plan", "coverage", "Reviewed per-platform ordered chunk and file dispositions."),
        ("qualification_chunk_plan", "coverage", "Bounded exact node IDs, exceptions and native coverage references."),
        ("qualification_collection_rules", "coverage", "Tracked pytest configuration and approved plugin inventory."),
        ("qualification_test_changes", "coverage", "Explicit review of all test/config changes against the baseline."),
        ("qualification_collected_nodes", "evidence", "Bounded ordered native pytest collection segment."),
        ("qualification_collection", "evidence", "Complete native collection, errors and ignored-file accounting."),
        ("qualification_chunk", "coverage", "Native test results corroborated by full event and JUnit bytes."),
        ("qualification_job", "evidence", "Exact source/platform/run attempt, serial chunks and required checks."),
        ("code_qualification", "evidence", "Code evidence graph requiring independent provenance authentication."),
        ("qualification_remote_query", "remote", "Exact current/attempt/jobs/artifact authenticated response pages."),
        ("qualification_import", "authentication", "Sealed importer binding of authenticated remote state and retained bytes."),
        ("qualification_revocations", "authentication", "Adopted local policy, source or certificate revocations."),
        ("qualification_inputs", "inputs", "Complete current-input generation pages and bounded validation interval."),
        ("qualification_input_entries", "inputs", "Ordered staged original-byte identities and explicit optional absences."),
    )
)


QUALIFICATION_REGISTERED_SCHEMAS += tuple(
    SchemaSpec("qualification_bootstrap_probe_" + name, "qualification_bootstrap_probe_" + name + "_v1",
               "weather.operations.qualification.bootstrap_probe", "active", description)
    for name, description in (
        ("envelope", "Directly reviewed fixed first-landing probe request; no acceptance or installation authority."),
        ("observation", "Nine fixed probe observations awaiting native completion and independent review."),
        ("use", "Create-once bootstrap probe claim bound to its actual parent process generation."),
        ("native_result", "Bounded probe child execution and lifetime read accounting; no integration authority."),
        ("result", "Native completed probe observations for review, never a qualification PASS."),
        ("failure", "Retained probe failure that cannot reopen its spent namespace."),
    )
)

QUALIFICATION_REGISTERED_SCHEMAS += tuple(
    SchemaSpec(name, name + "_v1", "weather.operations.qualification.bootstrap_install", "active", description)
    for name, description in (
        ("qualification_bootstrap_install_envelope", "Separate owner-approved K-only first landing with exact evidence, source, configuration and invocation."),
        ("qualification_bootstrap_install_review", "Directly reviewed off-host runs, dependency closure, cumulative diff and rollback."),
        ("qualification_bootstrap_probe_review", "Independent acceptance of the exact completed native fixed-probe observation."),
        ("qualification_bootstrap_install_boundary", "Read-only actual B/K/Q tree check inside the temporary guarded primitive."),
        ("qualification_bootstrap_install_use", "Create-once installation authority claim; no ordinary retry."),
        ("qualification_bootstrap_install_monitor", "Exact native monitor generation between adopted outer containment and guarded primitive."),
        ("qualification_bootstrap_install_quiet_native", "Primitive-local zero-descendant and native accounting proof."),
        ("qualification_bootstrap_install_native_result", "Continuous guarded-roll resource monitor and complete child teardown."),
        ("qualification_bootstrap_install_result", "Acknowledged installation awaiting exact non-running task closeout; never a full-host-suite PASS."),
        ("qualification_bootstrap_install_failure", "Conservative retained failure that may include a committed or published merge."),
        ("qualification_bootstrap_install_close_use", "Create-once exact completed-task closeout claim; partial closeout requires review."),
        ("qualification_bootstrap_installed_root", "Published K/policy identity and revoked bootstrap ID with proved exact task closure."),
    )
)
