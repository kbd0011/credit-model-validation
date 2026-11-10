"""
Core statistical helpers used across the validation.

These are deliberately implemented from first principles with numpy/scipy so
that (a) the validator does not depend on the same library calls the
developer used (an element of independence in effective challenge), and
(b) each statistic can be unit-tested against a closed-form case
(see tests/test_stats.py).

Conventions
-----------
* ``y`` is the 0/1 default indicator (1 = default, the "bad" event).
* ``p`` is the model's predicted 12-month probability of default.
* A *higher* score means *higher* risk; discrimination metrics are
  computed so that a perfect rank-ordering gives AUC = 1.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats
from scipy.special import expit, logit

# ----------------------------------------------------------------------------
# Discrimination
# ----------------------------------------------------------------------------


def auc_fast(y: np.ndarray, p: np.ndarray) -> float:
    """AUC via the Mann-Whitney U statistic with mid-ranks for ties.

    Equivalent to sklearn's roc_auc_score; used inside bootstrap loops
    because it avoids building the full ROC curve.
    """
    y = np.asarray(y)
    r = stats.rankdata(p)
    n1 = int(y.sum())
    n0 = len(y) - n1
    return float((r[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def ks_fast(y: np.ndarray, p: np.ndarray) -> float:
    """Kolmogorov-Smirnov separation: max |F_bad(s) - F_good(s)| over scores.

    Ties are handled by evaluating the CDFs only at the last occurrence of
    each distinct score, which makes the statistic identical to the
    two-sample KS statistic of the score distributions of defaulters and
    non-defaulters (scipy.stats.ks_2samp) and to max(TPR - FPR) on the ROC.
    """
    y = np.asarray(y)
    p = np.asarray(p)
    order = np.argsort(p, kind="mergesort")
    ps, ys = p[order], y[order]
    cb = np.cumsum(ys) / ys.sum()
    cg = np.cumsum(1 - ys) / (1 - ys).sum()
    last = np.r_[ps[1:] != ps[:-1], True]
    return float(np.max(np.abs(cb[last] - cg[last])))


def bootstrap_discrimination(
    y: np.ndarray, p: np.ndarray, n_boot: int = 1000, seed: int = 0, alpha: float = 0.05
) -> dict:
    """Point estimates and percentile bootstrap CIs for AUC, Gini and KS.

    Regulatory purpose: SR 26-2 expects outcomes analysis to distinguish a
    genuine deterioration in performance from sampling noise. Reporting a
    point AUC without an interval invites over-reaction to small moves (or
    under-reaction to real ones). Resampling is at loan level, i.e. it
    treats loans as exchangeable within a sample.
    """
    y = np.asarray(y)
    p = np.asarray(p)
    rng = np.random.default_rng(seed)
    n = len(y)
    aucs = np.empty(n_boot)
    kss = np.empty(n_boot)
    for b in range(n_boot):
        idx = rng.integers(0, n, n)
        yb, pb = y[idx], p[idx]
        aucs[b] = auc_fast(yb, pb)
        kss[b] = ks_fast(yb, pb)
    lo, hi = 100 * alpha / 2, 100 * (1 - alpha / 2)
    auc = auc_fast(y, p)
    ks = ks_fast(y, p)
    return {
        "n": int(n),
        "n_defaults": int(y.sum()),
        "auc": auc,
        "auc_ci": [float(np.percentile(aucs, lo)), float(np.percentile(aucs, hi))],
        "auc_boot_se": float(aucs.std(ddof=1)),
        "gini": 2 * auc - 1,
        "gini_ci": [float(2 * np.percentile(aucs, lo) - 1), float(2 * np.percentile(aucs, hi) - 1)],
        "ks": ks,
        "ks_ci": [float(np.percentile(kss, lo)), float(np.percentile(kss, hi))],
        "n_boot": n_boot,
    }


def delong_test(y: np.ndarray, p1: np.ndarray, p2: np.ndarray) -> dict:
    """DeLong, DeLong & Clarke-Pearson (1988) test for two correlated AUCs.

    Implementation follows the structural-components formulation of
    Sun & Xu (2014) using mid-ranks. Both models are scored on the same
    loans, so the AUCs are correlated and a paired test is required; an
    unpaired comparison of two CIs would be badly conservative.

    Returns AUCs, the difference (p2 - p1), its standard error, z and the
    two-sided p-value, plus each AUC's DeLong standard error.
    """
    y = np.asarray(y).astype(int)
    preds = np.vstack([np.asarray(p1), np.asarray(p2)])
    pos, neg = y == 1, y == 0
    m, n = int(pos.sum()), int(neg.sum())
    k = preds.shape[0]
    aucs = np.empty(k)
    v01 = np.empty((k, m))
    v10 = np.empty((k, n))
    for r in range(k):
        x, z = preds[r, pos], preds[r, neg]
        tx = stats.rankdata(x)
        tz = stats.rankdata(z)
        txz = stats.rankdata(np.concatenate([x, z]))
        aucs[r] = (txz[:m].sum() - m * (m + 1) / 2) / (m * n)
        v01[r] = (txz[:m] - tx) / n
        v10[r] = 1.0 - (txz[m:] - tz) / m
    s01 = np.atleast_2d(np.cov(v01))
    s10 = np.atleast_2d(np.cov(v10))
    S = s01 / m + s10 / n
    diff = aucs[1] - aucs[0]
    var = S[0, 0] + S[1, 1] - 2 * S[0, 1]
    se = float(np.sqrt(max(var, 0.0)))
    z = diff / se if se > 0 else 0.0
    pval = float(2 * stats.norm.sf(abs(z))) if se > 0 else 1.0
    return {
        "auc_1": float(aucs[0]),
        "auc_2": float(aucs[1]),
        "auc_1_se": float(np.sqrt(S[0, 0])),
        "auc_2_se": float(np.sqrt(S[1, 1])),
        "diff": float(diff),
        "diff_se": se,
        "diff_ci": [float(diff - 1.959964 * se), float(diff + 1.959964 * se)],
        "z": float(z),
        "p_value": pval,
    }


# ----------------------------------------------------------------------------
# Calibration
# ----------------------------------------------------------------------------


def hosmer_lemeshow(y, p, g: int = 10):
    """Hosmer-Lemeshow goodness-of-fit over ``g`` equal-mass risk groups.

    Degrees of freedom: g - 2. This is the conventional choice; on a sample
    the model was NOT fit on (out-of-time), g degrees of freedom is the
    stricter alternative, and the report states which was used.
    """
    df = pd.DataFrame({"y": np.asarray(y), "p": np.asarray(p)})
    df["bin"] = pd.qcut(df.p, g, duplicates="drop")
    grp = df.groupby("bin", observed=True).agg(obs=("y", "sum"), exp=("p", "sum"), n=("y", "size"))
    hl = float((((grp.obs - grp.exp) ** 2) / (grp.exp * (1 - grp.exp / grp.n))).sum())
    dof = len(grp) - 2
    return hl, int(dof), float(stats.chi2.sf(hl, dof)), grp


def spiegelhalter_z(y, p) -> dict:
    """Spiegelhalter (1986) z-test of overall calibration.

    Tests H0: E[(y - p)(1 - 2p)] = 0, i.e. the Brier score equals its
    expectation under perfect calibration. Unlike Hosmer-Lemeshow it does
    not depend on an arbitrary binning choice.
    """
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    num = np.sum((y - p) * (1 - 2 * p))
    den = np.sqrt(np.sum((1 - 2 * p) ** 2 * p * (1 - p)))
    z = float(num / den)
    return {"z": z, "p_value": float(2 * stats.norm.sf(abs(z)))}


def calibration_in_the_large(y, p) -> dict:
    """Observed vs expected defaults in aggregate.

    Reports the observed/predicted ratio, a normal-approximation z-test on
    O - E with variance sum p(1-p) (Poisson-binomial), and the calibration
    intercept estimated with the slope fixed at 1 (logistic model with
    offset logit(p)); the intercept is 0 under perfect CITL.
    """
    y = np.asarray(y, dtype=float)
    p = np.clip(np.asarray(p, dtype=float), 1e-12, 1 - 1e-12)
    O, E = y.sum(), p.sum()
    z = (O - E) / np.sqrt(np.sum(p * (1 - p)))
    off = logit(p)
    a = 0.0
    for _ in range(50):  # 1-D Newton-Raphson for intercept with offset
        mu = expit(a + off)
        step = np.sum(y - mu) / np.sum(mu * (1 - mu))
        a += step
        if abs(step) < 1e-12:
            break
    return {
        "observed_defaults": int(O),
        "expected_defaults": float(E),
        "observed_rate": float(O / len(y)),
        "mean_pd": float(E / len(y)),
        "obs_over_pred": float(O / E),
        "z": float(z),
        "p_value": float(2 * stats.norm.sf(abs(z))),
        "citl_intercept": float(a),
    }


def calibration_slope_intercept(y, p) -> tuple[float, float]:
    """Logistic recalibration logit P(y=1) = a + b * logit(p). Ideal a=0, b=1.

    b < 1 indicates over-fitting (predictions too extreme); b > 1 indicates
    predictions too compressed. Fitted with the validator's own IRLS.
    """
    lp = logit(np.clip(np.asarray(p, dtype=float), 1e-12, 1 - 1e-12))
    X = np.column_stack([np.ones_like(lp), lp])
    fit = fit_logit_irls(X, np.asarray(y, dtype=float))
    return float(fit.beta[0]), float(fit.beta[1])


def jeffreys_interval(k: np.ndarray | int, n: np.ndarray | int, alpha: float = 0.05):
    """Jeffreys (Beta(k+1/2, n-k+1/2)) interval for a binomial proportion."""
    k = np.asarray(k, dtype=float)
    n = np.asarray(n, dtype=float)
    lo = np.where(k > 0, stats.beta.ppf(alpha / 2, k + 0.5, n - k + 0.5), 0.0)
    hi = np.where(k < n, stats.beta.ppf(1 - alpha / 2, k + 0.5, n - k + 0.5), 1.0)
    return lo, hi


def reliability_table(y, p, bins: int = 10) -> pd.DataFrame:
    """Equal-mass reliability table with Jeffreys 95% intervals on observed DR."""
    df = pd.DataFrame({"y": np.asarray(y), "p": np.asarray(p)})
    df["bin"] = pd.qcut(df.p, bins, labels=False, duplicates="drop")
    g = df.groupby("bin").agg(n=("y", "size"), defaults=("y", "sum"),
                              predicted=("p", "mean"), observed=("y", "mean")).reset_index()
    lo, hi = jeffreys_interval(g.defaults.values, g.n.values)
    g["obs_lo"], g["obs_hi"] = lo, hi
    g["pred_in_ci"] = (g.predicted >= g.obs_lo) & (g.predicted <= g.obs_hi)
    return g


def expected_calibration_error(y, p, bins: int = 10) -> float:
    """ECE: population-weighted mean |observed - predicted| over equal-mass bins."""
    g = reliability_table(y, p, bins)
    return float(np.sum(g.n * np.abs(g.observed - g.predicted)) / g.n.sum())


def jeffreys_test(defaults: int, n: int, pd_: float) -> float:
    """One-sided Jeffreys test for PD under-estimation (ECB TRIM / EBA style).

    p-value = P(theta <= PD | data) under the Jeffreys posterior
    Beta(D + 1/2, N - D + 1/2). Small values mean the observed default rate
    is credibly above the predicted PD (the model is non-conservative).
    """
    return float(stats.beta.cdf(pd_, defaults + 0.5, n - defaults + 0.5))


def binomial_test_under(defaults: int, n: int, pd_: float) -> float:
    """One-sided exact binomial test: P(X >= D | N, PD). Small = under-prediction."""
    return float(stats.binom.sf(defaults - 1, n, pd_))


def traffic_light(pval: float, amber: float = 0.05, red: float = 0.01) -> str:
    """Basel-style traffic light from a one-sided under-estimation p-value."""
    if pval < red:
        return "red"
    if pval < amber:
        return "amber"
    return "green"


# ----------------------------------------------------------------------------
# Stability
# ----------------------------------------------------------------------------


def psi(base: np.ndarray, comp: np.ndarray, bins: int = 10) -> float:
    """Population Stability Index with quantile bins fixed on the base sample.

    PSI = sum_k (c_k - b_k) ln(c_k / b_k). Empty bins are floored at 1e-6.
    Industry convention: < 0.10 stable, 0.10-0.25 moderate shift (investigate),
    > 0.25 significant shift (action).
    """
    base = np.asarray(base, dtype=float)
    comp = np.asarray(comp, dtype=float)
    edges = np.unique(np.quantile(base, np.linspace(0, 1, bins + 1)))
    edges[0], edges[-1] = -np.inf, np.inf
    b = np.histogram(base, edges)[0] / len(base)
    c = np.histogram(comp, edges)[0] / len(comp)
    b, c = np.clip(b, 1e-6, None), np.clip(c, 1e-6, None)
    return float(np.sum((c - b) * np.log(c / b)))


def psi_from_shares(b: np.ndarray, c: np.ndarray) -> float:
    """PSI given pre-binned shares (e.g. rating-grade distributions)."""
    b = np.clip(np.asarray(b, dtype=float), 1e-6, None)
    c = np.clip(np.asarray(c, dtype=float), 1e-6, None)
    return float(np.sum((c - b) * np.log(c / b)))


# ----------------------------------------------------------------------------
# Fair lending
# ----------------------------------------------------------------------------


def adverse_impact_ratio(approved: np.ndarray, group: np.ndarray, protected, control) -> float:
    """AIR = approval rate (protected) / approval rate (control).

    The four-fifths rule of thumb (29 CFR 1607.4(D), borrowed from
    employment law) flags AIR < 0.80; many bank fair-lending programs use
    a tighter internal trigger (e.g. 0.90) for further review.
    """
    approved = np.asarray(approved, dtype=bool)
    group = np.asarray(group)
    return float(approved[group == protected].mean() / approved[group == control].mean())


# ----------------------------------------------------------------------------
# Logistic regression by IRLS (validator's independent estimator)
# ----------------------------------------------------------------------------


@dataclass
class LogitFit:
    beta: np.ndarray
    cov: np.ndarray
    loglik: float
    n_iter: int

    @property
    def se(self) -> np.ndarray:
        return np.sqrt(np.diag(self.cov))


def fit_logit_irls(X: np.ndarray, y: np.ndarray, max_iter: int = 100, tol: float = 1e-10) -> LogitFit:
    """Unpenalised logistic regression by Newton-Raphson / IRLS.

    Covariance is the inverse observed (= expected, canonical link)
    information matrix at the MLE. ``X`` must already include an intercept
    column if one is wanted.
    """
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float)
    beta = np.zeros(X.shape[1])
    it = 0
    for it in range(1, max_iter + 1):
        mu = expit(X @ beta)
        W = mu * (1 - mu)
        H = (X * W[:, None]).T @ X
        g = X.T @ (y - mu)
        step = np.linalg.solve(H, g)
        beta = beta + step
        if np.max(np.abs(step)) < tol:
            break
    mu = np.clip(expit(X @ beta), 1e-15, 1 - 1e-15)
    W = mu * (1 - mu)
    H = (X * W[:, None]).T @ X
    ll = float(np.sum(y * np.log(mu) + (1 - y) * np.log(1 - mu)))
    return LogitFit(beta=beta, cov=np.linalg.inv(H), loglik=ll, n_iter=it)


def profile_hinge_knot(base: np.ndarray, x: np.ndarray, y: np.ndarray, grid: np.ndarray, level: float = 0.95) -> dict:
    """Profile-likelihood estimate of a hinge (linear-spline) knot.

    For each k in ``grid`` fits logit P(y=1) = base @ b + c * max(x - k, 0)
    by IRLS (``base`` must include an intercept) and returns the arg-max knot
    and the interval {k : ll(k) >= ll_max - chi2_1(level) / 2}.
    """
    y = np.asarray(y, dtype=float)
    ll = np.array([fit_logit_irls(np.column_stack([base, np.maximum(x - k, 0)]), y).loglik for k in grid])
    i = int(np.argmax(ll))
    inside = np.asarray(grid)[ll >= ll[i] - stats.chi2.ppf(level, 1) / 2]
    return {"knot": float(grid[i]), "ci_lo": float(inside.min()), "ci_hi": float(inside.max()), "loglik": ll,
            "n_in_ci": int(len(inside))}


def wald_from_coefficients(beta: np.ndarray, X: np.ndarray) -> np.ndarray:
    """Covariance of logit coefficients from the information matrix at ``beta``.

    ``X`` must include the intercept column. Used to obtain standard errors
    for a model fitted by another party (the production model).
    """
    mu = expit(X @ beta)
    W = mu * (1 - mu)
    return np.linalg.inv((X * W[:, None]).T @ X)


# ----------------------------------------------------------------------------
# Characteristic analysis
# ----------------------------------------------------------------------------


def woe_iv(x: pd.Series, y: pd.Series, bins: int = 10, discrete_cap: int | None = None) -> tuple[pd.DataFrame, float]:
    """Weight of evidence and information value for one characteristic.

    WOE_k = ln(%non-default_k / %default_k); IV = sum (%nd_k - %d_k) * WOE_k.
    Missing values form their own bin so that informative missingness is
    visible. Conventional IV reading: <0.02 unpredictive, 0.02-0.10 weak,
    0.10-0.30 medium, >0.30 strong.
    """
    x = pd.Series(x).reset_index(drop=True)
    y = pd.Series(y).reset_index(drop=True)
    numeric = pd.api.types.is_numeric_dtype(x)
    if discrete_cap is not None:
        capped = x.clip(upper=discrete_cap)
        order = capped.fillna(np.inf)
        lab = capped.map(lambda v: f"{int(v)}+" if v >= discrete_cap else str(int(v)) if pd.notna(v) else "Missing")
    elif not numeric or x.nunique() <= 5:
        order = x.astype(str)
        lab = x.astype(str)
    else:
        q = pd.qcut(x, bins, duplicates="drop")
        order = pd.Series(q.cat.codes, dtype=float).where(x.notna(), np.inf)
        lab = q.astype(str)
    lab = lab.where(x.notna(), "Missing")
    t = (pd.DataFrame({"bin": lab, "y": y, "_o": order})
         .groupby("bin", sort=False).agg(n=("y", "size"), bad=("y", "sum"), _o=("_o", "first"))
         .sort_values("_o").drop(columns="_o"))
    t["good"] = t.n - t.bad
    t["pct_good"] = (t.good + 0.5) / (t.good.sum() + 0.5 * len(t))
    t["pct_bad"] = (t.bad + 0.5) / (t.bad.sum() + 0.5 * len(t))
    t["woe"] = np.log(t.pct_good / t.pct_bad)
    t["iv_contrib"] = (t.pct_good - t.pct_bad) * t.woe
    t["default_rate"] = t.bad / t.n
    return t.reset_index(), float(t.iv_contrib.sum())
