"""Lossless, allowlisted types with public outcome identities preserved."""
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal

from maker_core.contracts import MarketDescriptor, OutcomeView, Unavailable, InfoEvent
from maker_core.evidence.journal import SecretGuard, canonical_bytes
from maker_core.quoting.policy import (
    Book, RewardTerms, ExposureLimit, Portfolio, QuoteLeg, DecisionInputs, Profile, QuoteDecision,
)
from maker_core.replay.bundle import CapturedRecord, Condition
from maker_core.replay.fill_model import Fill
from maker_core.replay.lifecycle import ReplayConfig, State
from maker_core.replay.payloads import Descriptor, Trade, Coverage

TYPES = {cls.__name__: cls for cls in (
    MarketDescriptor, OutcomeView, Unavailable, InfoEvent, Book, RewardTerms,
    ExposureLimit, Portfolio, QuoteLeg, DecisionInputs, Profile, QuoteDecision,
    CapturedRecord, Condition, Fill, ReplayConfig, State, Descriptor, Trade, Coverage,
)}
PUBLIC_FIELDS = {"outcome_tokens": "outcomes", "clob_yes_token_id": "yes_asset",
                 "clob_no_token_id": "no_asset", "clobTokenIds": "assets", "change_key": "change_ref"}


def encode(value):
    if is_dataclass(value):
        name = type(value).__name__
        if TYPES.get(name) is not type(value):
            raise ValueError("unlisted_artifact_type")
        return {"type": name, "fields": {
            "outcomes" if f.name == "outcome_tokens" else f.name: encode(getattr(value, f.name))
            for f in fields(value)}}
    if isinstance(value, Mapping):
        if not all(isinstance(k, str) for k in value):
            raise ValueError("artifact_mapping_identity")
        renamed = [k for k in value if k in PUBLIC_FIELDS]
        if any(PUBLIC_FIELDS[k] in value for k in renamed):
            raise ValueError("ambiguous_public_mapping")
        if renamed:
            return {"type": "public_mapping", "public_fields": sorted(renamed),
                    "fields": {PUBLIC_FIELDS.get(k, k): encode(v) for k, v in value.items()}}
        return {"type": "mapping", "fields": {k: encode(v) for k, v in value.items()}}
    if isinstance(value, (tuple, list)):
        return {"type": "tuple" if isinstance(value, tuple) else "list", "items": [encode(v) for v in value]}
    if isinstance(value, (datetime, date, Decimal)):
        return {"type": type(value).__name__, "value": value.isoformat() if not isinstance(value, Decimal) else str(value)}
    if value is None or type(value) in (str, int, float, bool):
        canonical_bytes(value)
        return value
    raise ValueError("unlisted_artifact_value")


def decode(value):
    if not isinstance(value, dict):
        if value is None or type(value) in (str, int, float, bool):
            return value
        raise ValueError("invalid_artifact")
    name = value["type"]
    if name == "public_mapping" and set(value) == {"type", "fields", "public_fields"}:
        inverse = {PUBLIC_FIELDS[k]: k for k in value["public_fields"]}
        return {inverse.get(k, k): decode(v) for k, v in value["fields"].items()}
    if name in ("datetime", "date", "Decimal") and set(value) == {"type", "value"}:
        return {"datetime": datetime.fromisoformat, "date": date.fromisoformat, "Decimal": Decimal}[name](value["value"])
    if name in ("tuple", "list") and set(value) == {"type", "items"}:
        return (tuple if name == "tuple" else list)(decode(v) for v in value["items"])
    if set(value) != {"type", "fields"}:
        raise ValueError("invalid_artifact_fields")
    if name == "mapping":
        return {k: decode(v) for k, v in value["fields"].items()}
    cls = TYPES[name]
    kwargs = {"outcome_tokens" if k == "outcomes" else k: decode(v) for k, v in value["fields"].items()}
    if set(kwargs) != {f.name for f in fields(cls)}:
        raise ValueError("incomplete_typed_artifact")
    return cls(**kwargs)


def checked(value):
    projection = encode(value)
    if canonical_bytes(SecretGuard().clean(projection)) != canonical_bytes(projection):
        raise ValueError("secret_guard_would_change_artifact")
    if canonical_bytes(encode(decode(projection))) != canonical_bytes(projection):
        raise ValueError("artifact_round_trip")
    return projection
