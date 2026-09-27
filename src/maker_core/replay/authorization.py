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

APPROVED_REGISTRATIONS: dict[str, str] = {}
POLICIES = ("informed-v0", "no_quote", "blind_re1", "clock_only")
DECISION_FIELDS = {"authorization_id", "owner", "protocol_sha256", "addendum_sha256",
                   "signed_at", "scoring_date", "expires_at"}
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


def _verify_decision(doc, reader, decision_log, frozen_protocol, execution_addendum, now):
    attestation = doc.get("owner_decision")
    if (not isinstance(attestation, dict) or set(attestation) != DECISION_FIELDS
            or attestation.get("owner") != doc["owner"]
            or not isinstance(attestation.get("authorization_id"), str)
            or re.fullmatch(r"[A-Za-z0-9_-]{1,80}", attestation["authorization_id"]) is None):
        raise BundleError("invalid_owner_decision")
    for field in ("protocol_sha256", "addendum_sha256"):
        if not isinstance(attestation[field], str) or re.fullmatch(r"[0-9a-f]{64}", attestation[field]) is None:
            raise BundleError("invalid_frozen_document_hash")
    signed, expires = timestamp(attestation["signed_at"]), timestamp(attestation["expires_at"])
    try:
        scoring_date = date.fromisoformat(attestation["scoring_date"])
    except (ValueError, TypeError) as exc:
        raise BundleError("invalid_scoring_date") from exc
    if (scoring_date.isoformat() != attestation["scoring_date"] or not signed <= now < expires
            or signed >= expires or now.astimezone(ZoneInfo("America/Toronto")).date() != scoring_date):
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
            matches.append((fields, source))
    if len(matches) != 1:
        raise BundleError("owner_decision_missing_duplicate_or_superseded")
    fields, source = matches[0]
    if (fields[1] != "APPROVE_MAKER_REPLAY" or fields[0] != signed.date().isoformat()
            or fields[2] != "offline replay only" or fields[4] != "—" or source != attestation):
        raise BundleError("owner_decision_mismatch_or_revoked")
    for path, field in ((frozen_protocol, "protocol_sha256"), (execution_addendum, "addendum_sha256")):
        if sha256(reader.read(path, 65536)) != attestation[field]:
            raise BundleError("frozen_document_hash_mismatch:" + field)


def read_authorization(path, expected_hash, *, decision_log=None, frozen_protocol=None, execution_addendum=None):
    # Fail before any input IO if the requested signature/hash is not enrolled.
    if not path or expected_hash not in APPROVED_REGISTRATIONS:
        raise BundleError("owner_signed_pre_registration_hash_not_approved")
    reader = _Reader(Limits(458752, 1, 5), time.monotonic)
    raw = reader.read(path, 65536)
    if sha256(raw) != expected_hash:
        raise BundleError("pre_registration_hash_mismatch")
    doc = _json(raw)
    if (not isinstance(doc, dict) or doc.get("owner") != APPROVED_REGISTRATIONS[expected_hash]
            or not isinstance(doc.get("hurdles"), dict) or not doc["hurdles"]
            or doc.get("clusters") != ["date", "date_x_market"]
            or doc.get("policies") != list(POLICIES)):
        raise BundleError("invalid_signed_pre_registration")
    _verify_decision(doc, reader, decision_log, frozen_protocol, execution_addendum, _utc_now())
    return doc


def bind_scope(doc, bundles, config, replicates, seed):
    scope = dict(dates=sorted(b.day.isoformat() for b in bundles),
                 markets=sorted({c.market_id for b in bundles for c in b.conditions}),
                 replay_config=plain(config), bootstrap_replicates=replicates, bootstrap_seed=seed,
                 metrics=["modeled_net_k1", "modeled_net_k05"])
    if any(doc.get(key) != value for key, value in scope.items()):
        raise BundleError("pre_registration_scope_mismatch")
