"""Mutation-test the GATE against stand-ins for variants it has never seen.

The instructor grades with hidden variants and traps, so a gate tuned to the five public variants proves
little. Every bug switch in lab9.variant_agent.BUGS is a failure mode a hidden variant can be built from;
this module builds 64 stand-ins from them and asks your gate to judge each:

    60 harmful   10 failure-mode switches x 3 modes x 2 bases
                   modes : always on | odd seeds only (intermittent) | one seed in five (rare)
                   bases : `fixed` (+no_override) | `ref` (the swarm's own seed % 5 == 0 weakness stays)
     4 harmless  paraphrase / extra_lookup refactors, which must merge

    python -m lab9.stress --spec config/metric_spec_v2.yaml --baseline reports/baseline_v2.json
    python -m lab9.stress ... --only quiet_override        # name filter
    python -m lab9.stress ... --modes odd,rare             # fewer, faster

Exit 1 if a harmless variant is blocked (a false alarm costs real engineering time). A harmful variant that
merges is printed as MISSED, not failed: a regression that leaves every aggregate unchanged (for instance a
`rare` FM-03 bug on the `fixed` base, which only moves the baseline's own 3 failing trials to another seed)
cannot be caught by any gate that compares aggregates. Read those lines; do not loosen or tighten to chase them.
Takes ~5 minutes for all 64 (140 trials each on MockLLM).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from lab8.console import utf8_stdio
from lab8.shapes import SHAPES
from lab9 import gate
from lab9.eval import SPEC, load_spec, run_eval
from lab9.fm_probe import FM_OF_BUG
from lab9.variant_agent import make_shape

MODES = {"always": frozenset(), "odd": frozenset({"intermittent"}), "rare": frozenset({"rare"})}
BASES = {"fixed": frozenset({"no_override"}), "ref": frozenset()}
HARMLESS = {
    "paraphrase": frozenset({"no_override", "paraphrase"}),
    "extra_lookup": frozenset({"no_override", "extra_lookup"}),
    "refactor_keeps_seed55_weakness": frozenset({"paraphrase", "extra_lookup"}),
    "refactor_rare": frozenset({"no_override", "paraphrase", "extra_lookup", "rare"}),
}


def stand_ins() -> dict[str, tuple[frozenset[str], bool]]:
    """name -> (bug switches, harmful?)."""
    out: dict[str, tuple[frozenset[str], bool]] = {}
    for base, base_bugs in BASES.items():
        for bug in FM_OF_BUG:
            for mode, extra in MODES.items():
                out[f"{base}_{bug}_{mode}"] = (base_bugs | {bug} | extra, True)
    for name, bugs in HARMLESS.items():
        out[f"harmless_{name}"] = (bugs, False)
    return out


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.stress")
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--base-spec", help="spec of the baseline commit (ratchet), optional")
    ap.add_argument("--only", help="keep stand-ins whose name contains this text")
    ap.add_argument("--modes", help="comma list of modes to run: always,odd,rare")
    args = ap.parse_args(argv)
    spec = load_spec(Path(args.spec))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    modes = set(args.modes.split(",")) if args.modes else set(MODES)
    chosen = {}
    for name, found in stand_ins().items():
        if args.only and args.only not in name:
            continue
        if not name.startswith("harmless_") and name.rsplit("_", 1)[-1] not in modes:
            continue
        chosen[name] = found
    missed, false_alarms = [], []
    for name, (bugs, harmful) in chosen.items():
        SHAPES.setdefault(name, make_shape(name, bugs))
        blocked, _ = gate.check(run_eval(name, spec), base, spec, base_spec)
        verdict = "block" if blocked else "merge"
        tag = ("ok" if blocked else "MISSED") if harmful else ("FALSE ALARM" if blocked else "ok")
        print(f"  {name:<44} {verdict:<6} {tag:<12} {', '.join(blocked)}", flush=True)
        if harmful and not blocked:
            missed.append(name)
        if not harmful and blocked:
            false_alarms.append(name)
    harmful_n = sum(h for _, h in chosen.values())
    print(f"\nharmful blocked {harmful_n - len(missed)}/{harmful_n} · harmless blocked (false alarms) "
          f"{len(false_alarms)}/{len(chosen) - harmful_n}")
    if missed:
        print("missed: " + ", ".join(missed))
    return 1 if false_alarms else 0


if __name__ == "__main__":
    raise SystemExit(main())
