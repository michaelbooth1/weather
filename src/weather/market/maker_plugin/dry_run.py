"""Bounded offline CLI. Use python -B -m weather.market.maker_plugin.dry_run.

-B also prevents interpreter import-cache writes before this entrypoint loads.
The runner owns IO and policy composition; provider adapters remain pure.
"""
import sys

sys.dont_write_bytecode = True

from weather.market.maker_plugin_runner import main


if __name__ == "__main__":
    raise SystemExit(main())
