"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, aggregate, load_spec, per_item
from lab9.graders import GRADERS


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)
    Also refused (the same family of tricks, found while attacking our own gate):
      - the same (item_id, seed) listed twice, or manifest seeds/items different from the baseline's
      - pr["metrics"] that do not equal what pr["rows"] add up to (a hand-edited summary)
      - NaN/inf or evaluator_failures in the baseline itself: nothing can be compared against it
      - a changed bootstrap setting (rng, resamples, confidence), dropped seeds or pass_k values in
        the spec on the same eval-set version (p-hacking the CI instead of fixing the agent)"""
    problems: list[str] = []
    pr_rows, base_rows = pr.get("rows") or [], base.get("rows") or []
    man, base_man = pr.get("manifest") or {}, base.get("manifest") or {}

    for who, rep in (("PR", pr), ("baseline", base)):
        for k, v in (rep.get("metrics") or {}).items():
            if isinstance(v, float) and not math.isfinite(v):
                problems.append(f"{who} metric {k} is {v}: a crashed grader must not average away")
        if rep.get("evaluator_failures"):
            fails = rep["evaluator_failures"]
            problems.append(f"{who} report has {len(fails)} evaluator failure(s), first: {fails[0]}")

    seeds, items = list(man.get("seeds") or []), man.get("items", 0)
    if len(pr_rows) != items * len(seeds):
        problems.append(f"{len(pr_rows)} rows but the manifest says {items} items x {len(seeds)} seeds = "
                        f"{items * len(seeds)} (dropped or duplicated rows)")
    pairs = [(r.get("item_id"), r.get("seed")) for r in pr_rows]
    dup = sorted(p for p, n in Counter(pairs).items() if n > 1)
    if dup:
        problems.append(f"{len(dup)} (item, seed) pair(s) appear more than once, e.g. {dup[0]}")
    base_pairs = {(r.get("item_id"), r.get("seed")) for r in base_rows}
    missing, extra = sorted(base_pairs - set(pairs)), sorted(set(pairs) - base_pairs)
    if missing or extra:
        problems.append(f"(item, seed) set differs from the baseline's: {len(missing)} missing"
                        f"{' e.g. ' + str(missing[0]) if missing else ''}, {len(extra)} extra"
                        f"{' e.g. ' + str(extra[0]) if extra else ''} (cherry-picked rows?)")
    if seeds != list(base_man.get("seeds") or []) or items != base_man.get("items"):
        problems.append(f"manifest seeds/items {seeds}/{items} differ from the baseline's "
                        f"{base_man.get('seeds')}/{base_man.get('items')}")

    graded = [m["id"] for m in spec.get("metrics", []) if m["id"] in GRADERS]
    for mid in graded:
        empty = sum(r.get(mid) is None for r in pr_rows)
        if empty:
            problems.append(f"{empty} row(s) have no value for graded metric {mid}: a crashed grader drops out of the mean")

    base_slices = {}
    for r in base_rows:
        base_slices.setdefault(r.get("item_id"), tuple(sorted(r.get("slices") or [])))
    moved = sorted({r.get("item_id") for r in pr_rows
                    if r.get("item_id") in base_slices and tuple(sorted(r.get("slices") or [])) != base_slices[r.get("item_id")]})
    if moved:
        problems.append(f"slice tags of {len(moved)} item(s) differ from the baseline's, e.g. {moved[0]}: relabelling hides a regression")

    if pr_rows and not problems:        # recompute only from rows we already trust structurally
        try:
            norm = [{**r, "cost": r.get("cost", 0.0), **{m: r.get(m) for m in graded}} for r in pr_rows]
            fresh = aggregate(norm, graded, k_values=spec.get("pass_k", []))
        except (KeyError, TypeError, ValueError) as err:
            problems.append(f"rows are malformed ({err!r}): cannot recompute the metrics")
        else:
            reported = pr.get("metrics") or {}
            for k, want in fresh.items():
                if k not in reported:
                    continue                      # a metric the spec asks for but the report lacks is check()'s "missing"
                got = reported[k]
                if got is None or want is None:
                    edited = (got is None) != (want is None)
                else:
                    edited = not math.isclose(got, want, abs_tol=1e-9)
                if edited:
                    problems.append(f"metric {k} is {got} in the summary but the rows add up to {want}: summary was edited")

    if base_spec is not None:
        problems += _ratchet(spec, base_spec)
    return problems


def _limits(entry: dict, is_slice: bool) -> dict:
    return entry if is_slice else (entry.get("threshold") or {})


def _loosened(label: str, old: dict, new: dict, is_slice: bool) -> list[str]:
    """What the PR's version of one metric/slice gives up relative to main's."""
    ol, nl = _limits(old, is_slice), _limits(new, is_slice)
    out = []
    if "min" in ol:
        if "min" not in nl:
            out.append(f"{label}: floor removed (was min {ol['min']})")
        elif nl["min"] < ol["min"]:
            out.append(f"{label}: floor lowered min {ol['min']} -> {nl['min']}")
    for key in ("max", "max_increase"):
        if key in ol:
            if key not in nl:
                out.append(f"{label}: ceiling removed (was {key} {ol[key]})")
            elif nl[key] > ol[key]:
                out.append(f"{label}: ceiling raised {key} {ol[key]} -> {nl[key]}")
    if ol.get("no_significant_drop") and not nl.get("no_significant_drop"):
        out.append(f"{label}: no_significant_drop dropped")
    if old.get("blocking") and not new.get("blocking"):
        out.append(f"{label}: no longer blocking")
    for key in (("metric",) if is_slice else ("kind", "grader")):     # what the entry measures may not change under the same name
        if old.get(key) != new.get(key):
            out.append(f"{label}: {key} changed {old.get(key)!r} -> {new.get(key)!r} (moving the goalposts)")
    return out


def _ratchet(spec: dict, base_spec: dict) -> list[str]:
    """Same eval-set version => every threshold may only get stricter. A new version starts afresh."""
    if spec.get("eval_set_version") != base_spec.get("eval_set_version"):
        return []
    out = []
    now = {m["id"]: m for m in spec.get("metrics", [])}
    for old in base_spec.get("metrics", []):
        new = now.get(old["id"])
        out += [f"ratchet: metric {old['id']} removed"] if new is None else _loosened(f"ratchet: metric {old['id']}", old, new, False)
    now_s = {s["name"]: s for s in spec.get("slices") or []}
    for old in base_spec.get("slices") or []:
        new = now_s.get(old["name"])
        out += [f"ratchet: slice {old['name']} removed"] if new is None else _loosened(f"ratchet: slice {old['name']}", old, new, True)
    lost = sorted(set(base_spec.get("seeds") or []) - set(spec.get("seeds") or []))
    if lost:
        out.append(f"ratchet: seeds {lost} removed from the spec")
    lost_k = sorted(set(base_spec.get("pass_k") or []) - set(spec.get("pass_k") or []))
    if lost_k:
        out.append(f"ratchet: pass_k {lost_k} removed from the spec")
    ob, nb = base_spec.get("bootstrap") or {}, spec.get("bootstrap") or {}
    for key in ("rng", "method"):
        if key in ob and nb.get(key) != ob[key]:
            out.append(f"ratchet: bootstrap {key} changed {ob[key]!r} -> {nb.get(key)!r} (re-rolling the CI)")
    if "n_resamples" in ob and nb.get("n_resamples", 0) < ob["n_resamples"]:
        out.append(f"ratchet: bootstrap n_resamples lowered {ob['n_resamples']} -> {nb.get('n_resamples')}")
    if "confidence" in ob and nb.get("confidence", 0.95) > ob["confidence"]:
        out.append(f"ratchet: bootstrap confidence raised {ob['confidence']} -> {nb['confidence']} (a wider CI blocks less)")
    return out


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines).

    A slice with no rows in the PR report cannot be verified, so it fails: silence is not a pass."""
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for s in spec.get("slices") or []:
        sid = f"slice:{s['name']}/{s['metric']}"
        a, b = per_item(pr, s["metric"], s["name"]), per_item(base, s["metric"], s["name"])
        failed, note = False, ""
        if not a:
            val, failed, note = None, True, "no rows carry this slice tag"
        else:
            val = sum(a.values()) / len(a)
            if "min" in s and val < s["min"]:
                failed = True
            if s.get("no_significant_drop"):
                keys = sorted(set(a) & set(b))
                if keys:
                    d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                                       n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027),
                                                       confidence=bs.get("confidence", 0.95))
                    note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                    failed = failed or hi < 0
                else:
                    failed, note = True, "no item in common with the baseline"
        if failed and s.get("blocking"):
            blocked.append(sid)
        label = "ok" if not failed else ("BLOCK" if s.get("blocking") else "warn")
        rule = json.dumps({k: s[k] for k in ("min", "no_significant_drop") if k in s})
        shown = "-" if val is None else round(val, 4)
        lines.append(f"  {sid:<34} {shown!s:<8} {rule:<40} {note:<28} {label}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027),
                                               confidence=bs.get("confidence", 0.95))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
