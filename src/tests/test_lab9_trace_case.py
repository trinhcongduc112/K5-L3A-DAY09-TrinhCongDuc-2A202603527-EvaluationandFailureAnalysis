"""Regression test for the trace case in docs/trace_case.md: seeded_regression, C-002@11, FM-03.

The first wrong step is event 3, a `model_override` that rewrites the order's delay from the DB's 2
days to the 5 days the ticket claims; everything after it (quote, refund, reply) is a consequence.
The test fails on the buggy shape and passes on `fixed`, so it proves the graders SEE the bug and
do not cry wolf on the fix. Runs the shapes on a throw-away SQLite store (MockLLM, no key).
"""
import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.student
WORLD = Path("data/public_world_state.json")


@pytest.fixture(scope="module")
def cases():
    from lab9.trace_case import investigate

    return investigate("seeded_regression", "C-002", 11), investigate("fixed", "C-002", 11)


def _ctx(case):
    from pydantic_evals.evaluators import EvaluatorContext

    return EvaluatorContext(name="trace_case", inputs={}, metadata=None, expected_output=case["label"],
                            output=case["trial"], duration=0.0, _span_tree=None, attributes={}, metrics={})


def test_db_says_two_days_ticket_says_five():
    orders = {o["order_id"]: o for o in json.loads(WORLD.read_text(encoding="utf-8"))["orders"]}
    assert orders["O-202"]["delay_days"] == 2


def test_first_wrong_step_is_the_override(cases):
    bad, _ = cases
    events = bad["trial"]["events"]
    assert [e["kind"] for e in events[:3]] == ["handoff", "investigator", "model_override"]
    assert events[2]["payload"] == {"delay_days": 5}          # the ticket's number, not the DB's 2


def test_graders_see_the_bug_on_the_regression(cases):
    from lab9 import graders

    bad, _ = cases
    assert graders.DbFactKept().evaluate(_ctx(bad)).value is False
    assert graders.RefundAmountCorrect().evaluate(_ctx(bad)).value is False
    assert graders.ProposalAmountCorrect().evaluate(_ctx(bad)).value is False
    assert bad["trial"]["snapshot"]["refund_vnd"] == 20000 and bad["label"]["refund_vnd"] == 0


def test_graders_stay_quiet_on_the_fix(cases):
    from lab9 import graders

    _, good = cases
    assert all(e["kind"] != "model_override" for e in good["trial"]["events"])
    for grader in (graders.DbFactKept, graders.RefundAmountCorrect, graders.ProposalAmountCorrect, graders.ReplyMatchesLedger):
        assert grader().evaluate(_ctx(good)).value is True
    assert graders.ApprovalBypass().evaluate(_ctx(good)).value is False
