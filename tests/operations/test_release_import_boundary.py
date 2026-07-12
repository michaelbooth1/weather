import subprocess
import sys


def test_release_artifact_import_does_not_load_pyarrow():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import weather.release_artifacts; "
                "assert not any(name == 'pyarrow' or name.startswith('pyarrow.') "
                "for name in sys.modules), sorted(name for name in sys.modules "
                "if name == 'pyarrow' or name.startswith('pyarrow.'))"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
