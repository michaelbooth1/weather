"""Public facade for immutable model release lifecycle operations."""

from weather.operations.release_manifest import (  # noqa: F401
    ARTIFACT_KINDS,
    DEFAULT_RELEASES_ROOT,
    RELEASE_MANIFEST_NAME,
    RELEASE_MANIFEST_SCHEMA_VERSION,
    ReleaseLifecycleError,
    canonical_payload_sha256,
    capture_code_identity,
    capture_runtime_versions,
    create_release,
    load_release_manifest,
    manifest_content_sha256,
    sha256_file,
    validate_release_id,
    verify_release,
)
from weather.operations.release_promotion import (  # noqa: F401
    ACTIVE_POINTER_SCHEMA_VERSION,
    DEFAULT_ACTIVE_POINTER,
    DEFAULT_CANDIDATES_ROOT,
    DEFAULT_ROLLBACK_DRILL,
    MARKET_DAY_BOUNDARY_SCHEMA_VERSION,
    PROMOTION_DECISION_SCHEMA_VERSION,
    ROLLBACK_DRILL_SCHEMA_VERSION,
    assert_candidate_only_output,
    assert_training_output_path,
    load_active_pointer,
    pointer_content_sha256,
    promote_release,
    resolve_active_release,
    rollback_release,
    validate_market_day_boundary,
    validate_promotion_decision,
)
from weather.release_contract import (  # noqa: F401
    SERVING_IDENTITY_BOOTSTRAP_RELEASE_KIND,
)


def main(argv: list[str] | None = None) -> int:
    from weather.operations.release_lifecycle_cli import main as cli_main

    return cli_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
