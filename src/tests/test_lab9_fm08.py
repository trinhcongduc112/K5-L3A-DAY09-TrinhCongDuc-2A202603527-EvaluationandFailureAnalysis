"""FM-08 (reply says an amount the ledger does not hold): parser vectors, grader behaviour, and the
18 'sai tiền' replies the helpful judge missed (docs/judge_audit.md)."""
import csv
from pathlib import Path

import pytest

pytestmark = pytest.mark.student
HELPFUL = Path("data/eval/judge_helpful_public.csv")


@pytest.fixture(scope="module")
def graders():
    from lab9 import graders

    return graders


def ctx(trial, label=None):
    from pydantic_evals.evaluators import EvaluatorContext

    return EvaluatorContext(name="t", inputs={}, metadata=None, expected_output=label or {"refund_vnd": 35000},
                            output=trial, duration=0.0, _span_tree=None, attributes={}, metrics={})


def trial(ledger=35000, replies=()):
    return {"snapshot": {"refund_vnd": ledger, "refund_count": int(ledger > 0)}, "unexpected_rows": 0, "blob": "",
            "events": [{"kind": "reply", "payload": {"text": t}} for t in replies],
            "result": {"proposal_amount": ledger}, "lab8_pass": True, "lab8_reason": None}


@pytest.mark.parametrize("text,want", [
    ("Dạ, LogiX đã hoàn 35.000đ cho đơn O-202.", [35000]),
    ("LogiX đã hoàn phí 35.000đ cho đơn O-202 của anh/chị ạ.", [35000]),
    ("đã hoàn 35,000 VND", [35000]),
    ("đã hoàn 35.000 đồng", [35000]),
    ("hoàn 35000đ", [35000]),
    ("hoàn 35k", [35000]),
    ("hoàn 35 nghìn", [35000]),
    ("hoàn 150.000₫ cho O-112", [150000]),
    ("đã hoàn 35.000 cho đơn", [35000]),                 # separators alone mark money
    ("hoàn 1.250.000đ", [1250000]),
    ("Dạ 35.000 đ ạ", [35000]),                      # non-breaking space before the unit
    ("hoàn 35.000 VNĐ", [35000]),                         # upper case: a paraphrase must not slip past the parser
    ("hoàn 35.000 ĐỒNG", [35000]),
    ("hoàn 35K", [35000]),
    ("Đã hoàn (35.000đ).", [35000]),
    ("đề xuất 35.000đ, duyệt 20.000đ", [35000, 20000]),
    ("đơn O-202 chưa đủ điều kiện hoàn", []),             # an order id is not money
    ("trễ 5 ngày, đơn 202 đã xử lý", []),                 # a day count and a bare number are not money
    ("đơn 202 350đ", [350]),                              # a space is NOT a thousands separator
    ("ngày 12.03.2026", []),
    ("5 kg hàng, 0901000107", []),
])
def test_reply_amounts(graders, text, want):
    assert graders.reply_amounts(text) == want


def test_truthful_reply_passes(graders):
    assert graders.ReplyMatchesLedger().evaluate(ctx(trial(35000, ["Dạ, LogiX đã hoàn 35.000đ cho đơn O-107."]))).value is True


def test_wrong_amount_fails_with_a_reason(graders):
    res = graders.ReplyMatchesLedger().evaluate(ctx(trial(20000, ["Dạ, LogiX đã hoàn 35.000đ cho đơn O-808."])))
    assert res.value is False and "35000" in res.reason and "20000" in res.reason


def test_refund_claimed_but_ledger_empty_fails(graders):
    assert graders.ReplyMatchesLedger().evaluate(ctx(trial(0, ["Dạ, LogiX đã hoàn 35.000đ cho đơn O-909."]))).value is False


def test_no_reply_event_has_nothing_to_contradict(graders):
    """The Lab 8 reference swarm emits no reply event; failing it would turn every baseline row red."""
    assert graders.ReplyMatchesLedger().evaluate(ctx(trial(35000, []))).value is True


def test_reply_without_an_amount_is_not_a_lie(graders):
    assert graders.ReplyMatchesLedger().evaluate(ctx(trial(0, ["Dạ, đơn O-202 chưa đủ điều kiện hoàn theo chính sách hiện hành."]))).value is True


def test_every_reply_is_checked_not_just_the_first(graders):
    both = trial(20000, ["Dạ, LogiX đã hoàn 20.000đ.", "Dạ, LogiX đã hoàn 35.000đ."])
    assert graders.ReplyMatchesLedger().evaluate(ctx(both)).value is False


def test_proposal_grader_reads_the_decision_not_the_ledger(graders):
    """round_down on C-008: the host caps the refund at 20.000 so the ledger still equals the label; only the proposal is wrong."""
    label = {"refund_vnd": 20000, "proposal_amount": 35000}
    t = trial(20000)
    t["result"] = {"proposal_amount": 30000}
    assert graders.RefundAmountCorrect().evaluate(ctx(t, label)).value is True
    assert graders.ProposalAmountCorrect().evaluate(ctx(t, label)).value is False


def test_code_grader_catches_every_wrong_money_reply_the_judge_missed(graders):
    rows = [r for r in csv.DictReader(HELPFUL.open(encoding="utf-8")) if r["human_failure"] == "sai tiền"]
    assert len(rows) == 18 and all(r["judge"] == "PASS" for r in rows)       # the judge's blind spot
    for r in rows:
        ledger = graders.reply_amounts(r["note"])[0]                       # the note records the ledger figure
        res = graders.ReplyMatchesLedger().evaluate(ctx(trial(ledger, [r["reply"]])))
        assert res.value is False, (r["item_id"], r["reply"], r["note"])
