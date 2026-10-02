"""Owner decision-log attestation plus independently reviewed manifest hash pinning.

The signature is a DECISION_LOG row binding both frozen documents. A separate
review pins the execution manifest's raw SHA-256 and owner here. No key ceremony
or caller-supplied signature string substitutes for that review.
No real-data registration has been approved for this fixture-only build.
"""
import time
from datetime import date, datetime, timezone
import re
from zoneinfo import ZoneInfo
from maker_core.evidence.journal import plain
from maker_core.replay.bundle import BundleError, Limits, _Reader, _json, sha256, timestamp
from maker_core.replay.approved_registrations import APPROVED_REGISTRATIONS

POLICIES = ("informed-v0", "no_quote", "blind_re1", "clock_only")
DECISION_FIELDS = {"authorization_id", "owner", "protocol_sha256", "addendum_sha256",
                   "signed_at", "scoring_date", "expires_at"}
# An ID listed here must bind exactly these clarification hashes; any other ID keeps
# the original optional single clarification. Clarification 2 names v2; Clarification 3 names v3.
CLARIFIED_IDS = {"maker-replay-2026-10-15-v2": ("clarification_sha256", "clarification_2_sha256"),
                 "maker-replay-2026-10-15-v3": ("clarification_sha256", "clarification_2_sha256",
                                                "clarification_3_sha256")}
# Production replaces this with the signed Clarification 3's raw-byte SHA-256 after the owner
# signs it. Until then no v3 attestation (always 64 hex characters) can match: v3 fails closed.
CLARIFICATION_3_SHA256 = "fcbcb7d0d2a38777814b6f9d5e8b96c879d069af873c0b32fb4b274506b03eaa"
# Clarification 2's Authorization section: v2 binds the raw-byte SHA-256 of the signed
# registration, addendum, Clarification 1 and Clarification 2 (signed 2026-10-01, bytes at
# a8c0b846b), for the 2026-10-15 scoring date, expiring 2026-11-01 (00:00 Toronto). A row
# binding any other document, date or later expiry is not this authorization.
SIGNED_BINDINGS = {"maker-replay-2026-10-15-v2": dict(
    protocol_sha256="0380212d8e82474281afbed1197161263f794570ec06cf51fec99a3c6c03a6bf",
    addendum_sha256="074a0e56b87770eff9f574232819b5d95ecd7073e450f27adac7bf555a43410b",
    clarification_sha256="37d2fd8e34462a77d6209ee4018e3685bf91a81a93e2cb08df6986985811fa0e",
    clarification_2_sha256="1719fd1ea679cd14501d5b6ddd392fbb9e8d2b086cf6b5a3c0348961824e60f0",
    scoring_date="2026-10-15")}
# Clarification 3's Authorization section: v3 binds v2's four documents plus Clarification 3,
# with v2's scoring date, late-look limit and expiry unchanged.
SIGNED_BINDINGS["maker-replay-2026-10-15-v3"] = dict(SIGNED_BINDINGS["maker-replay-2026-10-15-v2"],
                                                     clarification_3_sha256=CLARIFICATION_3_SHA256)
EXPIRES_NO_LATER_THAN = {name: datetime(2026, 11, 1, 4, tzinfo=timezone.utc)
                         for name in ("maker-replay-2026-10-15-v2", "maker-replay-2026-10-15-v3")}
# Clarification 2: the look may run on any Toronto date from its scoring date to this
# date inclusive, provided no attempt has been reserved; a reservation consumes it.
LATE_LOOK_UNTIL = {name: date(2026, 10, 31) for name in ("maker-replay-2026-10-15-v2", "maker-replay-2026-10-15-v3")}
LOG_HEADER = "| Date | Decision | Scope / expiry | Source | Supersedes |"


def _utc_now():
    return datetime.now(timezone.utc)


def _log_lines(raw):
    """Ignore fenced examples and HTML comments; only an actual table can sign."""
    try:
        text = raw.decode("utf-8")
    except UnicodeError as exc:
        raise BundleError("invalid_decision_log_encoding") from exc
    text = re.sub(r"<!--.*?(?:-->|\Z)", "", text, flags=re.DOTALL)
    fence = None
    lines = []
    for line in text.splitlines():
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if marker:
            value = marker.group(1)
            if fence is None:
                fence = value
            elif value[0] == fence[0] and len(value) >= len(fence):
                fence = None
            lines.append("")  # A fenced block terminates a surrounding table.
        elif fence is None:
            lines.append(line)
    return lines


def _clarification_fields(attestation):
    required = CLARIFIED_IDS.get(attestation.get("authorization_id"))
    if required is not None:
        return set(required)
    return {"clarification_sha256"} & set(attestation)


def scoring_date_allowed(attestation, today, late_look_permitted=False):
    """Scoring date itself, or (listed IDs only) a later date up to the limit while no attempt is reserved."""
    scoring_date = date.fromisoformat(attestation["scoring_date"])
    until = LATE_LOOK_UNTIL.get(attestation["authorization_id"])
    return today == scoring_date or bool(late_look_permitted and until and scoring_date < today <= until)


