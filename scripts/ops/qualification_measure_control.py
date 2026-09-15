"""Fixed adopted measurement child; no caller-selected Python command."""

from pathlib import Path
import sys


if not sys.flags.isolated or not sys.flags.no_site or not sys.dont_write_bytecode or len(sys.argv) != 4:
    raise RuntimeError("fixed isolated measurement arguments required")
trusted = Path(__file__).absolute().parents[2]
sys.path[:] = [str(trusted / "src"), *(entry for entry in sys.path if entry and Path(entry).is_absolute())]
from weather.operations.qualification.measurement import run_phase

run_phase(sys.argv[1], sys.argv[2], sys.argv[3])
