from __future__ import annotations

import subprocess

import pytest

from weather.reporting.research.research_path_contract import (
    resolve_output_outside_read_only_roots,
)


def _directory_alias(alias, target) -> None:
    try:
        alias.symlink_to(target, target_is_directory=True)
    except (NotImplementedError, OSError) as symlink_error:
        junction = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(alias), str(target)],
            capture_output=True,
            text=True,
            check=False,
        )
        if junction.returncode != 0:
            pytest.skip(f"directory aliases unavailable: {symlink_error}")


def test_output_contract_requires_an_existing_explicit_root(tmp_path):
    with pytest.raises(ValueError, match="at least one"):
        resolve_output_outside_read_only_roots(tmp_path / "out", read_only_roots=[])
    with pytest.raises(ValueError, match="cannot resolve read-only root"):
        resolve_output_outside_read_only_roots(
            tmp_path / "out", read_only_roots=[tmp_path / "missing"]
        )


def test_output_contract_rejects_direct_and_directory_aliased_targets(tmp_path):
    data_root = tmp_path / "immutable-evidence"
    data_root.mkdir()
    with pytest.raises(ValueError, match="read-only root"):
        resolve_output_outside_read_only_roots(
            data_root / "result.json", read_only_roots=[data_root]
        )

    alias = tmp_path / "scratch-looking-alias"
    _directory_alias(alias, data_root)
    with pytest.raises(ValueError, match="read-only root"):
        resolve_output_outside_read_only_roots(
            alias / "result.json", read_only_roots=[data_root]
        )


def test_output_contract_accepts_real_scratch_target(tmp_path):
    data_root = tmp_path / "immutable-evidence"
    data_root.mkdir()
    target = resolve_output_outside_read_only_roots(
        tmp_path / "scratch" / "result.json", read_only_roots=[data_root]
    )
    assert target == (tmp_path / "scratch" / "result.json").resolve()


def test_output_contract_rejects_exact_or_hardlinked_protected_input(tmp_path):
    data_root = tmp_path / "immutable-evidence"
    data_root.mkdir()
    protected = tmp_path / "sealed-input.json"
    protected.write_text("sealed", encoding="utf-8")

    with pytest.raises(ValueError, match="aliases a protected input"):
        resolve_output_outside_read_only_roots(
            protected,
            read_only_roots=[data_root],
            protected_inputs=[protected],
        )

    hardlink = tmp_path / "scratch-result.json"
    try:
        hardlink.hardlink_to(protected)
    except OSError as exc:
        pytest.skip(f"hard links unavailable: {exc}")
    with pytest.raises(ValueError, match="aliases a protected input"):
        resolve_output_outside_read_only_roots(
            hardlink,
            read_only_roots=[data_root],
            protected_inputs=[protected],
        )
    assert protected.read_text(encoding="utf-8") == "sealed"


def test_output_contract_rejects_unknown_existing_multilink_file(tmp_path):
    data_root = tmp_path / "immutable-evidence"
    data_root.mkdir()
    first = tmp_path / "first.json"
    first.write_text("sealed", encoding="utf-8")
    output = tmp_path / "output.json"
    try:
        output.hardlink_to(first)
    except OSError as exc:
        pytest.skip(f"hard links unavailable: {exc}")

    with pytest.raises(ValueError, match="multiple hard links"):
        resolve_output_outside_read_only_roots(
            output,
            read_only_roots=[data_root],
        )
    assert first.read_text(encoding="utf-8") == "sealed"