def _verify_decision(doc, reader, decision_log, frozen_protocol, execution_addendum, now,
                     clarification=None, *, require_scoring_date=True, clarification_2=None,
                     late_look_permitted=False, clarification_3=None):
    attestation = doc.get("owner_decision")
    if (not isinstance(attestation, dict) or not isinstance(attestation.get("authorization_id"), str)
            or set(attestation) != DECISION_FIELDS | _clarification_fields(attestation)
            or attestation.get("owner") != doc["owner"]
            or re.fullmatch(r"[A-Za-z0-9_-]{1,80}", attestation["authorization_id"]) is None):
        raise BundleError("invalid_owner_decision")
    clarifications = sorted(_clarification_fields(attestation))
    for field in ("protocol_sha256", "addendum_sha256", *clarifications):
        if not isinstance(attestation[field], str) or re.fullmatch(r"[0-9a-f]{64}", attestation[field]) is None:
            raise BundleError("invalid_frozen_document_hash")
    pinned = SIGNED_BINDINGS.get(attestation["authorization_id"], {})
    for field, value in pinned.items():
        if attestation[field] != value:
            raise BundleError("signed_binding_mismatch:" + field)
    signed, expires = timestamp(attestation["signed_at"]), timestamp(attestation["expires_at"])
    limit = EXPIRES_NO_LATER_THAN.get(attestation["authorization_id"])
    if limit is not None and expires > limit:
        raise BundleError("owner_decision_expiry_after_signed_limit")
    try:
        scoring_date = date.fromisoformat(attestation["scoring_date"])
    except (ValueError, TypeError) as exc:
        raise BundleError("invalid_scoring_date") from exc
    if (scoring_date.isoformat() != attestation["scoring_date"] or not signed <= now < expires
            or signed >= expires or (require_scoring_date and not scoring_date_allowed(
                attestation, now.astimezone(ZoneInfo("America/Toronto")).date(), late_look_permitted))):
        raise BundleError("owner_decision_time_window")
    if doc.get("signed_at") != attestation["signed_at"]:
        raise BundleError("owner_decision_signed_at_mismatch")
    if not all((decision_log, frozen_protocol, execution_addendum)):
        raise BundleError("owner_decision_paths_required")
    lines = _log_lines(reader.read(decision_log, 262144))
    if lines.count(LOG_HEADER) != 1:
        raise BundleError("invalid_decision_log_table")
    matches = []
    table = lines[lines.index(LOG_HEADER) + 1:]
    for line in table:
        if not line.startswith("|"):
            break
        fields = [field.strip() for field in line.split("|")[1:-1]]
        if len(fields) < 2 or fields[1] not in ("APPROVE_MAKER_REPLAY", "REVOKE_MAKER_REPLAY"):
            continue
        if len(fields) != 5 or not fields[3].startswith("`") or not fields[3].endswith("`"):
            raise BundleError("invalid_decision_log_row")
        source = _json(fields[3][1:-1].encode("utf-8"))
        if not isinstance(source, dict) or "authorization_id" not in source:
            raise BundleError("invalid_decision_log_row")
        if source["authorization_id"] == attestation["authorization_id"]:
            if fields[1] == "REVOKE_MAKER_REPLAY":
                raise BundleError("owner_decision_revoked")
            matches.append((fields, source))
    if len(matches) != 1:
        raise BundleError("owner_decision_missing_duplicate_or_superseded")
    fields, source = matches[0]
    if (fields[1] != "APPROVE_MAKER_REPLAY" or fields[0] != signed.date().isoformat()
            or fields[2] != "offline replay only" or fields[4] != "—" or source != attestation):
        raise BundleError("owner_decision_mismatch_or_revoked")
    documents = [(frozen_protocol, "protocol_sha256"), (execution_addendum, "addendum_sha256")]
    for path, field, name in ((clarification, "clarification_sha256", "clarification"),
                              (clarification_2, "clarification_2_sha256", "clarification_2"),
                              (clarification_3, "clarification_3_sha256", "clarification_3")):
        if field in clarifications:
            if not path:
                raise BundleError(name + "_path_required")
            documents.append((path, field))
        elif path:
            raise BundleError(name + "_not_attested")
    for path, field in documents:
        if sha256(reader.read(path, 65536)) != attestation[field]:
            raise BundleError("frozen_document_hash_mismatch:" + field)


def read_authorization(path, expected_hash, *, decision_log=None, frozen_protocol=None, execution_addendum=None,
                       clarification=None, clarification_2=None, late_look=lambda doc: False, clarification_3=None):
    # Fail before any input IO if the requested signature/hash is not enrolled.
    if not path or expected_hash not in APPROVED_REGISTRATIONS:
        raise BundleError("owner_signed_pre_registration_hash_not_approved")
    reader = _Reader(Limits(8*1024**2+458752, 1, 5), time.monotonic)
    raw = reader.read(path, 8*1024**2)
    if sha256(raw) != expected_hash:
        raise BundleError("pre_registration_hash_mismatch")
    doc = _json(raw)
    if (not isinstance(doc, dict) or doc.get("owner") != APPROVED_REGISTRATIONS[expected_hash]
            or not isinstance(doc.get("hurdles"), dict) or not doc["hurdles"]
            or doc.get("clusters") != ["date", "date_x_market"]
            or doc.get("policies") != list(POLICIES)):
        raise BundleError("invalid_signed_pre_registration")
    _verify_decision(doc, reader, decision_log, frozen_protocol, execution_addendum, _utc_now(), clarification,
                     clarification_2=clarification_2, late_look_permitted=late_look(doc),
                     clarification_3=clarification_3)
    return doc


def bind_scope(doc, bundles, config, replicates, seed):
    quote_bundles = [b for b in bundles if b.day.isoformat() != doc.get("settlement_only_date")]
    scope = dict(dates=sorted(b.day.isoformat() for b in quote_bundles),
                 markets=sorted({c.market_id for b in quote_bundles for c in b.conditions}),
                 replay_config=plain(config), bootstrap_replicates=replicates, bootstrap_seed=seed,
                 metrics=["modeled_net_k1", "modeled_net_k05"])
    if any(doc.get(key) != value for key, value in scope.items()):
        raise BundleError("pre_registration_scope_mismatch")
