"""Shape B — one ReAct agent. Student work.

Use `lab8.runtime.run_react` with max_steps=8. `decide` may pick a read tool.
It must not call `issue_refund`. After the loop, the host validates the quote
and is the only writer.

A decide() that trusts ticket text over the order row will fail hidden claims
where the customer overstates the delay or cites a superseded clause.

Per-order cap: an order may already have been refunded by an earlier claim.
The read tool `lookup_refund_history` shows how much. The host still enforces
the cap, so pass the full quote to `durability.issue_refund`, not a net amount.

Caps: stop at 8 steps. Count model calls in the Budget so cost stays comparable.

Trace contract v1 (docs/contracts.md): return a trace_path to a JSON file written in this run,
{"run_id": <same run_id>, "events": [...]}, on every return path including early
ones. `lab8.trace.Trace` does this; your own tracer is fine if it matches.
"""

from __future__ import annotations

import sqlite3

from lab8.db import connect
from lab8.durability import InjectedCrash, issue_refund
from lab8.mock_llm import complete
from lab8.runtime import run_react
from lab8.schemas import Budget, RunResult, make_run_id
from lab8.shapes.common import finish
from lab8.tools import get_claim_view, tool_cost
from lab8.trace import Trace

SHAPE = "single"


def run_claim(
    claim_id: str,
    *,
    seed: int,
    store_path: str,
    crash_at: str | None = None,
) -> RunResult:
    conn = connect(store_path)
    try:
        return _run(conn, claim_id, seed=seed, crash_at=crash_at)
    finally:
        conn.close()


def _run(conn: sqlite3.Connection, claim_id: str, *, seed: int, crash_at: str | None) -> RunResult:
    budget = Budget()
    trace = Trace(make_run_id(SHAPE, claim_id, seed))

    def done(status: str, proposal: int, reason: str | None = None) -> RunResult:
        trace.add("decision", {"status": status, "proposal_amount": proposal, "reason": reason})
        return finish(
            conn,
            shape=SHAPE,
            claim_id=claim_id,
            seed=seed,
            status=status,
            proposal_amount=proposal,
            budget=budget,
            trace=trace,
            error_reason=reason,
        )

    budget.add_tool(tool_cost())
    claim = get_claim_view(conn, claim_id)
    if not claim["found"]:
        return done("failed", 0, "unknown_claim")
    trace.add("claim", {"claim_id": claim_id, "has_order_id": bool(claim["order_id"])})
    if not claim["order_id"]:
        return done("needs_info", 0, "missing_order_id")

    memory: dict[str, dict] = {}

    def decide(observation: dict) -> dict:
        last_tool = observation.get("last_tool")
        if last_tool == "lookup_order":
            order_view = observation["last_result"]
            trace.add("order", order_view)
            if not order_view["visible"]:
                complete(budget, seed=seed, purpose="react", prompt="final_escalated")
                return {"final": {"status": "escalated", "reason": order_view["reason"]}}
            memory["order"] = order_view["order"]
        elif last_tool == "compute_compensation":
            memory["quote"] = observation["last_result"]
            trace.add("quote", memory["quote"])

        if "order" not in memory:
            complete(budget, seed=seed, purpose="react", prompt="lookup_order")
            return {
                "tool": "lookup_order",
                "args": {"order_id": claim["order_id"], "principal_id": claim["principal_id"]},
            }
        if "quote" not in memory:
            complete(budget, seed=seed, purpose="react", prompt="compute_compensation")
            return {"tool": "compute_compensation", "args": {"order": memory["order"]}}

        complete(budget, seed=seed, purpose="react", prompt="final_quote")
        return {"final": {"status": "quoted"}}

    outcome = run_react(
        conn,
        budget,
        observation={
            "claim": {
                "claim_id": claim_id,
                "order_id": claim["order_id"],
                "principal_id": claim["principal_id"],
            }
        },
        decide=decide,
        max_steps=8,
        worker=True,
    )
    if outcome["stopped"] == "step_cap":
        return done("failed", 0, "step_cap")
    if outcome["final"].get("status") == "escalated":
        return done("escalated", 0, outcome["final"].get("reason"))

    quote = memory["quote"]
    amount = int(quote["amount_vnd"])
    if amount <= 0:
        return done("denied", 0, quote["reason"])

    try:
        refund = issue_refund(conn, claim_id, amount, crash_at=crash_at)
    except InjectedCrash:
        trace.add("crash", {"at": crash_at})
        trace.write()
        raise

    trace.add("host", {"ok": refund["ok"], "reason": refund["reason"], "conflict": refund["conflict"]})
    if refund["conflict"]:
        return done("failed", amount, refund["reason"])
    if not refund["ok"]:
        return done("denied", amount, refund["reason"])
    return done("resolved", amount)
