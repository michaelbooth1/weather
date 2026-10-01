"""Full trace comparator, ready for separately authorized sanitized journals."""
from maker_core.evidence.journal import canonical_bytes


def compare_journal(result, expected):
    """Compare every event, including terminal actions, without ignoring fields."""
    actual = [{"at": e.at, "condition_id": e.condition_id, "decision": e.decision} for e in result.decisions]
    mismatches = [i for i, (a, b) in enumerate(zip(actual, expected)) if canonical_bytes(a) != canonical_bytes(b)]
    return {"status": "PASS" if not mismatches and len(actual) == len(expected) else "FAIL",
            "actual_events": len(actual), "expected_events": len(expected), "mismatched_indices": mismatches}
