"""Lazy command router for the offline F3 simulator packages (WP-05)."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from decimal import Decimal
from hashlib import sha256
from importlib import import_module, util
import json
from pathlib import Path
import re
import sys


ROUTES: Mapping[str, tuple[str, str]] = {
    "adapter-parity": ("weather.backtesting.f3_inputs", "cli_main"),
    "envelope": ("weather.scoring.response_envelope", "cli_main"),
    "simulate": ("weather.backtesting.f3_sim", "cli_main"),
    "accuracy": ("weather.backtesting.f3_accuracy", "cli_main"),
    "bridge": ("weather.backtesting.f3_accuracy", "cli_main"),
}


def _available(module: str) -> bool:
    if util.find_spec(module) is None:
        print(f"engine module not present on this branch: {module}")
        return False
    return True


def _json_value(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"unsupported policy value: {type(value).__name__}")


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False,
        default=_json_value,
    ).encode("utf-8")


def _policy_from_f2(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="f3_cli policy-from-f2")
    parser.add_argument("--f2-freeze", required=True, type=Path)
    parser.add_argument("--f2-git-sha", required=True)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    if re.fullmatch(r"[0-9a-fA-F]{40}", args.f2_git_sha) is None:
        print("invalid --f2-git-sha: expected 40 hex characters")
        return 4
    if args.out.exists():
        print("refusal: output already exists")
        return 3
    module_name = "weather.market.f3_policy"
    if not _available(module_name):
        return 4
    try:
        receipt_bytes = args.f2_freeze.read_bytes()
        receipt = json.loads(receipt_bytes)
        if not isinstance(receipt, dict) or not isinstance(receipt.get("policy"), dict):
            print("invalid F2 freeze receipt: policy must be an object")
            return 4
        policy = receipt["policy"]
        # F2's Campaign.sha256 uses canonical JSON WITH a terminal LF
        # (mm_stage2_hold.canonical_bytes). Keep that existing identity.
        f2_policy_sha = sha256(_canonical(policy) + b"\n").hexdigest()
        if receipt.get("policy_sha256", f2_policy_sha) != f2_policy_sha:
            print("refusal: F2 policy hash mismatch")
            return 3
        params = import_module(module_name).params_from_f2_policy(
            policy, f2_git_sha=args.f2_git_sha.lower(),
            f2_policy_sha256=f2_policy_sha,
        )
        # WP-01 owns the economic translation and validation. Its F3Params is
        # a dataclass; accepting a mapping also permits a wire-format adapter.
        payload = asdict(params) if is_dataclass(params) else dict(params)
        provenance = dict(payload["f2_source"])
        provenance["freeze_receipt_sha256"] = sha256(receipt_bytes).hexdigest()
        payload["f2_source"] = provenance
        output = _canonical(payload)
        with args.out.open("xb") as stream:
            stream.write(output + b"\n")
    except FileExistsError:
        print("refusal: output already exists")
        return 3
    except (OSError, ValueError, TypeError, KeyError):
        # Never echo receipt content: it may contain fields beyond the policy.
        print("invalid or unavailable policy input/output")
        return 4
    print(f"policy_sha256: {sha256(output).hexdigest()}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["policy-from-f2", *ROUTES])
    if not args or args[0] in {"-h", "--help"}:
        parser.print_help()
        return 0 if args else 4
    command = parser.parse_args(args[:1]).command
    if command == "policy-from-f2":
        return _policy_from_f2(args[1:])
    module_name, function = ROUTES[command]
    if not _available(module_name):
        return 4
    return getattr(import_module(module_name), function)(args)


if __name__ == "__main__":
    raise SystemExit(main())
