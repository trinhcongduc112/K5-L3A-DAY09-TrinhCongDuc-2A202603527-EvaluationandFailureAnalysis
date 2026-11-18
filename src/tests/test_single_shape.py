"""Shape B (single): bounded ReAct reads and host-owned writes."""

import pytest

from lab8.handoff import READONLY_TOOLS
from lab8.runtime import dispatch as real_dispatch
from lab8.shapes.single import run_claim


def test_react_uses_only_bounded_read_tools(public_db, monkeypatch):
    tool_names = []

    def recording_dispatch(conn, budget, name, args, *, worker):
        tool_names.append(name)
        return real_dispatch(conn, budget, name, args, worker=worker)

    monkeypatch.setattr("lab8.runtime.dispatch", recording_dispatch)

    result = run_claim("C-001", seed=11, store_path=str(public_db))

    assert result.status == "resolved"
    assert result.model_calls > 0
    assert 0 < len(tool_names) <= 8
    assert set(tool_names) <= READONLY_TOOLS


@pytest.mark.parametrize("claim_id,seed", [("C-002", 55), ("C-006", 11)])
def test_ticket_claims_cannot_override_structured_order_data(public_db, claim_id, seed):
    result = run_claim(claim_id, seed=seed, store_path=str(public_db))

    assert result.status == "denied"
    assert result.proposal_amount == 0
    assert result.refund_effects == []
