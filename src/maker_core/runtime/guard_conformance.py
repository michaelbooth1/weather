"""Conformance kit for any maker runtime: once HALT is latched, nothing is placed.

The runtime under test is built from an ``OrderGate`` and a ``GatedPlacement``
and exposes ``step(book)``, one decision cycle that may try to place orders.
Refusals (``GuardRefused``, ``PermissionError``) may propagate or be swallowed.
"""
from maker_core.runtime.guard import ALLOW, HALT, GatedPlacement, GuardRefused


def _step(runtime, book):
    try:
        runtime.step(book)
    except (GuardRefused, PermissionError):
        pass


def check_guard_conformance(make_runtime, *, gate, allow_book, halt_book, cancel_intents, cycles=3):
    """Raise AssertionError on a violation. ``cancel_intents`` is the list the
    gate's fake cancel port appends to; ``allow_book`` must evaluate ALLOW."""
    sent = []
    runtime = make_runtime(gate, GatedPlacement(gate, sent.append))
    assert gate.check(allow_book).action == ALLOW, "fixture book must allow"
    _step(runtime, allow_book)
    assert sent, "runtime never placed under ALLOW; the kit proves nothing"
    placed, intents = len(sent), len(cancel_intents)
    # The wallet read that reveals the HALT reaches the gate (any caller), then
    # the runtime keeps running on both the halting and an innocent-looking book.
    assert gate.check(halt_book).action == HALT, "fixture book must halt"
    _step(runtime, halt_book)
    assert len(sent) == placed, "placed after a HALT decision"
    assert len(cancel_intents) > intents and cancel_intents[-1].trigger == HALT, "HALT without cancel-all intent"
    for _ in range(cycles):
        _step(runtime, allow_book)
    assert len(sent) == placed, "placed after HALT without an owner clear"
    assert gate.check(allow_book).action == HALT, "HALT resumed automatically"
