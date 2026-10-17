"""The registration gate for a scored frontier read (item 330 build 3).

A scored read is refused unless all six (up to eight with a decision rule and a toxicity table) of these hold for the preregistration document's bytes:

1. ``SIGNED_PREREGISTRATION_SHA256`` is pinned. Only a reviewed change after the owner signs may set it;
   until then it is None and every scored read is refused.
2. The SHA-256 of the raw bytes equals the pin.
3. The document carries a ``Signed:`` line whose value is neither empty nor ``UNSIGNED``.
4. The document's ``Grid hash:`` line equals ``grid.GRID_HASH``, so a changed grid cannot be scored under
   an old signature.
5. The document's ``Decay digest:`` line equals the digest of the competitor-response model the run uses.
6. The document's ``Fill model:`` line equals the binding of the fill model the run uses
   (``seams.binding``: exact class, version constants and name; never ``.name`` alone).
7. When the caller passes ``decision_rule_digest`` (the frontier CLI's ``score`` always does), the document's
   ``Decision rule digest:`` line equals it (``decision.DecisionRule.digest``).
8. When the caller passes ``toxicity_table_digest`` (the runner's scored mode and the CLI's ``score`` always
   do, and refuse without one), the document's ``Toxicity table:`` line equals it (the build 2
   ``TableFillCostProvider`` digest), so the fill-cost table is not a free parameter of a scored read.

The runner also refuses a scored read over anything but the whole grid and every baseline, so a signature
cannot be spent on a hand-picked subset.

Descriptive reads need no registration. They still pass the date embargo.
"""
from __future__ import annotations

import hashlib
import re

from maker_core.frontier.grid import GRID_HASH

SIGNED_PREREGISTRATION_SHA256: str | None = None
_SIGNED = re.compile(r"^Signed:[ \t]*(.*?)[ \t]*$", re.MULTILINE)
_GRID = re.compile(r"^Grid hash:[ \t]*`?([0-9a-f]{64})`?[ \t]*$", re.MULTILINE)
_DECAY = re.compile(r"^Decay digest:[ \t]*`?([0-9a-f]{64})`?[ \t]*$", re.MULTILINE)
_FILL = re.compile(r"^Fill model:[ \t]*`?([^`\s]+)`?[ \t]*$", re.MULTILINE)
_RULE = re.compile(r"^Decision rule digest:[ \t]*`?([0-9a-f]{64})`?[ \t]*$", re.MULTILINE)
_TOXICITY = re.compile(r"^Toxicity table:[ \t]*`?([0-9a-f]{64})`?[ \t]*$", re.MULTILINE)


class PreregRefused(ValueError):
    """The scored read has no matching signed preregistration."""


def registration_hash(document: bytes) -> str:
    return hashlib.sha256(document).hexdigest()


def verify(document: bytes | None, *, decay_digest: str, fill_model_binding: str,
           decision_rule_digest: str | None = None, toxicity_table_digest: str | None = None) -> str:
    """Return the registration hash, or refuse. There is deliberately no caller-supplied pin."""
    pinned = SIGNED_PREREGISTRATION_SHA256
    if pinned is None:
        raise PreregRefused("no_signed_preregistration")
    if not isinstance(document, bytes):
        raise PreregRefused("registration_document_required")
    sha = registration_hash(document)
    if sha != pinned:
        raise PreregRefused("registration_hash_mismatch")
    text = document.decode("utf-8")
    signatures = _SIGNED.findall(text)
    if len(signatures) != 1 or not signatures[0] or "UNSIGNED" in signatures[0].upper():
        raise PreregRefused("preregistration_unsigned")
    grids = _GRID.findall(text)
    if len(grids) != 1 or grids[0] != GRID_HASH:
        raise PreregRefused("grid_hash_mismatch")
    decays = _DECAY.findall(text)
    if len(decays) != 1 or decays[0] != decay_digest:
        raise PreregRefused("decay_digest_mismatch")
    fills = _FILL.findall(text)
    if len(fills) != 1 or fills[0] != fill_model_binding:
        raise PreregRefused("fill_model_mismatch")
    if decision_rule_digest is not None:
        rules = _RULE.findall(text)
        if len(rules) != 1 or rules[0] != decision_rule_digest:
            raise PreregRefused("decision_rule_digest_mismatch")
    if toxicity_table_digest is not None:
        tables = _TOXICITY.findall(text)
        if len(tables) != 1 or tables[0] != toxicity_table_digest:
            raise PreregRefused("toxicity_table_mismatch")
    return sha
