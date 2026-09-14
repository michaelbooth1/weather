"""Byte substitutions and metadata ambiguity in small real dist-info fixtures."""

import base64
import hashlib
from pathlib import Path

import pytest

from weather.operations.qualification import environment as env
from weather.operations.qualification.records import QualificationError


@pytest.fixture
def installation(tmp_path):
    site = tmp_path / "Lib" / "site-packages"
    info = site / "example_dependency-1.2.3.dist-info"
    info.mkdir(parents=True)
    code = b"value = 7\n"
    (site / "example_dependency.py").write_bytes(code)
    (info / "METADATA").write_text("Metadata-Version: 2.1\nName: example-dependency\nVersion: 1.2.3\n", encoding="utf-8")
    encoded = base64.urlsafe_b64encode(hashlib.sha256(code).digest()).decode().rstrip("=")
    (info / "RECORD").write_text(
        f"example_dependency.py,sha256={encoded},{len(code)}\n"
        "example_dependency-1.2.3.dist-info/METADATA,,\n"
        "example_dependency-1.2.3.dist-info/RECORD,,\n", encoding="utf-8")
    return tmp_path, site, info


def test_real_installed_record_binds_code_and_unhashed_metadata(installation):
    root, site, _ = installation
    distributions = env.discover_distributions([site])
    assert set(distributions) == {"example-dependency"}
    manifest = env.installed_distribution(distributions["example-dependency"], root)
    assert len(manifest["files"]) == 3
    assert all(item["sha256"] and item["path"].startswith("Lib/site-packages/") for item in manifest["files"])


def test_installed_same_length_code_rewrite_is_rejected(installation):
    root, site, _ = installation
    distributions = env.discover_distributions([site])
    (site / "example_dependency.py").write_bytes(b"value = 8\n")
    with pytest.raises(QualificationError, match="disagree with RECORD"):
        env.installed_distribution(distributions["example-dependency"], root)


@pytest.mark.parametrize("row", ["example_dependency.py,,\n", "example_dependency.py,sha512=wrong,10\n",
                                "../../../escape.py,,\n", "example_dependency.py,,nan\n"])
def test_ambiguous_or_escaping_record_cannot_qualify(installation, row):
    root, site, info = installation
    with (info / "RECORD").open("a", encoding="utf-8") as handle:
        handle.write(row)
    with pytest.raises((QualificationError, ValueError)):
        env.installed_distribution(env.discover_distributions([site])["example-dependency"], root)


def test_duplicate_metadata_distribution_is_rejected(installation):
    _, site, _ = installation
    extra = site / "example_dependency-8.0.dist-info"
    extra.mkdir()
    (extra / "METADATA").write_text("Name: Example_Dependency\nVersion: 8.0\n", encoding="utf-8")
    with pytest.raises(QualificationError, match="duplicate"):
        env.discover_distributions([site])


def test_wheel_pins_reject_wrong_version_missing_wheel_and_changed_bytes(installation, tmp_path):
    _, site, _ = installation
    distributions = env.discover_distributions([site])
    name = "example_dependency-1.2.3-py3-none-any.whl"
    # The provenance reader hashes retained bytes; installation is a separate
    # reviewed producer step. This fixture does not claim to be an installable wheel.
    (tmp_path / name).write_bytes(b"fixture retained wheel")
    pin = {"name": "example-dependency", "version": "1.2.3", "filename": name,
           "sha256": hashlib.sha256(b"fixture retained wheel").hexdigest(), "size": 22}
    assert env.bind_wheels(distributions, tmp_path, [pin])["example-dependency"]["filename"] == name
    for bad in ({**pin, "version": "1.2.4"}, {**pin, "sha256": "0" * 64}):
        with pytest.raises(QualificationError):
            env.bind_wheels(distributions, tmp_path, [bad])
    with pytest.raises(QualificationError, match="incomplete"):
        env.bind_wheels(distributions, tmp_path, [])


def test_bytecode_is_part_of_complete_installed_identity(installation):
    root, site, _ = installation
    (site / "unbound.pyc").write_bytes(b"cached old code")
    assert "Lib/site-packages/unbound.pyc" in env.enumerate_files(root)
    assert "Lib/site-packages/example_dependency.py" in env.enumerate_files(root)
