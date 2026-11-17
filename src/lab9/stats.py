"""Statistics students implement (M2 judge calibration, M4 paired bootstrap, M6 pass@k / pass^k).

Rules: a judge is a classifier -- measure it like one. A higher mean is not
"better" until the paired CI of the difference excludes 0.
Reference values to self-check are in tests/test_lab9_stats.py.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
from scipy import stats as _scipy_stats

POS = "FAIL"   # the judge's job is to FIND failures, so FAIL is the positive class
NEG = "PASS"


def _normalise(human: Sequence[str], judge: Sequence[str]) -> tuple[list[str], list[str]]:
    """Same length, only PASS/FAIL. A typo such as "FAILED" must not silently count as PASS."""
    if len(human) != len(judge):
        raise ValueError(f"human and judge must have the same length ({len(human)} != {len(judge)})")
    h = [str(x).strip().upper() for x in human]
    j = [str(x).strip().upper() for x in judge]
    bad = sorted({x for x in h + j if x not in (POS, NEG)})
    if bad:
        raise ValueError(f"labels must be {NEG} or {POS}, got {bad}")
    return h, j


def confusion(human: Sequence[str], judge: Sequence[str]) -> dict[str, int]:
    """tp/fp/fn/tn with FAIL as positive."""
    h, j = _normalise(human, judge)
    return {
        "tp": sum(a == POS and b == POS for a, b in zip(h, j)),
        "fp": sum(a == NEG and b == POS for a, b in zip(h, j)),
        "fn": sum(a == POS and b == NEG for a, b in zip(h, j)),
        "tn": sum(a == NEG and b == NEG for a, b in zip(h, j)),
    }


def precision_recall(human: Sequence[str], judge: Sequence[str]) -> tuple[float, float]:
    """precision = tp/(tp+fp), recall = tp/(tp+fn); 0.0 when the denominator is 0."""
    cm = confusion(human, judge)
    flagged = cm["tp"] + cm["fp"]
    actual = cm["tp"] + cm["fn"]
    return (cm["tp"] / flagged if flagged else 0.0, cm["tp"] / actual if actual else 0.0)


def cohen_kappa(human: Sequence[str], judge: Sequence[str]) -> float:
    """kappa = (p_o - p_e) / (1 - p_e). Raise ValueError when undefined (p_e == 1):
    a constant judge has no signal and must FAIL calibration, not pass on a technicality."""
    h, j = _normalise(human, judge)
    n = len(h)
    if n == 0:
        raise ValueError("kappa is undefined for an empty sample")
    p_o = sum(a == b for a, b in zip(h, j)) / n
    p_e = sum((h.count(c) / n) * (j.count(c) / n) for c in (POS, NEG))
    if p_e >= 1.0 - 1e-12:
        raise ValueError("kappa is undefined: chance agreement is 1 (a constant rater carries no signal)")
    return (p_o - p_e) / (1.0 - p_e)


def rogan_gladen(observed_rate: float, sensitivity: float, specificity: float) -> float:
    """Correct an observed failure rate for judge error; clip to [0, 1].

    true_rate = (p_obs + spec - 1) / (sens + spec - 1). The denominator is Youden's J: when the
    judge is no better than a coin (J <= 0) the correction is undefined and we return NaN rather
    than a number that looks like a measurement (NaN fails every comparison downstream).
    """
    for name, v in (("observed_rate", observed_rate), ("sensitivity", sensitivity), ("specificity", specificity)):
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"{name} must be in [0, 1], got {v}")
    youden = sensitivity + specificity - 1.0
    if youden <= 1e-12:
        return float("nan")
    return min(1.0, max(0.0, (observed_rate + specificity - 1.0) / youden))


def _mean_difference(x: np.ndarray, y: np.ndarray, axis: int = -1) -> np.ndarray:
    return np.mean(x, axis=axis) - np.mean(y, axis=axis)


def paired_bootstrap(a: Sequence[float], b: Sequence[float], *, n_resamples: int = 1000,
                     rng: int = 2027, confidence: float = 0.95) -> tuple[float, float, float]:
    """a[i], b[i] = per-item mean over seeds, SAME items, SAME order.
    Return (mean(a)-mean(b), lo, hi) with scipy.stats.bootstrap(paired=True, method="percentile",
    rng=numpy.random.default_rng(rng)). If a == b everywhere return (0.0, 0.0, 0.0).

    Items are the resampling unit: seeds of one item are not independent draws, so they are
    averaged first (see lab9.eval.per_item)."""
    x = np.asarray(a, dtype=float)
    y = np.asarray(b, dtype=float)
    if x.ndim != 1 or x.shape != y.shape:
        raise ValueError("a and b must be 1-D with the same length (same items, same order)")
    if x.size == 0:
        raise ValueError("paired_bootstrap needs at least one item")
    if not (np.isfinite(x).all() and np.isfinite(y).all()):
        raise ValueError("paired_bootstrap got NaN/inf: refuse to average over a crashed grader")
    if not 0.0 < confidence < 1.0 or int(n_resamples) < 1:
        raise ValueError("need 0 < confidence < 1 and n_resamples >= 1")
    if np.array_equal(x, y):
        return (0.0, 0.0, 0.0)
    delta = float(x.mean() - y.mean())
    if x.size < 2:                      # one item: there is nothing to resample, the CI is the point
        return (delta, delta, delta)
    res = _scipy_stats.bootstrap((x, y), _mean_difference, paired=True, vectorized=True,
                                 method="percentile", n_resamples=int(n_resamples),
                                 confidence_level=confidence, rng=np.random.default_rng(rng))
    return (delta, float(res.confidence_interval.low), float(res.confidence_interval.high))


def _check_nck(n: int, c: int, k: int) -> None:
    """Reject nonsense instead of returning a probability for it."""
    for name, v in (("n", n), ("c", c), ("k", k)):
        if isinstance(v, bool) or not isinstance(v, (int, np.integer)):
            raise ValueError(f"{name} must be an integer, got {v!r}")
    if n < 1:
        raise ValueError(f"n must be >= 1, got {n}")
    if not 0 <= c <= n:
        raise ValueError(f"c must satisfy 0 <= c <= n, got c={c}, n={n}")
    if not 1 <= k <= n:
        raise ValueError(f"k must satisfy 1 <= k <= n, got k={k}, n={n}")


def pass_at_k(n: int, c: int, k: int) -> float:
    """Probability that AT LEAST ONE of k trials drawn from n (c of them passing) passes.
    Unbiased estimator (Chen et al. 2021): 1 - C(n-c, k) / C(n, k). Raise ValueError if k > n."""
    _check_nck(n, c, k)
    n, c, k = int(n), int(c), int(k)
    return 1.0 - math.comb(n - c, k) / math.comb(n, k)


def pass_hat_k(n: int, c: int, k: int) -> float:
    """pass^k (tau-bench, Yao et al. 2024): probability that ALL k trials drawn from n pass.
    Unbiased estimator: C(c, k) / C(n, k). Raise ValueError if k > n.
    pass^k <= pass@1 <= pass@k; a reliable agent keeps pass^k close to pass@1."""
    _check_nck(n, c, k)
    n, c, k = int(n), int(c), int(k)
    return math.comb(c, k) / math.comb(n, k)
