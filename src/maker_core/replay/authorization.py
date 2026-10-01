"""Owner-reviewed hash pinning, not self-asserted or cryptographic signatures.

An owner signs the registration through the repository review process. A separate
review pins its exact raw SHA-256 and owner here. The runtime cannot enroll a hash.
No real-data registration has been approved for this fixture-only build.
"""
import time
from maker_core.evidence.journal import plain
from maker_core.replay.bundle import BundleError, Limits, _Reader, _json, sha256, timestamp

APPROVED_REGISTRATIONS: dict[str, str] = {}
POLICIES = ("informed-v0", "no_quote", "blind_re1", "clock_only")


def read_authorization(path, expected_hash):
    # Fail before any input IO if the requested signature/hash is not enrolled.
    if not path or expected_hash not in APPROVED_REGISTRATIONS:
        raise BundleError("owner_signed_pre_registration_hash_not_approved")
    raw = _Reader(Limits(65536, 1, 5), time.monotonic).read(path, 65536)
    if sha256(raw) != expected_hash:
        raise BundleError("pre_registration_hash_mismatch")
    doc = _json(raw)
    if (not isinstance(doc, dict) or doc.get("owner") != APPROVED_REGISTRATIONS[expected_hash]
            or not isinstance(doc.get("signature"), str) or not doc["signature"].strip()
            or not isinstance(doc.get("hurdles"), dict) or not doc["hurdles"]
            or doc.get("clusters") != ["date", "date_x_market"]
            or doc.get("policies") != list(POLICIES)):
        raise BundleError("invalid_signed_pre_registration")
    timestamp(doc.get("signed_at"))
    return doc


def bind_scope(doc, bundles, config, replicates, seed):
    scope = dict(dates=sorted(b.day.isoformat() for b in bundles),
                 markets=sorted({c.market_id for b in bundles for c in b.conditions}),
                 replay_config=plain(config), bootstrap_replicates=replicates, bootstrap_seed=seed,
                 metrics=["modeled_net_k1", "modeled_net_k05"])
    if any(doc.get(key) != value for key, value in scope.items()):
        raise BundleError("pre_registration_scope_mismatch")
