"""Route production archives through the admitted workstation entrypoints."""
import pytest
from weather.operations import bulk_cold_archive_crypt as bridge
from weather.operations import workstation_cold_archive_stage as stage
from weather.operations import workstation_cold_archive_restore as restore


@pytest.mark.parametrize("module,operation", [(stage, "encrypt"), (restore, "restore")])
def test_production_mode_forwards_exact_tokens(monkeypatch, module, operation):
    seen = []
    monkeypatch.setattr(bridge, "main", lambda argv: seen.append(argv) or 2)
    tokens = ["--production-chunk", "--archive-file", "archive.tar.gz", "--archive-id", "fixture"]
    assert module.main(tokens) == 2
    assert seen == [[operation, *tokens[1:]]]
    assert tokens[0] == "--production-chunk"


@pytest.mark.parametrize("module", [stage, restore])
def test_production_mode_does_not_accept_mirror_authority(module):
    with pytest.raises(SystemExit):
        module.main(["--production-chunk", "--provisional-mirror-copy"])


@pytest.mark.parametrize("module", [stage, restore])
def test_missing_mode_keeps_legacy_refusal(module):
    with pytest.raises(SystemExit):
        module.main([])
