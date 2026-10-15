"""Evidence host configuration: ``config/evidence_host.json`` plus the settlement station list.

The config owns every per-family number (interval, caps, budgets, station maps). Its whole-file
sha256 is stamped on every journal row as ``config_sha256``.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from weather.paths import config_path, data_path
from weather.schema_families import schema_version

CONFIG_SCHEMA = schema_version("evidence_host_config")
DEFAULT_CONFIG_PATH = config_path("evidence_host.json")
DEFAULT_LOCATIONS_PATH = config_path("locations.json")
DEFAULT_ROOT = data_path("evidence")
MIB = 1024**2


class EvidenceConfigError(ValueError):
    pass


def load_config(path=DEFAULT_CONFIG_PATH) -> tuple[dict, str]:
    raw = Path(path).read_bytes()
    payload = json.loads(raw)
    if payload.get("schema_version") != CONFIG_SCHEMA:
        raise EvidenceConfigError(f"{path}: schema_version must be {CONFIG_SCHEMA}")
    families = payload.get("families")
    if not isinstance(families, dict) or not families:
        raise EvidenceConfigError(f"{path}: no families")
    for family_id, family in families.items():
        for key in ("plan_family", "module", "enabled", "ram_cap_mib", "hour_byte_budget_mib",
                    "request_budget_per_hour", "channels"):
            if key not in family:
                raise EvidenceConfigError(f"{family_id}: missing {key}")
        if int(family["ram_cap_mib"]) <= 0 or float(family["hour_byte_budget_mib"]) <= 0:
            raise EvidenceConfigError(f"{family_id}: caps must be positive")
    return payload, hashlib.sha256(raw).hexdigest()


def load_locations(path=DEFAULT_LOCATIONS_PATH) -> list[dict]:
    payload = json.loads(Path(path).read_bytes())
    return list(payload.get("locations") or [])


def evidence_root(config: dict, repo_root=None) -> Path:
    from weather.paths import REPO_ROOT
    root = Path(config.get("root") or DEFAULT_ROOT)
    return root if root.is_absolute() else Path(repo_root or REPO_ROOT) / root


def declared_caps_bytes(config: dict) -> int:
    """Sum of enabled children's commit caps plus the parent's (the RAM pause rule adds these)."""
    host = config.get("host") or {}
    total = int(host.get("parent_ram_cap_mib", 0)) * MIB
    for family in config["families"].values():
        if family.get("enabled"):
            total += int(family["ram_cap_mib"]) * MIB
    return total
