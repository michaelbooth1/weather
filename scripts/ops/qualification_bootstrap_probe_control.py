"""Fixed child of the independently reviewed first-landing probe adapter."""

from pathlib import Path
import sys


if not sys.flags.isolated or not sys.flags.no_site or not sys.dont_write_bytecode or len(sys.argv) != 3:
    raise RuntimeError("fixed isolated bootstrap probe arguments required")
authority = Path(__file__).absolute().parents[2]
sys.path[:] = [str(authority / "src"), *(entry for entry in sys.path if entry and Path(entry).is_absolute())]
from weather.operations.qualification.bootstrap_probe import run

run(sys.argv[1], sys.argv[2])
