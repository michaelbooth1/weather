"""Schemas for split qualification; registration never confers adoption authority."""

from weather.schema_registry_types import SchemaSpec


QUALIFICATION_REGISTERED_SCHEMAS = tuple(
    SchemaSpec(name, name + "_v2", "weather.operations.qualification." + owner, "active", description)
    for name, owner, description in (
        ("qualification_control_closure", "frozen", "Exact adopted B source-only execution copy checked against actual Git blobs before deferred launches."),
        ("qualification_audit_preparation", "host_audit", "Strict complete current-input preparation and cumulative read accounting."),
        ("qualification_host_audit_plan", "host", "Pinned fixed three-phase host audit with cumulative byte and absolute elapsed budgets."),
        ("qualification_audit_current", "host", "Complete final current-generation validation bound to exact staging and computation."),
        ("qualification_audit_pipeline", "host", "One fixed native-contained staging, candidate computation and final input validation chain."),
        ("qualification_audit_computation", "host_audit", "Sealed candidate audit computation preserving complete semantic output; current validation still required."),
        ("qualification_audit_imports", "host_audit", "Actual before/after isolated candidate audit import bytes and computation reference."),
        ("qualification_configuration", "merge_tree", "Frozen generated configuration pair and complete current dependency reference."),
        ("qualification_effective_tree", "merge_tree", "Deterministic reviewed source plus exact generated configuration Git tree."),
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
