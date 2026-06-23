"""Retired live analog diagnostics probe."""

from __future__ import annotations

try:
    from .research_harness import retired_stub_main
except ImportError:
    from research_harness import retired_stub_main


RESEARCH_STATUS = "retired"


def main(argv=None) -> int:
    return retired_stub_main(__file__, argv, description="Retired live analog diagnostics probe.")


if __name__ == "__main__":
    raise SystemExit(main())

