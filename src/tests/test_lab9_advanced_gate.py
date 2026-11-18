"""M5-M7 beyond the public vectors: each test is one way to get a red build green, and the gate must refuse it.
The tricks that are not in lab9.traps (duplicate rows, evaluator_failures on a green run, an edited summary,
a re-rolled bootstrap, ...) are the ones the instructor's hidden traps are likely to use. Run with -k advanced."""
import copy
import math

import pytest

pytestmark = pytest.mark.student
ITEMS, SEEDS = 6, (1, 2, 3)


def make_report(fail=(), slices=None, metrics=None, items=ITEMS, seeds=SEEDS):
    """item i < 3 carries the 'money' slice; `fail` is a set of (item_index, seed) that did not pass."""
    rows = [{"item_id": f"E-{i:03d}", "seed": s, "pass_rate": (i, s) not in set(fail),
             "slices": ["money"] if i < 3 else []} for i in range(items) for s in seeds]
    if slices:
        for r in rows:
            r["slices"] = slices.get(r["item_id"], r["slices"])
    ok = sum(r["pass_rate"] for r in rows) / len(rows)
    return {"manifest": {"eval_set_sha": "x", "items": items, "seeds": list(seeds)}, "rows": rows,
            "metrics": metrics or {"pass_rate": round(ok, 4)}, "evaluator_failures": []}


SPEC = {"eval_set_version": "v2", "bootstrap": {"n_resamples": 1000, "method": "percentile", "rng": 2027, "confidence": 0.95},
        "seeds": list(SEEDS),
        "metrics": [{"id": "pass_rate", "kind": "capability", "grader": "lab8.metrics.trial_pass", "blocking": True,
                     "threshold": {"min": 0.8, "no_significant_drop": True}}],
        "slices": [{"name": "money", "metric": "pass_rate", "min": 0.9, "no_significant_drop": True, "blocking": True}]}


@pytest.fixture
def gate():
    from lab9 import gate

    return gate


@pytest.fixture
def base():
    return make_report()


def test_a_report_is_trusted_against_itself(gate, base):
    assert gate.integrity_check(base, base, SPEC, SPEC) == []


def test_duplicate_rows_padding_a_dropped_failure(gate, base):
    """Drop the failing rows, then pad back to the right count with copies of passing ones."""
    pr = make_report(fail={(0, 1), (0, 2)})
    kept = [r for r in pr["rows"] if r["pass_rate"]]
    pr["rows"] = kept + [copy.deepcopy(kept[0]) for _ in range(len(pr["rows"]) - len(kept))]
    assert len(pr["rows"]) == ITEMS * len(SEEDS)                      # the count alone looks fine
    problems = gate.integrity_check(pr, base, SPEC)
    assert any("more than once" in p for p in problems) and any("set differs" in p for p in problems)


def test_evaluator_failures_on_an_otherwise_green_run(gate, base):
    pr = make_report()
    pr["evaluator_failures"] = ["E-001@2:ReplyMatchesLedger:KeyError"]
    assert any("evaluator failure" in p for p in gate.integrity_check(pr, base, SPEC))


def test_baseline_with_evaluator_failures_is_refused_too(gate):
    bad_base = make_report()
    bad_base["evaluator_failures"] = ["x"]
    assert any("baseline" in p for p in gate.integrity_check(make_report(), bad_base, SPEC))


def test_edited_summary_that_the_rows_do_not_support(gate, base):
    pr = make_report(fail={(0, 1), (1, 1), (2, 1), (3, 2)})
    pr["metrics"]["pass_rate"] = 1.0
    assert any("summary was edited" in p for p in gate.integrity_check(pr, base, SPEC))


def test_nan_and_inf_summary(gate, base):
    for bad in (float("nan"), float("inf")):
        pr = make_report(metrics={"pass_rate": bad})
        assert any("pass_rate" in p for p in gate.integrity_check(pr, base, SPEC))


def test_row_without_a_value_for_a_graded_metric(gate, base):
    pr = make_report()
    pr["rows"][4]["pass_rate"] = None
    assert any("no value" in p for p in gate.integrity_check(pr, base, SPEC))
    del pr["rows"][4]["pass_rate"]
    assert any("no value" in p for p in gate.integrity_check(pr, base, SPEC))


def test_cherry_picked_seeds_and_items(gate, base):
    fewer_seeds = make_report(seeds=(1, 2))
    assert gate.integrity_check(fewer_seeds, base, SPEC)
    fewer_items = make_report(items=5)
    assert gate.integrity_check(fewer_items, base, SPEC)


def test_relabelling_an_item_out_of_a_slice(gate, base):
    pr = make_report(fail={(0, 1), (0, 2), (0, 3)}, slices={"E-000": []})
    assert any("slice tags" in p for p in gate.integrity_check(pr, base, SPEC))


