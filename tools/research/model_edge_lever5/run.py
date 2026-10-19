"""Lever 5 driver (outcome-blind; no labels, no market prices).

  python -m tools.research.model_edge_lever5.run census --cache C:\\swarm\\cache --out <new.json>
  python -m tools.research.model_edge_lever5.run replay --out <new.jsonl> [--snapshots-root ...]
      [--market M] [--variants a,b] [--summary-out <new.json>]

``census`` reads the 111h swarm cache (workstation); ``replay`` re-runs the
serving pipeline over captured ``replay_inputs.jsonl`` (where they exist: the
capture host). See ``stage_replay`` and ``census`` for the contracts.
"""
from __future__ import annotations

import argparse
import json
import sys


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in {"census", "replay"}:
        print(__doc__, file=sys.stderr)
        return 2
    command, rest = argv[0], argv[1:]
    if command == "replay":
        from tools.research.model_edge_lever5 import stage_replay

        return stage_replay.main(rest)
    from tools.research.model_edge_lever5 import census

    parser = argparse.ArgumentParser(prog="model_edge_lever5 census")
    parser.add_argument("--cache", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(rest)
    result = census.run(args.cache, args.out)
    print(json.dumps({k: result[k] for k in result if k != "columns_read"}, indent=2,
                     sort_keys=True, default=str)[:6000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
