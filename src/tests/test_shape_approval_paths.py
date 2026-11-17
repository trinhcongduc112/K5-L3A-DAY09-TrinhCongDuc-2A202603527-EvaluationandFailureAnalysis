"""All student shapes must leave approval enforcement to the host."""

import json

import pytest

from lab8.db import connect
from lab8.shapes import SHAPES


def _add_claim(conn, claim_id, order_id, approval_id):
    conn.execute(
        """
        INSERT INTO claims (claim_id, principal_id, order_id, ticket, parent_secret, raw_headers_json, approval_id)
        VALUES (?, 'P-100', ?, 'test', 'CANARY_SECRET_PARENT_APPROVAL', '{}', ?)
        """,
        (claim_id, order_id, approval_id),
    )


def _add_approval(conn, approval_id, claim_id, status):
    conn.execute(
        """
        INSERT INTO approvals (approval_id, claim_id, approved_vnd, status, expires_at)
        VALUES (?, ?, 35000, ?, '2027-12-31')
        """,
        (approval_id, claim_id, status),
    )


@pytest.mark.parametrize("shape", ["workflow", "single", "orchestrator"])
@pytest.mark.parametrize(
    "claim_id,order_id,approval_id,approval_status,reason",
    [
        ("C-BORROW", "O-808", "A-001", None, "approval_claim_mismatch"),
        ("C-RV", "O-909", "A-RV", "revoked", "approval_revoked"),
        ("C-NOAPP", "O-107", None, None, "missing_approval"),
    ],
)
def test_invalid_approval_is_denied_and_audited(
    public_db, shape, claim_id, order_id, approval_id, approval_status, reason
):
    conn = connect(public_db)
    if approval_status is not None:
        _add_approval(conn, approval_id, claim_id, approval_status)
    _add_claim(conn, claim_id, order_id, approval_id)
    conn.commit()
    conn.close()

    result = SHAPES[shape](claim_id, seed=11, store_path=str(public_db))

    conn = connect(public_db)
    ledger_count = conn.execute(
        "SELECT COUNT(*) AS n FROM refund_ledger WHERE claim_id = ?", (claim_id,)
    ).fetchone()["n"]
    denial_rows = conn.execute(
        """
        SELECT details_json FROM audit_events
        WHERE claim_id = ? AND event_type = 'policy_denied'
        """,
        (claim_id,),
    ).fetchall()
    conn.close()

    assert result.status == "denied"
    assert result.proposal_amount == 35000
    assert ledger_count == 0
    assert [json.loads(row["details_json"])["reason"] for row in denial_rows] == [reason]
