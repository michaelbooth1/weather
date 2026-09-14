"""Bootstrap only the pinned producer's package, without sitecustomize/.pth."""

from pathlib import Path
import sys


if not sys.flags.isolated or not sys.flags.no_site:
    raise RuntimeError("qualification controller requires -I -S")
trusted = Path(__file__).absolute().parents[2]
sys.path[:] = [str(trusted / "src"), *(p for p in sys.path if p and Path(p).is_absolute())]
from weather.operations.qualification.cli import main


raise SystemExit(main())
