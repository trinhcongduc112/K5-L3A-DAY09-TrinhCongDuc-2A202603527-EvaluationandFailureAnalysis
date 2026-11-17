"""Crash at every injection point, on every student shape, then resume on the same store.

The host ledger keys one row per claim, so a shape that forwards `crash_at` to
`durability.issue_refund` and lets `InjectedCrash` escape must come back to exactly
one refund and one `refund_committed` audit after the retry. T12 in the public
matrix only covers `after_effect_before_checkpoint`; this covers all three points.
"""

import time

import pytest

from lab8.db import connect, init_store
from lab8.durability import InjectedCrash
from lab8.metrics import trial_pass
from lab8.shapes import SHAPES
from tests.conftest import BY_ID, CLAIMS, WORLD

STUDENT_SHAPES = ["workflow", "single", "orchestrator"]
CRASH_POINTS = ["before_effect", "after_effect_before_checkpoint", "after_checkpoint"]
CLAIM_ID = "C-012"


def _counts(store):
    conn = connect(store)
    try:
        refunds = conn.execute(
            "SELECT COUNT(*) AS n FROM refund_ledger WHERE claim_id = ?", (CLAIM_ID,)
        ).fetchone()["n"]
        audits = conn.execute(
            "SELECT COUNT(*) AS n FROM audit_events WHERE claim_id = ? AND event_type = 'refund_committed'",
            (CLAIM_ID,),
        ).fetchone()["n"]
        return refunds, audits
    finally:
        conn.close()


@pytest.mark.parametrize("point", CRASH_POINTS)
@pytest.mark.parametrize("shape", STUDENT_SHAPES)
def test_crash_then_resume_leaves_exactly_one_refund(tmp_path, shape, point):
    store = tmp_path / f"{shape}-{point}.sqlite"
    init_store(store, WORLD, CLAIMS).close()

    with pytest.raises(InjectedCrash):
        SHAPES[shape](CLAIM_ID, seed=11, store_path=str(store), crash_at=point)

    refunds_after_crash, _ = _counts(store)
    # Before the effect nothing may be written; at the other two points the money is already down once.
    assert refunds_after_crash == (0 if point == "before_effect" else 1)

    started_at = time.time()
    resumed = SHAPES[shape](CLAIM_ID, seed=11, store_path=str(store))
    assert resumed.status == "resolved"

    assert _counts(store) == (1, 1)
    conn = connect(store)
    try:
        passed, reason = trial_pass(resumed.as_dict(), BY_ID[CLAIM_ID]["expected"], conn, started_at=started_at)
    finally:
        conn.close()
    assert passed, reason
