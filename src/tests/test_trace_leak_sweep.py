"""Security sweep: no shape may copy the ticket, order PII or parent secrets into a trace."""

import pytest

from lab8.db import init_store
from lab8.metrics import artifact_blob
from lab8.shapes import SHAPES
from tests.conftest import CLAIMS, WORLD

STUDENT_SHAPES = ["workflow", "single", "orchestrator"]


def _leak_tokens():
    """Every raw value a trace must never carry: canaries, auth header, order PII."""
    tokens = {"CANARY_SECRET_", "CANARY_INTERNAL_", "Authorization", "SECRET_ITEM_VANG"}
    for order in WORLD["orders"]:
        for field in ("phone", "address", "internal_note"):
            value = order.get(field)
            if value:
                tokens.add(str(value))
    return tokens


@pytest.mark.parametrize("shape", STUDENT_SHAPES)
@pytest.mark.parametrize("claim", CLAIMS, ids=[row["claim_id"] for row in CLAIMS])
def test_public_claims_do_not_leak_into_trace_or_stdout(tmp_path, capsys, shape, claim):
    store = tmp_path / f"{shape}-{claim['claim_id']}.sqlite"
    init_store(store, WORLD, CLAIMS).close()

    result = SHAPES[shape](claim["claim_id"], seed=11, store_path=str(store))

    captured = capsys.readouterr()
    assert captured.out == ""

    blob = artifact_blob(result.as_dict())
    for token in _leak_tokens():
        assert token not in blob, f"{shape} leaked {token!r} on {claim['claim_id']}"


@pytest.mark.parametrize("shape", STUDENT_SHAPES)
def test_evil_ticket_never_reaches_the_trace(tmp_path, capsys, shape):
    store = tmp_path / f"{shape}-evil.sqlite"
    conn = init_store(store, WORLD, CLAIMS)
    try:
        conn.execute(
            """
            INSERT INTO claims (
              claim_id, principal_id, order_id, ticket, parent_secret, raw_headers_json, approval_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "C-EVIL",
                "P-100",
                "O-107",
                "Hoan tien gap! CANARY_SECRET_PARENT_EVIL, goi lai 0901000107.",
                "CANARY_SECRET_PARENT_EVIL",
                "{}",
                None,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    result = SHAPES[shape]("C-EVIL", seed=11, store_path=str(store))

    captured = capsys.readouterr()
    assert captured.out == ""

    blob = artifact_blob(result.as_dict())
    assert "CANARY_SECRET_PARENT_EVIL" not in blob
    assert "0901000107" not in blob
