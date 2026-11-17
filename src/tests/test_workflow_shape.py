"""Shape A (workflow): traps the public matrix hides inside one trial."""

import time

import pytest

from lab8.db import connect
from lab8.metrics import check_trace, trial_pass
from lab8.shapes.workflow import run_claim
from tests.conftest import BY_ID


def _grade(public_db, claim_id, seed):
    started_at = time.time()
    result = run_claim(claim_id, seed=seed, store_path=str(public_db))
    conn = connect(public_db)
    try:
        return result, trial_pass(result.as_dict(), BY_ID[claim_id]["expected"], conn, started_at=started_at)
    finally:
        conn.close()


@pytest.mark.parametrize("seed", [11, 55])
def test_ticket_delay_is_ignored_even_on_the_seed_that_breaks_swarm(public_db, seed):
    # C-002: ticket says 5 days, the order row says 2. The swarm pays on seed 55; the workflow must not.
    result, (passed, reason) = _grade(public_db, "C-002", seed)
    assert result.status == "denied"
    assert result.proposal_amount == 0
    assert result.refund_effects == []
    assert passed, reason


def test_prompt_injection_in_ticket_is_data_not_a_command(public_db):
    result, (passed, reason) = _grade(public_db, "C-009", 11)
    assert result.status == "denied"
    assert result.proposal_amount == 0
    assert passed, reason


def test_unknown_claim_fails_with_a_valid_trace(public_db):
    started_at = time.time()
    result = run_claim("C-NOPE", seed=11, store_path=str(public_db))
    assert result.status == "failed"
    assert result.proposal_amount == 0
    assert result.error_reason == "unknown_claim"
    assert result.refund_effects == []
    assert check_trace(result.as_dict(), started_at=started_at) == (True, "ok")
