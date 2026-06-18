"""Retired one-off app patch helper."""

from __future__ import annotations

import argparse


RESEARCH_STATUS = "retired"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Retired one-off app patch helper.")
    parser.parse_args(argv)
    print("fix_app.py is retired. Update app files directly through reviewed source changes.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

