"""Fixed adopted planning child, always inside the admitted native parent."""

from pathlib import Path
import sys

if not sys.flags.isolated or not sys.flags.no_site or not sys.dont_write_bytecode or len(sys.argv) != 3:
    raise RuntimeError("fixed isolated planning arguments required")
trusted = Path(__file__).absolute().parents[2]
sys.path[:] = [str(trusted / "src"), *(entry for entry in sys.path if entry and Path(entry).is_absolute())]
from weather.operations.qualification.planning import run

run(sys.argv[1], sys.argv[2])
