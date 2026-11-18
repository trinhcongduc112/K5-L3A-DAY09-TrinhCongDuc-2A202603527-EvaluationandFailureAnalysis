"""M1 evidence: which public claim does each failure-mode switch break, and where does the trace go wrong?

The public variants only switch on FM-02/03/04/05 (seeded_regression, slice_, flaky_regression).
FM-01/06/07/08 have a switch in lab9.variant_agent.BUGS but no registered variant, so
`lab9.trace_case` cannot show them. This module registers one throw-away shape per switch
(`probe_<bug>` = the clean `fixed` agent + that one bug; nothing in variants.py or lab8/ changes) and replays it.

    python -m lab9.fm_probe --table                              # every switch x every claim, which grader fires
    python -m lab9.fm_probe --bug stale_clause --claim C-006     # one trace, same layout as lab9.trace_case

Reading the table: "step N kind" is the first event that differs from the clean agent on the same
claim@seed, the usual candidate for the first wrong step. "-" means the trace is identical to the clean
one and the damage is only in the ledger or the reply (e.g. quiet_override leaves no event at all).
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

from pydantic_evals.evaluators import EvaluatorContext

from lab8.console import utf8_stdio
from lab8.db import load_json, load_jsonl
from lab8.shapes import SHAPES
from lab9 import trace_case
from lab9.eval import WORLD, load_spec, make_task
from lab9.graders import GRADERS
from lab9.variant_agent import make_shape

# bug switch (lab9.variant_agent.BUGS) -> failure-mode code in docs/failure_taxonomy.md
FM_OF_BUG = {
    "leaky_trace": "FM-01", "ignore_denied": "FM-02", "ticket_trust": "FM-03", "quiet_override": "FM-03",
    "sum_parts": "FM-04", "round_down": "FM-04", "pre_deducted": "FM-05", "stale_clause": "FM-06",
    "sibling_refund": "FM-07", "misreport": "FM-08",
}
CLEAN = "probe_clean"


def register() -> None:
    SHAPES.setdefault(CLEAN, make_shape(CLEAN, {"no_override"}))
    for bug in FM_OF_BUG:
        SHAPES.setdefault(f"probe_{bug}", make_shape(f"probe_{bug}", {"no_override", bug}))


def _ctx(trial: dict[str, Any], label: dict[str, Any]) -> EvaluatorContext:
    return EvaluatorContext(name="probe", inputs={}, metadata=None, expected_output=label, output=trial,
                            duration=0.0, _span_tree=None, attributes={}, metrics={})


def flagged_by(trial: dict[str, Any], label: dict[str, Any]) -> list[str]:
    """Metric ids whose grader says this trial is bad (safety: True is bad; capability: False is bad)."""
    spec = load_spec()
    bad = []
    for m in spec["metrics"]:
        grader = GRADERS.get(m["id"])
        if grader is None:
            continue
        value = grader().evaluate(_ctx(trial, label)).value
        is_safety = m.get("kind") == "safety"
        if (is_safety and value) or (not is_safety and not value):
            bad.append(m["id"])
    return bad


def first_divergence(trial: dict[str, Any], clean: dict[str, Any]) -> str:
    """First event (1-based) whose kind or payload differs from the clean agent's trace."""
    a, b = trial["events"], clean["events"]
    for i, (x, y) in enumerate(zip(a, b), start=1):
        if x.get("kind") != y.get("kind") or json.dumps(x.get("payload"), sort_keys=True) != json.dumps(y.get("payload"), sort_keys=True):
            return f"step {i} {x.get('kind')}"
    if len(a) != len(b):
        longer = a if len(a) > len(b) else b
        return f"step {min(len(a), len(b)) + 1} {longer[min(len(a), len(b))].get('kind')}"
    return "-"


def sweep(seeds: list[int]) -> list[dict[str, Any]]:
    register()
    claims = load_jsonl(Path("data/public_claims.jsonl"))
    labels = {c["claim_id"]: c["expected"] for c in claims}
    world = load_json(WORLD)
    out = []
    with tempfile.TemporaryDirectory(prefix="lab9-probe-", ignore_cleanup_errors=True) as tmp:
        run = {name: make_task(name, world, claims, labels, Path(tmp)) for name in (CLEAN, *(f"probe_{b}" for b in FM_OF_BUG))}
        for bug, fm in FM_OF_BUG.items():
            for c in claims:
                hits, first, graders = 0, "-", set()
                for s in seeds:
                    inputs = {"claim_id": c["claim_id"], "seed": s}
                    trial, clean = run[f"probe_{bug}"](inputs), run[CLEAN](inputs)
                    why = flagged_by(trial, labels[c["claim_id"]])
                    if not trial["lab8_pass"]:
                        why.append("pass_rate")
                    if why:
                        hits += 1
                        graders.update(why)
                        if first == "-":
                            first = first_divergence(trial, clean)
                if hits:
                    out.append({"fm": fm, "bug": bug, "claim": c["claim_id"], "seeds": hits, "of": len(seeds),
                                "graders": sorted(graders), "first": first})
    return out


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.fm_probe")
    ap.add_argument("--table", action="store_true", help="sweep every switch over every public claim")
    ap.add_argument("--bug", choices=sorted(FM_OF_BUG))
    ap.add_argument("--claim")
    ap.add_argument("--seed", type=int, default=11)
    args = ap.parse_args(argv)
    if args.table:
        seeds = load_spec()["seeds"]
        rows = sweep(seeds)
        print(f"{'FM':<6} {'switch':<15} {'claim':<6} {'seeds':<6} {'first divergent step':<24} graders that fire")
        for r in sorted(rows, key=lambda r: (r["fm"], r["bug"], r["claim"])):
            print(f"{r['fm']:<6} {r['bug']:<15} {r['claim']:<6} {r['seeds']}/{r['of']:<4} {r['first']:<24} {', '.join(r['graders'])}")
        by_claim: dict[str, set[str]] = {}
        for r in rows:
            by_claim.setdefault(r["claim"], set()).add(r["fm"])
        print("\nFM exposed per claim (replay): " + "; ".join(f"{c}={sorted(v)}" for c, v in sorted(by_claim.items())))
        return 0
    if not (args.bug and args.claim):
        ap.error("give --table, or --bug and --claim")
    register()
    return trace_case.main(["--shape", f"probe_{args.bug}", "--claim", args.claim, "--seed", str(args.seed)])


if __name__ == "__main__":
    raise SystemExit(main())
