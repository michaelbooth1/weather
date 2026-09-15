"""Fixed isolated first-landing boundary; never imports the candidate."""
from pathlib import Path
import sys

if not sys.flags.isolated or not sys.flags.no_site or not sys.dont_write_bytecode or len(sys.argv) != 3:
    raise RuntimeError("fixed isolated first-landing boundary arguments required")
trusted = Path(__file__).absolute().parents[2]
sys.path[:] = [str(trusted / "src"), *(entry for entry in sys.path if entry and Path(entry).is_absolute())]
from weather.operations.qualification.bootstrap_install import run_boundary

run_boundary(Path(sys.argv[1]), sys.argv[2])
