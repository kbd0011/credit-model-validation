"""
Unit tests for the validator's statistical helpers.

Each test checks a helper against a closed-form value, an independent
library implementation, or a known statistical property. These tests are
the evidence that the validation's own tooling is fit for purpose (a
validator's tools are themselves subject to model risk scrutiny under SR 26-2).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy import stats
from scipy.special import expit
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from validation import stats_core as sc  # noqa: E402
from validation.tests import _wald, ks_stat  # noqa: E402


@pytest.fixture(scope="module")
def sim():
    """Perfectly calibrated simulated scores: y ~ Bernoulli(p)."""
    rng = np.random.default_rng(123)
    lp = rng.normal(-2.0, 1.2, 40_000)
    p = expit(lp)
    y = rng.binomial(1, p)
    return y, p, lp


# ---------------------------------------------------------------- PSI
def test_psi_identical_is_zero():
    x = np.random.default_rng(0).normal(size=5000)
    assert sc.psi(x, x) == pytest.approx(0.0, abs=1e-12)


def test_psi_matches_hand_computation():
    base = np.linspace(0, 1, 100_001)                       # deciles at 0.1, 0.2, ...
    shares = np.array([0.05, 0.05, 0.10, 0.10, 0.10, 0.10, 0.10, 0.10, 0.15, 0.15])
    comp = np.repeat(np.arange(10) / 10 + 0.05, (shares * 10_000).astype(int))   # bin centres
    expected = float(np.sum((shares - 0.1) * np.log(shares / 0.1)))
    assert sc.psi(base, comp) == pytest.approx(expected, rel=1e-3)


def test_psi_from_shares_symmetric():
    b, c = np.array([0.2, 0.3, 0.5]), np.array([0.3, 0.3, 0.4])
    assert sc.psi_from_shares(b, c) == pytest.approx(sc.psi_from_shares(c, b))


# ---------------------------------------------------------------- KS / AUC
def test_ks_equals_two_sample_ks(sim):
    y, p, _ = sim
    ref = stats.ks_2samp(p[y == 1], p[y == 0]).statistic
    assert sc.ks_fast(y, p) == pytest.approx(ref, abs=1e-12)
    assert ks_stat(y, p) == pytest.approx(ref, abs=1e-9)


def test_ks_with_ties():
    y = np.array([0, 0, 1, 1, 0, 1])
    p = np.array([0.1, 0.2, 0.2, 0.4, 0.4, 0.9])
    ref = stats.ks_2samp(p[y == 1], p[y == 0]).statistic
    assert sc.ks_fast(y, p) == pytest.approx(ref)


def test_auc_fast_matches_sklearn_with_ties(sim):
    y, p, _ = sim
    pr = np.round(p, 2)                                     # force many ties
    assert sc.auc_fast(y, pr) == pytest.approx(roc_auc_score(y, pr), abs=1e-12)


def test_bootstrap_ci_contains_point(sim):
    y, p, _ = sim
    r = sc.bootstrap_discrimination(y[:5000], p[:5000], n_boot=200, seed=1)
    assert r["auc_ci"][0] < r["auc"] < r["auc_ci"][1]
    assert r["gini"] == pytest.approx(2 * r["auc"] - 1)


# ---------------------------------------------------------------- DeLong
def test_delong_identical_models():
    rng = np.random.default_rng(2)
    y = rng.binomial(1, 0.3, 500)
    p = rng.uniform(size=500)
    r = sc.delong_test(y, p, p)
    assert r["diff"] == 0 and r["p_value"] == 1.0


def test_delong_se_matches_bootstrap(sim):
    """DeLong SE of a single AUC should match the bootstrap SE within 10%."""
    y, p, _ = sim
    y, p = y[:8000], p[:8000]
    r = sc.delong_test(y, p, p + 1e-9 * np.random.default_rng(0).normal(size=len(p)))
    boot = sc.bootstrap_discrimination(y, p, n_boot=600, seed=3)["auc_boot_se"]
    assert r["auc_1_se"] == pytest.approx(boot, rel=0.10)


def test_delong_detects_better_model(sim):
    y, _, lp = sim
    rng = np.random.default_rng(4)
    good, noisy = lp, lp + rng.normal(0, 1.5, len(lp))
    r = sc.delong_test(y, noisy, good)
    assert r["diff"] > 0 and r["p_value"] < 1e-6


# ---------------------------------------------------------------- Calibration
def test_hosmer_lemeshow_hand_case():
    # two groups of 100 with predicted 0.1 and 0.3; observed 15 and 25 defaults
    p = np.r_[np.full(100, 0.1), np.full(100, 0.3)]
    y = np.r_[np.ones(15), np.zeros(85), np.ones(25), np.zeros(75)]
    hl, dof, pval, _ = sc.hosmer_lemeshow(y, p, g=2)
    expected = (15 - 10) ** 2 / (10 * 0.9) + (25 - 30) ** 2 / (30 * 0.7)
    assert hl == pytest.approx(expected)
    assert dof == 0


def test_hosmer_lemeshow_calibrated_vs_miscalibrated(sim):
    y, p, _ = sim
    assert sc.hosmer_lemeshow(y, p)[2] > 0.01
    assert sc.hosmer_lemeshow(y, np.clip(p * 1.3, 0, 0.999))[2] < 1e-6


def test_calibration_slope_recovers_known_values(sim):
    y, _, lp = sim
    a, b = sc.calibration_slope_intercept(y, expit(lp))
    assert a == pytest.approx(0, abs=0.08) and b == pytest.approx(1, abs=0.04)
    # predictions twice as extreme -> slope ~ 0.5 (over-fitting signature)
    a2, b2 = sc.calibration_slope_intercept(y, expit(2 * lp + 2.0))
    assert b2 == pytest.approx(0.5, abs=0.03)


def test_calibration_slope_matches_sklearn(sim):
    y, p, _ = sim
    lp = np.log(p / (1 - p)).reshape(-1, 1)
    m = LogisticRegression(C=1e10, tol=1e-10, max_iter=5000).fit(lp, y)
    a, b = sc.calibration_slope_intercept(y, p)
    assert b == pytest.approx(m.coef_[0][0], abs=1e-4)
    assert a == pytest.approx(m.intercept_[0], abs=1e-4)


def test_spiegelhalter_and_citl(sim):
    y, p, _ = sim
    assert sc.spiegelhalter_z(y, p)["p_value"] > 0.01
    c = sc.calibration_in_the_large(y, p)
    assert c["obs_over_pred"] == pytest.approx(1, abs=0.03)
    shifted = sc.calibration_in_the_large(y, expit(np.log(p / (1 - p)) - 0.3))
    assert shifted["citl_intercept"] == pytest.approx(0.3, abs=0.05)
    assert shifted["p_value"] < 1e-6


def test_jeffreys_and_binomial_tests():
    # 30 defaults out of 100 at PD 10% is overwhelmingly under-predicted
    assert sc.jeffreys_test(30, 100, 0.10) < 1e-6
    assert sc.binomial_test_under(30, 100, 0.10) == pytest.approx(stats.binom.sf(29, 100, 0.10))
    assert sc.traffic_light(sc.jeffreys_test(10, 100, 0.10)) == "green"
    assert sc.traffic_light(0.03) == "amber" and sc.traffic_light(0.001) == "red"


def test_ece_zero_when_perfect():
    p = np.repeat([0.1, 0.2], 1000)
    y = np.r_[np.tile([1] + [0] * 9, 100), np.tile([1, 0, 0, 0, 0], 200)]
    assert sc.expected_calibration_error(y, p, bins=2) == pytest.approx(0, abs=1e-12)


# ---------------------------------------------------------------- Fairness
def test_adverse_impact_ratio_hand_case():
    approved = np.array([1, 1, 1, 0, 1, 1, 0, 0], bool)
    group = np.array(["A", "A", "A", "A", "B", "B", "B", "B"])
    assert sc.adverse_impact_ratio(approved, group, "B", "A") == pytest.approx(0.5 / 0.75)


# ---------------------------------------------------------------- Wald SEs
def _two_by_two():
    """Binary covariate: cells a,b (x=1: defaults, non-defaults), c,d (x=0)."""
    a, b, c, d = 40, 160, 30, 270
    x = np.r_[np.ones(a + b), np.zeros(c + d)]
    y = np.r_[np.ones(a), np.zeros(b), np.ones(c), np.zeros(d)]
    return x, y, (a, b, c, d)


def test_wald_se_closed_form_irls():
    x, y, (a, b, c, d) = _two_by_two()
    fit = sc.fit_logit_irls(np.column_stack([np.ones_like(x), x]), y)
    assert fit.beta[1] == pytest.approx(np.log(a * d / (b * c)), abs=1e-10)
    assert fit.se[1] == pytest.approx(np.sqrt(1 / a + 1 / b + 1 / c + 1 / d), abs=1e-10)
    assert fit.se[0] == pytest.approx(np.sqrt(1 / c + 1 / d), abs=1e-10)


def test_wald_se_closed_form_production_helper():
    """The helper used on the production model (tests._wald) reproduces the closed form."""
    x, y, (a, b, c, d) = _two_by_two()
    X = pd.DataFrame({"x": x})
    m = LogisticRegression(C=1e12, tol=1e-12, max_iter=10_000).fit(X, y)
    w = _wald({"model": m}, X).set_index("variable")
    assert w.loc["x", "std_err"] == pytest.approx(np.sqrt(1 / a + 1 / b + 1 / c + 1 / d), abs=1e-4)


# ---------------------------------------------------------------- WOE / IV
def test_woe_iv_binary_hand_case():
    x = pd.Series(["u"] * 100 + ["v"] * 100)
    y = pd.Series([1] * 20 + [0] * 80 + [1] * 5 + [0] * 95)
    t, iv = sc.woe_iv(x, y)
    # with +0.5 smoothing
    g = np.array([80.5, 95.5]) / (175 + 1)
    bd = np.array([20.5, 5.5]) / (25 + 1)
    assert iv == pytest.approx(float(np.sum((g - bd) * np.log(g / bd))))


def test_woe_iv_missing_bin():
    x = pd.Series([1.0, 2.0, np.nan, np.nan] * 50)
    y = pd.Series([0, 0, 1, 1] * 50)
    t, _ = sc.woe_iv(x, y)
    assert "Missing" in set(t.bin)


# ---------------------------------------------------------------- Hinge knot
def test_profile_hinge_recovers_known_knot():
    """Simulate a logit with a hinge at 0.35 and recover it by profile likelihood."""
    rng = np.random.default_rng(31)
    n = 60_000
    x = rng.uniform(0, 0.9, n)
    z = rng.normal(size=n)
    true_knot = 0.35
    eta = -2.0 + 0.8 * z + 1.0 * x + 5.0 * np.maximum(x - true_knot, 0)
    y = rng.binomial(1, expit(eta))
    base = np.column_stack([np.ones(n), z, x])
    grid = np.round(np.arange(0.20, 0.651, 0.01), 2)
    r = sc.profile_hinge_knot(base, x, y, grid)
    assert abs(r["knot"] - true_knot) <= 0.03
    assert r["ci_lo"] <= true_knot <= r["ci_hi"]
    assert r["ci_hi"] - r["ci_lo"] < 0.15


def test_profile_hinge_flat_when_no_hinge():
    """With a purely linear effect the interval should be wide (no identifiable knot)."""
    rng = np.random.default_rng(32)
    n = 20_000
    x = rng.uniform(0, 0.9, n)
    y = rng.binomial(1, expit(-2.0 + 1.5 * x))
    base = np.column_stack([np.ones(n), x])
    grid = np.round(np.arange(0.20, 0.651, 0.01), 2)
    r = sc.profile_hinge_knot(base, x, y, grid)
    assert r["ci_hi"] - r["ci_lo"] >= 0.15