@pytest.mark.parametrize("mutate", [
    lambda s: s["metrics"][0]["threshold"].__setitem__("min", 0.5),                      # floor lowered
    lambda s: s["metrics"][0]["threshold"].pop("min"),                                   # floor removed
    lambda s: s["metrics"][0]["threshold"].pop("no_significant_drop"),                   # CI test dropped
    lambda s: s["metrics"][0].__setitem__("blocking", False),                            # no longer blocking
    lambda s: s["metrics"].clear(),                                                      # metric removed
    lambda s: s["metrics"][0].__setitem__("kind", "system"),                             # redefined
    lambda s: s["slices"][0].__setitem__("min", 0.5),                                    # slice floor lowered
    lambda s: s["slices"][0].pop("no_significant_drop"),                                 # slice CI test dropped
    lambda s: s["slices"][0].__setitem__("blocking", False),                             # slice stops blocking
    lambda s: s["slices"].clear(),                                                       # slice removed
    lambda s: s["slices"][0].__setitem__("metric", "other"),                             # slice measures something else
    lambda s: s["bootstrap"].__setitem__("rng", 7),                                      # re-roll the CI
    lambda s: s["bootstrap"].__setitem__("n_resamples", 10),                             # a noisier CI
    lambda s: s["bootstrap"].__setitem__("confidence", 0.999),                           # a wider CI blocks less
    lambda s: s.__setitem__("seeds", [1]),                                               # fewer trials
])
def test_ratchet_refuses_every_loosening(gate, base, mutate):
    loose = copy.deepcopy(SPEC)
    mutate(loose)
    assert any("ratchet" in p for p in gate.integrity_check(base, base, loose, SPEC))


def test_ratchet_allows_tightening_and_a_new_eval_set_version(gate, base):
    tight = copy.deepcopy(SPEC)
    tight["metrics"][0]["threshold"]["min"] = 0.9
    tight["slices"].append({"name": "extra", "metric": "pass_rate", "min": 0.9, "blocking": True})
    assert gate.integrity_check(base, base, tight, SPEC) == []
    fresh = copy.deepcopy(SPEC)
    fresh["eval_set_version"] = "v3"
    fresh["metrics"][0]["threshold"]["min"] = 0.1
    assert gate.integrity_check(base, base, fresh, SPEC) == []        # a new version starts a new baseline


def test_check_refuses_with_integrity_before_comparing(gate, base):
    pr = make_report(fail={(0, 1)})
    pr["evaluator_failures"] = ["boom"]
    blocked, lines = gate.check(pr, base, SPEC)
    assert blocked == ["integrity"] and any("INTEGRITY" in ln for ln in lines)


def test_slice_floor_blocks_what_the_average_hides(gate, base):
    """6 items x 3 seeds: two failures inside the 3-item slice leave the overall mean at 0.89, above its 0.8 floor."""
    pr = make_report(fail={(0, 1), (1, 2)})
    assert gate.integrity_check(pr, base, SPEC) == []
    blocked, _ = gate.slice_check(pr, base, SPEC)
    assert blocked == ["slice:money/pass_rate"]


def test_slice_ci_blocks_even_above_the_floor(gate, base):
    spec = copy.deepcopy(SPEC)
    spec["slices"][0].pop("min")
    pr = make_report(fail={(i, s) for i in range(3) for s in SEEDS})   # every money item fails every seed
    blocked, lines = gate.slice_check(pr, base, spec)
    assert blocked == ["slice:money/pass_rate"] and "CI" in lines[0]


def test_slice_passes_an_identical_run(gate, base):
    blocked, lines = gate.slice_check(base, base, SPEC)
    assert blocked == [] and lines[0].rstrip().endswith("ok")


def test_an_empty_slice_is_a_failure_not_a_pass(gate, base):
    spec = copy.deepcopy(SPEC)
    spec["slices"].append({"name": "ghost", "metric": "pass_rate", "min": 0.5, "blocking": True})
    blocked, _ = gate.slice_check(base, base, spec)
    assert blocked == ["slice:ghost/pass_rate"]


def test_non_blocking_slice_only_warns(gate, base):
    spec = copy.deepcopy(SPEC)
    spec["slices"][0]["blocking"] = False
    blocked, lines = gate.slice_check(make_report(fail={(0, 1), (1, 2)}), base, spec)
    assert blocked == [] and lines[0].rstrip().endswith("warn")


def test_pass_k_values_are_probabilities_in_order():
    from lab9 import stats

    for n, c in [(5, 0), (5, 1), (5, 3), (5, 5), (10, 7)]:
        vals = [stats.pass_hat_k(n, c, k) for k in range(1, min(n, 5) + 1)]
        assert all(0.0 <= v <= 1.0 for v in vals) and vals == sorted(vals, reverse=True)     # pass^k falls with k
        ats = [stats.pass_at_k(n, c, k) for k in range(1, min(n, 5) + 1)]
        assert ats == sorted(ats) and math.isclose(stats.pass_hat_k(n, c, 1), stats.pass_at_k(n, c, 1))


def test_stress_stand_ins_are_well_formed():
    """lab9.stress builds 64 stand-ins for hidden variants from the real bug switches; each must be a legal shape."""
    from lab9 import stress
    from lab9.variant_agent import BENIGN, make_shape

    found = stress.stand_ins()
    harmful = {n: b for n, (b, h) in found.items() if h}
    harmless = {n: b for n, (b, h) in found.items() if not h}
    assert len(harmful) == 60 and len(harmless) == 4
    for name, bugs in {**harmful, **harmless}.items():
        make_shape(name, bugs)                                      # raises on an unknown switch
    assert all(bugs - BENIGN for bugs in harmful.values())          # every harmful one carries a real bug
    assert all(not (bugs - BENIGN) for bugs in harmless.values())   # no harmless one does
