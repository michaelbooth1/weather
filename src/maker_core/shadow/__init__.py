"""Public-reads-only shadow runner: per-minute would-quote tape and nightly diagnostics.

Domain-neutral. It never imports a venue client: public reads, the wallet book
and fair value are injected by the caller. Every would-quote leg goes through
``maker_core.runtime.guard.OrderGate``; the placement target is a local sink.
Contract: docs/operations/maker-shadow-runner.md.
"""
