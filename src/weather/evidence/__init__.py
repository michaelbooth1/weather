"""Data layer v2 evidence host (plan stage S4): PL-1 journal and reader, PL-4 code identity,
PL-5 telemetry, PL-6 supervisor, and the first recorder families.

Owner: ``docs/operations/EVIDENCE_HOST.md``. No capture loop imports this package, so every
module here is roll-free under ``scripts/ops/roll_verdict.ps1``;
``tests/evidence/test_evidence_closure.py`` ratchets that. Importing the package runs no code.
"""
