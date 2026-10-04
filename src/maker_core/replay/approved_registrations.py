"""Independently reviewed raw execution-manifest SHA-256 -> owner enrollments.

Production fills this only after calibration, the sealed inventory and owner-log
verification. Keeping enrollment separate avoids hashing the manifest into itself.
"""
APPROVED_REGISTRATIONS: dict[str, str] = {}
