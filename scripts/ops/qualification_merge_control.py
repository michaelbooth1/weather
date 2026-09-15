"""Fixed baseline import path for actual guarded merge boundary checks."""

from pathlib import Path
import sys


if not sys.flags.isolated or not sys.flags.no_site or not sys.dont_write_bytecode or len(sys.argv) != 3:
    raise RuntimeError("fixed isolated merge-controller arguments required")
trusted = Path(__file__).absolute().parents[2]
sys.path[:] = [str(trusted / "src"), *(entry for entry in sys.path if entry and Path(entry).is_absolute())]
from weather.operations.qualification.merge_session import run_boundary


run_boundary(sys.argv[1], sys.argv[2])
