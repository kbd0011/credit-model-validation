"""
Extended second-line validation tests.

This module deepens the baseline library in ``validation/tests.py``. Each
function returns plain Python / pandas objects that ``run_validation.py``
serialises to ``outputs/tables`` and that ``figures.py`` plots. The mapping to
SR 26-2 / OCC 2026-13 (which retains the SR 11-7 validation components) is
stated in each docstring.

The production model is never refit here. Where a refit appears it is a
*validator-built* comparator (challenger, counterfactual or bootstrap
replicate), and the function says so.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats
from scipy.special import expit, logit
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

from model.develop_model import FEATURES, prepare
from validation import stats_core as sc
from validation.tests import _enhanced_features, dev_train_split, score

APPROVAL_RATE = 0.70          # documented underwriting policy: approve lowest-risk 70% at development
N_GRADES = 8                  # master-scale grades, quantile-based on development scores
GBM_PARAMS = dict(max_iter=300, learning_rate=0.05, max_depth=4, random_state=0)
# Expected direction of each production input (economic intuition / policy).
MONOTONE = {"fico": -1, "dti": 1, "utilization": 1, "income_log": 0, "inquiries_6m": 1,
            "delinq_24m": 1, "employment_years": -1, "region_risk": 0, "channel_broker": 0}


def clean_mask(df: pd.DataFrame) -> np.ndarray:
    """Rows that pass the validator's range edits (FICO in [300, 850], DTI in [0, 1])."""
    return ((df.fico >= 300) & (df.fico <= 850) & (df.dti >= 0) & (df.dti <= 1)).values


def dev_split(dev: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Reproduce the developer's documented 70/30 random split (seed 7)."""
    return dev_train_split(dev)


def linear_predictor(artifact, X: pd.DataFrame, beta: np.ndarray | None = None) -> np.ndarray:
    """Production log-odds; optionally with a perturbed coefficient vector [b0, b1..bk]."""
    m = artifact["model"]
    if beta is None:
        beta = np.concatenate([m.intercept_, m.coef_[0]])
    return beta[0] + X.values @ beta[1:]


# ----------------------------------------------------------------------------
# Challengers (validator-built)
# ----------------------------------------------------------------------------
@dataclass
class Challengers:
    train: pd.DataFrame
    test: pd.DataFrame
    gbm: HistGradientBoostingClassifier
    gbm_mono: HistGradientBoostingClassifier
    enhanced: LogisticRegression
    no_region: LogisticRegression
    fill: float
    knot: float

    def predict(self, name: str, d: pd.DataFrame, artifact) -> np.ndarray:
        if name == "production":
            return score(artifact, d)
        X, _ = prepare(d, self.fill)
        if name == "gbm":
            return self.gbm.predict_proba(X)[:, 1]
        if name == "gbm_monotone":
            return self.gbm_mono.predict_proba(X)[:, 1]
        if name == "enhanced_logit":
            return self.enhanced.predict_proba(_enhanced_features(d, self.fill, self.knot))[:, 1]
        if name == "no_region_logit":
            return self.no_region.predict_proba(X.drop(columns="region_risk"))[:, 1]
        raise KeyError(name)


def select_dti_knot(artifact, dev: pd.DataFrame, grid: np.ndarray | None = None) -> dict:
    """Profile-likelihood search for the DTI hinge location.

    The validator does not know where (or whether) the DTI effect changes
    slope, so the knot is estimated from the data rather than assumed. For
    each candidate k on the grid, the enhanced specification (nine production
    inputs + income-missing flag + max(DTI - k, 0)) is fitted by IRLS on the
    developer's training split (clean rows only) and its log-likelihood
    recorded. The estimate is the arg-max; the 95% interval is the set of k
    whose log-likelihood lies within chi2(1, 0.95) / 2 = 1.92 of the maximum
    (profile-likelihood interval). A flat profile would indicate no hinge.
    The likelihood-ratio statistic against the linear-DTI model (no hinge)
    is also reported. Because the knot is selected, that statistic is not
    exactly chi-square(1) (Davies' problem); it is reported as descriptive
    evidence, not as a formal test.
    """
    if grid is None:
        grid = np.round(np.arange(0.20, 0.6501, 0.01), 2)
    train, _ = dev_split(dev)
    d = train[clean_mask(train)]
    X, _ = prepare(d, artifact["income_fill"])
    base = np.column_stack([np.ones(len(d)), X.values, d.income.isna().astype(float).values])
    y = d.default_12m.values.astype(float)
    r = sc.profile_hinge_knot(base, d.dti.values, y, grid)
    ll = r["loglik"]
    ll_linear = sc.fit_logit_irls(base, y).loglik
    return {"grid": grid.tolist(), "loglik": ll.tolist(), "knot_raw": r["knot"], "knot": round(r["knot"], 2),
            "ci_lo": round(r["ci_lo"], 2), "ci_hi": round(r["ci_hi"], 2),
            "ci_contiguous": bool(r["n_in_ci"] == int(round((r["ci_hi"] - r["ci_lo"]) / 0.01)) + 1),
            "max_loglik": float(ll.max()), "loglik_linear_dti": float(ll_linear), "lr_vs_linear": float(2 * (ll.max() - ll_linear)),
            "n_fit": int(len(d)), "grid_step": 0.01}


def fit_challengers(artifact, dev: pd.DataFrame, knot: float) -> Challengers:
    """Fit all validator comparators on the developer's own training split.

    * gbm            - unconstrained gradient boosting on the 9 production inputs
                       (how much signal does the linear form leave behind?)
    * gbm_monotone   - same, with monotonic constraints (what an ML model fit
                       for adverse-action use would have to look like)
    * enhanced_logit - production recipe + income-missing flag + DTI hinge at
                       the data-selected knot (the minimal remediation of the
                       two specification findings)
    * no_region_logit- production recipe without region_risk (less
                       discriminatory alternative search)
    Using the developer's split keeps the comparison like-for-like.
    """
    train, test = dev_split(dev)
    fill = artifact["income_fill"]
    Xtr, _ = prepare(train, fill)
    ytr = train.default_12m
    gbm = HistGradientBoostingClassifier(**GBM_PARAMS).fit(Xtr, ytr)
    cst = [MONOTONE[c] for c in FEATURES]
    gbm_mono = HistGradientBoostingClassifier(**GBM_PARAMS, monotonic_cst=cst).fit(Xtr, ytr)
    enh = LogisticRegression(C=1e6, max_iter=5000, solver="newton-cholesky", tol=1e-10).fit(_enhanced_features(train, fill, knot), ytr)
    nor = LogisticRegression(C=1e6, max_iter=5000, solver="newton-cholesky", tol=1e-10).fit(Xtr.drop(columns="region_risk"), ytr)
    return Challengers(train, test, gbm, gbm_mono, enh, nor, fill, knot)


# ----------------------------------------------------------------------------
# B1 / B3. Discrimination with confidence intervals; DeLong comparisons
# ----------------------------------------------------------------------------
def discrimination_with_ci(artifact, samples: dict[str, pd.DataFrame], n_boot: int = 1000, seed: int = 11) -> pd.DataFrame:
    """AUC, Gini and KS with percentile bootstrap 95% CIs for each sample.

    SR 26-2 outcomes analysis: establishes whether out-of-time
    discrimination is statistically distinguishable from development.
    """
    rows = []
    for i, (name, d) in enumerate(samples.items()):
        r = sc.bootstrap_discrimination(d.default_12m.values, score(artifact, d), n_boot=n_boot, seed=seed + i)
        rows.append({"sample": name, "n": r["n"], "n_defaults": r["n_defaults"],
                     "default_rate": r["n_defaults"] / r["n"],
                     "auc": r["auc"], "auc_lo": r["auc_ci"][0], "auc_hi": r["auc_ci"][1], "auc_se": r["auc_boot_se"],
                     "gini": r["gini"], "gini_lo": r["gini_ci"][0], "gini_hi": r["gini_ci"][1],
                     "ks": r["ks"], "ks_lo": r["ks_ci"][0], "ks_hi": r["ks_ci"][1], "n_boot": n_boot})
    return pd.DataFrame(rows)


def benchmark_delong(artifact, ch: Challengers, samples: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Paired DeLong tests: each challenger vs production on each sample.

    SR 26-2 conceptual soundness (benchmarking): a challenger that is statistically superior on
    out-of-time data is evidence that the production specification leaves
    risk signal unused. The p-value answers "is the gap noise?"; the AUC
    difference and its CI answer "is the gap material?".
    """
    rows = []
    for sname, d in samples.items():
        y = d.default_12m.values
        p0 = ch.predict("production", d, artifact)
        for cname in ("enhanced_logit", "gbm", "gbm_monotone", "no_region_logit"):
            r = sc.delong_test(y, p0, ch.predict(cname, d, artifact))
            rows.append({"sample": sname, "challenger": cname, "auc_production": r["auc_1"],
                         "auc_challenger": r["auc_2"], "auc_diff": r["diff"], "diff_se": r["diff_se"],
                         "diff_lo": r["diff_ci"][0], "diff_hi": r["diff_ci"][1], "z": r["z"], "p_value": r["p_value"]})
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------
# B2. Calibration suite, master scale, traffic lights, grade migration
# ----------------------------------------------------------------------------
def calibration_suite(artifact, samples: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    """CITL, Spiegelhalter, HL (g-2 and g dof), calibration slope/intercept, ECE.

    SR 26-2 outcomes analysis. Several complementary tests are used because
    each has a known blind spot: HL depends on binning, Spiegelhalter can
    mask offsetting errors, CITL tests only the mean, and the slope tests
    only spread.
    """
    rows, rel = [], {}
    for name, d in samples.items():
        y, p = d.default_12m.values, score(artifact, d)
        citl = sc.calibration_in_the_large(y, p)
        sp = sc.spiegelhalter_z(y, p)
        hl, dof, hlp, _ = sc.hosmer_lemeshow(y, p)
        a, b = sc.calibration_slope_intercept(y, p)
        rel[name] = sc.reliability_table(y, p, 10)
        rows.append({"sample": name, "n": len(y), "observed_rate": citl["observed_rate"], "mean_pd": citl["mean_pd"],
                     "obs_over_pred": citl["obs_over_pred"], "citl_z": citl["z"], "citl_p": citl["p_value"],
                     "citl_intercept": citl["citl_intercept"], "spiegelhalter_z": sp["z"], "spiegelhalter_p": sp["p_value"],
                     "hl_stat": hl, "hl_dof": dof, "hl_p": hlp, "hl_p_dof_g": float(stats.chi2.sf(hl, dof + 2)),
                     "calib_intercept": a, "calib_slope": b,
                     "ece": sc.expected_calibration_error(y, p, 10),
                     "bins_pred_outside_ci": int((~rel[name].pred_in_ci).sum())})
    return pd.DataFrame(rows), rel


def master_scale(artifact, dev: pd.DataFrame, n_grades: int = N_GRADES) -> np.ndarray:
    """Interior PD cut-points for an n-grade master scale (equal-population on dev)."""
    return np.quantile(score(artifact, dev), np.linspace(0, 1, n_grades + 1)[1:-1])


def assign_grade(p: np.ndarray, edges: np.ndarray) -> np.ndarray:
    """Grade 1 = lowest PD."""
    return np.searchsorted(edges, p, side="right") + 1


def grade_backtest(artifact, samples: dict[str, pd.DataFrame], edges: np.ndarray) -> pd.DataFrame:
    """Per-grade binomial and Jeffreys tests with Basel-style traffic lights.

    Regulatory purpose: aggregate calibration can hide offsetting grade
    errors. Testing each grade one-sided for under-estimation reflects the
    supervisory focus on non-conservative PDs. Traffic light uses the
    Jeffreys p-value: green >= 0.05, amber [0.01, 0.05), red < 0.01.
    Over-estimation is also reported (two-sided view) for completeness.
    """
    rows = []
    for name, d in samples.items():
        y, p = d.default_12m.values, score(artifact, d)
        g = assign_grade(p, edges)
        for k in range(1, len(edges) + 2):
            m = g == k
            n, D = int(m.sum()), int(y[m].sum())
            if n == 0:
                continue
            pd_ = float(p[m].mean())
            pj = sc.jeffreys_test(D, n, pd_)
            lo, hi = sc.jeffreys_interval(D, n)
            rows.append({"sample": name, "grade": k, "n": n, "defaults": D, "predicted_pd": pd_,
                         "observed_dr": D / n, "obs_lo": float(lo), "obs_hi": float(hi),
                         "binomial_p_under": sc.binomial_test_under(D, n, pd_), "jeffreys_p_under": pj,
                         "jeffreys_p_over": 1 - pj, "traffic_light": sc.traffic_light(pj),
                         "over_estimation_flag": bool(1 - pj < 0.01)})
    return pd.DataFrame(rows)


def grade_migration(artifact, ch: Challengers, dev: pd.DataFrame, target: pd.DataFrame, edges: np.ndarray) -> dict:
    """Grade-mix migration dev -> target, plus a loan-level reclassification matrix.

    An origination portfolio has no repeated observations of the same
    obligor, so a true obligor-level transition matrix is not estimable.
    Two substitutes are reported: (1) the distribution of loans across
    master-scale grades, development vs target, with grade-level PSI; and
    (2) for target loans, a matrix of production grade vs. the grade the
    enhanced challenger would assign, which measures how many decisions the
    specification findings actually move.
    """
    gd = assign_grade(score(artifact, dev), edges)
    gt = assign_grade(score(artifact, target), edges)
    K = len(edges) + 1
    sd = np.bincount(gd, minlength=K + 1)[1:] / len(gd)
    st = np.bincount(gt, minlength=K + 1)[1:] / len(gt)
    mix = pd.DataFrame({"grade": range(1, K + 1), "dev_share": sd, "target_share": st, "change_pp": 100 * (st - sd)})
    ge = assign_grade(ch.predict("enhanced_logit", target, artifact), edges)
    mat = pd.crosstab(pd.Series(gt, name="production_grade"), pd.Series(ge, name="enhanced_grade"))
    mat = mat.reindex(index=range(1, K + 1), columns=range(1, K + 1), fill_value=0)
    move = ge - gt
    far = np.abs(move) >= 2
    miss = target.income.isna().values
    return {"grade_mix": mix, "grade_psi": sc.psi_from_shares(sd, st),
            "n_moved_2plus": int(far.sum()),
            "share_2plus_income_missing": float(miss[far].mean()) if far.any() else float("nan"),
            "share_2plus_to_riskier": float((move[far] > 0).mean()) if far.any() else float("nan"),
            "reclass_counts": mat, "reclass_row_pct": mat.div(mat.sum(1), axis=0),
            "share_same_grade": float(np.trace(mat.values) / mat.values.sum()),
            "share_within_one_grade": float(sum(mat.values[i, j] for i in range(K) for j in range(K) if abs(i - j) <= 1) / mat.values.sum())}


# ----------------------------------------------------------------------------
# Segment calibration (where aggregate calibration hides problems)
# ----------------------------------------------------------------------------
def dti_tail_threshold(dev: pd.DataFrame) -> float:
    """Upper-decile DTI threshold on clean development data (rounded to 2 dp).

    Used to define the high-DTI tail segment without reference to the
    generator: the top decile is a conventional tail cut."""
    return round(float(np.quantile(dev.dti[clean_mask(dev)], 0.90)), 2)


def make_segments(knot: float, tail: float) -> dict:
    """Business segments for calibration testing; DTI cuts are data-derived."""
    return {
        "All loans": lambda d: np.ones(len(d), bool),
        "Income missing": lambda d: d.income.isna().values,
        "Income reported": lambda d: d.income.notna().values,
        f"DTI <= {knot:.2f}": lambda d: (d.dti <= knot).values,
        f"DTI > {knot:.2f}": lambda d: (d.dti > knot).values & (d.dti <= 1).values,
        f"DTI > {tail:.2f}": lambda d: (d.dti > tail).values & (d.dti <= 1).values,
        "FICO < 640": lambda d: ((d.fico < 640) & (d.fico >= 300)).values,
        "Utilization > 0.60": lambda d: (d.utilization > 0.60).values,
        "Broker channel": lambda d: (d.channel == "broker").values,
    }


def segment_calibration(artifact, ch: Challengers, samples: dict[str, pd.DataFrame], segments: dict) -> pd.DataFrame:
    """Observed vs predicted by business segment, production vs enhanced challenger."""
    rows = []
    for sname, d in samples.items():
        y = d.default_12m.values
        p0 = score(artifact, d)
        p1 = ch.predict("enhanced_logit", d, artifact)
        for seg, f in segments.items():
            m = f(d)
            n, D = int(m.sum()), int(y[m].sum())
            pj = sc.jeffreys_test(D, n, float(p0[m].mean()))
            rows.append({"sample": sname, "segment": seg, "n": n, "share": n / len(d), "observed_dr": D / n,
                         "production_pd": float(p0[m].mean()), "production_ratio": D / n / float(p0[m].mean()),
                         "enhanced_pd": float(p1[m].mean()), "enhanced_ratio": D / n / float(p1[m].mean()),
                         "jeffreys_p_under": pj, "jeffreys_p_over": 1 - pj,
                         "traffic_light": sc.traffic_light(min(pj, 1 - pj))})
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------
# B4. Variable-level analysis
# ----------------------------------------------------------------------------
def woe_iv_all(dev: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    """WOE / IV for every candidate characteristic on development data.

    Conceptual soundness: confirms each input carries signal in the
    expected direction and exposes informative missingness (income) that the
    developer's imputation discards.
    """
    specs = {"fico": {}, "dti": {}, "utilization": {}, "income (raw, missing as bin)": {"col": "income"},
             "income_log (as imputed by model)": {"col": "_inc_imp"}, "inquiries_6m": {"discrete_cap": 4},
             "delinq_24m": {"discrete_cap": 3}, "employment_years": {}, "region_risk": {}, "channel": {}}
    d = dev.copy()
    d["_inc_imp"] = np.log(d.income.fillna(d.income.median()))
    summary, tables = [], {}
    for name, kw in specs.items():
        col = kw.get("col", name)
        t, iv = sc.woe_iv(d[col], d.default_12m, discrete_cap=kw.get("discrete_cap"))
        tables[name] = t
        strength = "unpredictive" if iv < 0.02 else "weak" if iv < 0.10 else "medium" if iv < 0.30 else "strong"
        summary.append({"characteristic": name, "iv": iv, "strength": strength, "n_bins": len(t)})
    return pd.DataFrame(summary).sort_values("iv", ascending=False), tables


def binned_logit_profile(artifact, ch: Challengers, dev: pd.DataFrame, feature: str, bins: int = 20) -> pd.DataFrame:
    """Empirical vs model log-odds across bins of one feature (clean dev rows).

    Partial-dependence-style functional-form check: if the production
    model's mean log-odds tracks the empirical log-odds within each bin,
    the linear term is adequate; systematic divergence in one region
    indicates misspecification. Empirical CIs are Jeffreys intervals mapped
    to the logit scale.
    """
    d = dev[clean_mask(dev)]
    q = pd.qcut(d[feature], bins, duplicates="drop")
    p0 = score(artifact, d)
    p1 = ch.predict("enhanced_logit", d, artifact)
    t = pd.DataFrame({"x": d[feature].values, "y": d.default_12m.values, "lp0": logit(p0),
                      "p0": p0, "p1": p1, "bin": q.cat.codes.values})
    g = t.groupby("bin").agg(x=("x", "mean"), n=("y", "size"), defaults=("y", "sum"), model_logit=("lp0", "mean"),
                             model_pd=("p0", "mean"), enhanced_pd=("p1", "mean")).reset_index()
    g["observed_dr"] = g.defaults / g.n
    lo, hi = sc.jeffreys_interval(g.defaults.values, g.n.values)
    g["emp_logit"] = logit(np.clip(g.observed_dr, 1e-4, 1 - 1e-4))
    g["emp_logit_lo"], g["emp_logit_hi"] = logit(np.clip(lo, 1e-4, 1)), logit(np.clip(hi, 0, 1 - 1e-4))
    g["model_logit_of_mean_pd"] = logit(g.model_pd)
    g["enhanced_logit_of_mean_pd"] = logit(g.enhanced_pd)
    return g


# ----------------------------------------------------------------------------
# B5. Replication of developer-reported statistics
# ----------------------------------------------------------------------------
def replicate_reported(artifact, dev: pd.DataFrame, dev_doc: dict, tol: float = 5e-5) -> dict:
    """Reproduce the developer's reported train/test AUCs from the frozen artifact.

    Tolerance is half a unit in the fourth decimal place (the precision at
    which the developer reported), i.e. the reproduced value must round to
    the reported value.
    """
    train, test = dev_split(dev)
    out = {"tolerance": tol}
    for nm, d in (("train", train), ("test", test)):
        a = float(roc_auc_score(d.default_12m, score(artifact, d)))
        rep = dev_doc["developer_reported_auc"][nm]
        out[nm] = {"n": int(len(d)), "reported_auc": rep, "reproduced_auc": a, "abs_diff": abs(a - rep),
                   "within_tolerance": bool(abs(a - rep) <= tol)}
    out["n_train_matches_doc"] = out["train"]["n"] == dev_doc["n_train"]
    out["n_test_matches_doc"] = out["test"]["n"] == dev_doc["n_test"]
    return out


# ----------------------------------------------------------------------------
# B6. Sensitivity
# ----------------------------------------------------------------------------
def elasticity_table(artifact, dev: pd.DataFrame, h: float = 0.1) -> pd.DataFrame:
    """One-at-a-time sensitivity: change in mean PD per 1 SD of each input.

    Central finite difference of the portfolio mean PD with a +/- h SD shift
    of one input at a time (clean dev rows), scaled to a 1 SD move. Also
    reports the full +/- 1 SD response, which captures the convexity of the
    logistic link. Binary inputs are reported as the 0 -> 1 switch.
    """
    d = dev[clean_mask(dev)]
    X, _ = prepare(d, artifact["income_fill"])
    base = expit(linear_predictor(artifact, X)).mean()
    rows = []
    for c in FEATURES:
        Xp, Xm = X.copy(), X.copy()
        if c == "channel_broker":
            Xp[c], Xm[c] = 1, 0
            up, dn = expit(linear_predictor(artifact, Xp)).mean(), expit(linear_predictor(artifact, Xm)).mean()
            rows.append({"feature": c, "sd": np.nan, "dPD_per_sd": up - dn, "pd_plus_1sd": up, "pd_minus_1sd": dn,
                         "note": "binary: all broker vs all non-broker"})
            continue
        sd = X[c].std()
        Xp[c], Xm[c] = X[c] + h * sd, X[c] - h * sd
        deriv = (expit(linear_predictor(artifact, Xp)).mean() - expit(linear_predictor(artifact, Xm)).mean()) / (2 * h)
        Xp[c], Xm[c] = X[c] + sd, X[c] - sd
        rows.append({"feature": c, "sd": sd, "dPD_per_sd": deriv,
                     "pd_plus_1sd": expit(linear_predictor(artifact, Xp)).mean(),
                     "pd_minus_1sd": expit(linear_predictor(artifact, Xm)).mean(), "note": ""})
    t = pd.DataFrame(rows)
    t["base_mean_pd"] = base
    t["rel_change_plus_1sd"] = t.pd_plus_1sd / base - 1
    t["rank"] = t.dPD_per_sd.abs().rank(ascending=False).astype(int)
    return t.sort_values("rank")


def sobol_indices(artifact, dev: pd.DataFrame, n: int = 20000, n_boot: int = 200, seed: int = 5) -> pd.DataFrame:
    """First-order and total Sobol indices of PD w.r.t. the nine inputs.

    Saltelli (2010) estimator for S_i and Jansen (1999) for S_Ti, with the
    inputs sampled independently from their empirical marginals on clean
    development data. The production inputs are close to mutually
    independent in this portfolio (all VIFs ~ 1), so the independence
    assumption is not material. S_Ti - S_i measures interaction through the
    logistic link. Bootstrap CIs resample the Monte-Carlo rows.
    """
    rng = np.random.default_rng(seed)
    d = dev[clean_mask(dev)]
    X, _ = prepare(d, artifact["income_fill"])
    V = X.values
    k = V.shape[1]

    def draw():
        return np.column_stack([V[rng.integers(0, len(V), n), j] for j in range(k)])

    A, B = draw(), draw()
    m = artifact["model"]
    f = lambda M: expit(m.intercept_[0] + M @ m.coef_[0])  # noqa: E731
    fA, fB = f(A), f(B)
    fAB = []
    for i in range(k):
        ABi = A.copy()
        ABi[:, i] = B[:, i]
        fAB.append(f(ABi))
    fAB = np.array(fAB)

    def est(idx):
        a, b, ab = fA[idx], fB[idx], fAB[:, idx]
        var = np.var(np.r_[a, b])
        s1 = np.mean(b * (ab - a), axis=1) / var
        st = 0.5 * np.mean((a - ab) ** 2, axis=1) / var
        return s1, st

    s1, st = est(np.arange(n))
    bs1, bst = [], []
    for _ in range(n_boot):
        idx = rng.integers(0, n, n)
        a, b = est(idx)
        bs1.append(a)
        bst.append(b)
    bs1, bst = np.array(bs1), np.array(bst)
    t = pd.DataFrame({"feature": FEATURES, "S1": s1, "S1_lo": np.percentile(bs1, 2.5, 0), "S1_hi": np.percentile(bs1, 97.5, 0),
                      "ST": st, "ST_lo": np.percentile(bst, 2.5, 0), "ST_hi": np.percentile(bst, 97.5, 0)})
    t["interaction_share"] = t.ST - t.S1
    return t.sort_values("ST", ascending=False)


def production_covariance(artifact, dev: pd.DataFrame) -> np.ndarray:
    """Covariance of the production coefficients (intercept first), from the
    information matrix on the developer's training split."""
    train, _ = dev_split(dev)
    X, _ = prepare(train, artifact["income_fill"])
    m = artifact["model"]
    beta = np.concatenate([m.intercept_, m.coef_[0]])
    return sc.wald_from_coefficients(beta, np.column_stack([np.ones(len(X)), X.values]))


def coefficient_perturbation(artifact, dev: pd.DataFrame, n_sim: int = 2000, seed: int = 9) -> tuple[pd.DataFrame, dict]:
    """Parameter-uncertainty sensitivity at the fixed approval cut-off.

    The cut-off is held at the production level (PD at the 70th percentile of
    development scores). For each coefficient two perturbations are run:

    * naive: shift beta_j by +/- 1 SE, all other coefficients fixed;
    * covariance-consistent: shift beta_j by +/- 1 SE and move the other
      coefficients by their conditional expectation given that shift,
      delta_{-j} = Sigma_{-j,j} / Sigma_jj * delta_j.

    The naive version is the textbook test but is misleading for inputs
    that are not centred (the intercept, FICO and log-income coefficients
    are strongly correlated with each other, so a one-at-a-time shift
    describes a model the data rule out). The covariance-consistent version
    is the statistically meaningful one. A joint Monte-Carlo draw
    beta ~ N(beta_hat, Sigma) gives the distribution of portfolio mean PD
    and approval rate implied by estimation error alone.
    """
    d = dev[clean_mask(dev)]
    X, _ = prepare(d, artifact["income_fill"])
    m = artifact["model"]
    beta = np.concatenate([m.intercept_, m.coef_[0]])
    cov = production_covariance(artifact, dev)
    se = np.sqrt(np.diag(cov))
    p0 = expit(linear_predictor(artifact, X))
    cutoff = float(np.quantile(score(artifact, dev), APPROVAL_RATE))
    app0 = p0 <= cutoff
    rows = []
    names = ["intercept"] + FEATURES
    for i, name in enumerate(names):
        for sgn in (+1, -1):
            r = {"parameter": name, "shift": "+1 SE" if sgn > 0 else "-1 SE", "se": se[i]}
            for mode in ("naive", "conditional"):
                b = beta.copy()
                delta = sgn * se[i]
                if mode == "naive":
                    b[i] += delta
                else:
                    b += cov[:, i] / cov[i, i] * delta
                p = expit(linear_predictor(artifact, X, b))
                app = p <= cutoff
                r[f"{mode}_mean_pd_change_bp"] = 1e4 * (p.mean() - p0.mean())
                r[f"{mode}_approval_change_pp"] = 100 * (app.mean() - app0.mean())
                r[f"{mode}_flipped_pct"] = 100 * (app != app0).mean()
            rows.append(r)
    rng = np.random.default_rng(seed)
    # Cholesky, not the default SVD: SVD sign conventions differ between linear-algebra libraries,
    # which changes the draws from one machine to another.
    draws = rng.multivariate_normal(beta, cov, n_sim, method="cholesky")
    Xd = np.column_stack([np.ones(len(X)), X.values])
    sims = expit(Xd @ draws.T)
    mean_pd = sims.mean(0)
    appr = (sims <= cutoff).mean(0)
    flips = (((sims <= cutoff) != app0[:, None]).mean(0))
    joint = {"n_sim": n_sim, "cutoff_pd": cutoff, "base_mean_pd": float(p0.mean()), "base_approval_rate": float(app0.mean()),
             "mean_pd_p05": float(np.percentile(mean_pd, 5)), "mean_pd_p95": float(np.percentile(mean_pd, 95)),
             "approval_p05": float(np.percentile(appr, 5)), "approval_p95": float(np.percentile(appr, 95)),
             "flipped_pct_median": float(100 * np.median(flips)), "flipped_pct_p95": float(100 * np.percentile(flips, 95)),
             "corr_intercept_fico": float(cov[0, 1] / np.sqrt(cov[0, 0] * cov[1, 1])),
             "corr_intercept_income_log": float(cov[0, 4] / np.sqrt(cov[0, 0] * cov[4, 4]))}
    return pd.DataFrame(rows), joint


def missing_income_counterfactual(artifact, ch: Challengers, samples: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Observed vs predicted PD for missing-income borrowers, production vs counterfactual.

    The counterfactual is the enhanced challenger (production recipe plus an
    income-missing indicator and the DTI hinge). Also reports how the
    production model's PD for these borrowers moves across the imputation
    value (p10 / median / p90 of development income): if no imputation value
    closes the gap, the issue is the absence of a missing indicator, not the
    choice of fill value.
    """
    dev = samples["dev"]
    rows = []
    for sname, d in samples.items():
        m = d.income.isna().values
        y = d.default_12m.values[m]
        sub = d[m]
        p0 = score(artifact, sub)
        p1 = ch.predict("enhanced_logit", sub, artifact)
        fills = {}
        for q in (0.10, 0.50, 0.90):
            alt = {**artifact, "income_fill": float(dev.income.quantile(q))}
            fills[f"production_pd_fill_p{int(q * 100)}"] = float(score(alt, sub).mean())
        D, n = int(y.sum()), int(m.sum())
        rows.append({"sample": sname, "n_missing": n, "share_missing": n / len(d), "observed_dr": D / n,
                     "production_pd": float(p0.mean()), "production_obs_over_pred": D / n / p0.mean(),
                     "enhanced_pd": float(p1.mean()), "enhanced_obs_over_pred": D / n / p1.mean(),
                     "jeffreys_p_under_production": sc.jeffreys_test(D, n, float(p0.mean())),
                     "excess_defaults_vs_production": D - float(p0.sum()), **fills})
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------
# B7. Fair lending
# ----------------------------------------------------------------------------
def fairness_extended(artifact, ch: Challengers, samples: dict[str, pd.DataFrame], cutoff: float) -> tuple[pd.DataFrame, dict]:
    """Group fairness metrics at the fixed production cut-off.

    Group B is the (simulated) protected class, group A the control group.
    Approval is the favourable outcome. Definitions (B minus A):
      * demographic-parity difference: P(approve | B) - P(approve | A)
      * equal-opportunity difference: P(approve | non-default, B) - P(approve | non-default, A)
        (the "qualified applicant" approval gap)
      * FPR gap: P(approve | default, B) - P(approve | default, A)
    AIR is reported at both the fixed production cut-off and a sample-
    specific 70% approval cut-off. Reliability tables by group support the
    calibration-by-group plot (differential validity check).
    """
    rows, rel = [], {}
    for sname, d in samples.items():
        y = d.default_12m.values
        g = d.protected_class.values
        for model in ("production", "no_region_logit"):
            p = ch.predict(model, d, artifact)
            cut = cutoff if model == "production" else float(np.quantile(ch.predict(model, samples["dev"], artifact), APPROVAL_RATE))
            app = p <= cut
            app70 = p <= np.quantile(p, APPROVAL_RATE)
            r = {"sample": sname, "model": model, "cutoff_pd": cut, "approval_rate": app.mean()}
            for cls in ("A", "B"):
                m = g == cls
                r[f"approval_{cls}"] = app[m].mean()
                r[f"tpr_{cls}"] = app[m & (y == 0)].mean()
                r[f"fpr_{cls}"] = app[m & (y == 1)].mean()
                r[f"obs_dr_{cls}"] = y[m].mean()
                r[f"mean_pd_{cls}"] = p[m].mean()
                r[f"calib_ratio_{cls}"] = y[m].mean() / p[m].mean()
                r[f"auc_{cls}"] = sc.auc_fast(y[m], p[m])
            r["air"] = sc.adverse_impact_ratio(app, g, "B", "A")
            r["air_at_70pct"] = sc.adverse_impact_ratio(app70, g, "B", "A")
            r["dp_diff"] = r["approval_B"] - r["approval_A"]
            r["eo_diff"] = r["tpr_B"] - r["tpr_A"]
            r["fpr_diff"] = r["fpr_B"] - r["fpr_A"]
            r["auc"] = sc.auc_fast(y, p)
            rows.append(r)
            if model == "production":
                rel[sname] = {cls: sc.reliability_table(y[g == cls], p[g == cls], 10) for cls in ("A", "B")}
    return pd.DataFrame(rows), rel


def proxy_and_marginal_effect(dev: pd.DataFrame, artifact) -> dict:
    """Is region_risk a proxy, and is it predictive conditional on protected class?

    1. Proxy strength: correlation of region_risk with class B and the AUC of
       region_risk alone in predicting class membership.
    2. Likelihood-ratio tests on clean development data:
       (a) region_risk given the other 8 inputs AND a class-B indicator.
           If significant, region_risk carries default signal beyond its
           correlation with the protected class (supports business
           justification, but does not remove the disparate-impact question).
       (b) class-B given all 9 production inputs. If NOT significant, the
           model's inputs fully absorb the class difference in default
           rates, i.e. there is no omitted-group miscalibration.
    3. Average marginal effect of region_risk on PD with delta-method SE,
       with and without class in the model; a large attenuation would mean
       region_risk is mostly standing in for class.
    """
    d = dev[clean_mask(dev)]
    X, _ = prepare(d, artifact["income_fill"])
    y = d.default_12m.values
    cls = (d.protected_class == "B").astype(float).values
    one = np.ones(len(d))

    def design(cols, with_class):
        mats = [one] + [X[c].values for c in cols] + ([cls] if with_class else [])
        return np.column_stack(mats)

    others = [c for c in FEATURES if c != "region_risk"]
    full = sc.fit_logit_irls(design(FEATURES, True), y)
    no_rr = sc.fit_logit_irls(design(others, True), y)
    no_cls = sc.fit_logit_irls(design(FEATURES, False), y)
    lr_rr = 2 * (full.loglik - no_rr.loglik)
    lr_cls = 2 * (full.loglik - no_cls.loglik)

    def ame(fit, Xd, j):
        mu = expit(Xd @ fit.beta)
        w = mu * (1 - mu)
        val = float(np.mean(w * fit.beta[j]))
        # gradient of AME wrt beta (delta method)
        grad = np.mean((w * (1 - 2 * mu) * fit.beta[j])[:, None] * Xd, axis=0)
        grad[j] += np.mean(w)
        return val, float(np.sqrt(grad @ fit.cov @ grad))

    j = 1 + FEATURES.index("region_risk")
    ame_with, se_with = ame(full, design(FEATURES, True), j)
    ame_without, se_without = ame(no_cls, design(FEATURES, False), j)
    jc = full.beta.shape[0] - 1
    return {
        "n": int(len(d)),
        "corr_region_risk_class_B": float(np.corrcoef(cls, d.region_risk)[0, 1]),
        "auc_region_risk_predicting_class_B": sc.auc_fast(cls.astype(int), d.region_risk.values),
        "mean_region_risk_A": float(d.region_risk[cls == 0].mean()),
        "mean_region_risk_B": float(d.region_risk[cls == 1].mean()),
        "raw_default_rate_A": float(y[cls == 0].mean()), "raw_default_rate_B": float(y[cls == 1].mean()),
        "lr_test_region_risk_given_class": {"stat": float(lr_rr), "dof": 1, "p_value": float(stats.chi2.sf(lr_rr, 1)),
                                            "coef": float(full.beta[j]), "se": float(full.se[j])},
        "lr_test_class_given_inputs": {"stat": float(lr_cls), "dof": 1, "p_value": float(stats.chi2.sf(lr_cls, 1)),
                                       "coef": float(full.beta[jc]), "se": float(full.se[jc])},
        "ame_region_risk_with_class": {"ame": ame_with, "se": se_with},
        "ame_region_risk_without_class": {"ame": ame_without, "se": se_without},
        "ame_attenuation_pct": float(100 * (1 - ame_with / ame_without)),
    }


# ----------------------------------------------------------------------------
# B9. ML challenger validation (how an ML model would be validated differently)
# ----------------------------------------------------------------------------
def importance_stability(artifact, ch: Challengers, n_boot: int = 25, n_repeats: int = 3, seed: int = 21) -> dict:
    """Bootstrap stability of permutation importance: GBM vs logistic recipe.

    For each bootstrap resample of the development training split, refit the
    model, then compute permutation importance (AUC drop) on the fixed
    development test split. An ML model whose importance ranking reshuffles
    across resamples cannot support stable adverse-action reason codes or a
    credible conceptual-soundness narrative.
    """
    rng = np.random.default_rng(seed)
    fill = ch.fill
    Xtr, _ = prepare(ch.train, fill)
    ytr = ch.train.default_12m.values
    Xte, _ = prepare(ch.test, fill)
    yte = ch.test.default_12m.values
    res = {"gbm": [], "logit": []}
    for b in range(n_boot):
        idx = rng.integers(0, len(Xtr), len(Xtr))
        mods = {"gbm": HistGradientBoostingClassifier(**{**GBM_PARAMS, "random_state": b}).fit(Xtr.iloc[idx], ytr[idx]),
                "logit": LogisticRegression(C=1e6, max_iter=5000, solver="newton-cholesky", tol=1e-10).fit(Xtr.iloc[idx], ytr[idx])}
        for k, mdl in mods.items():
            pi = permutation_importance(mdl, Xte, yte, scoring="roc_auc", n_repeats=n_repeats, random_state=b)
            res[k].append(pi.importances_mean)
    out = {}
    for k, arr in res.items():
        arr = np.array(arr)
        ranks = np.array([stats.rankdata(-r) for r in arr])
        rhos = [stats.spearmanr(arr[i], arr[j])[0] for i, j in itertools.combinations(range(len(arr)), 2)]
        top3 = np.argsort(-arr, axis=1)[:, :3]
        modal_top3 = set(np.argsort(-arr.mean(0))[:3])
        tbl = pd.DataFrame({"feature": FEATURES, "mean_importance": arr.mean(0), "sd_importance": arr.std(0, ddof=1),
                            "p05": np.percentile(arr, 5, 0), "p95": np.percentile(arr, 95, 0),
                            "mean_rank": ranks.mean(0), "rank_min": ranks.min(0), "rank_max": ranks.max(0)})
        tbl["cv"] = tbl.sd_importance / tbl.mean_importance.abs().clip(lower=1e-9)
        out[k] = {"table": tbl.sort_values("mean_importance", ascending=False),
                  "raw": arr,
                  "mean_pairwise_spearman": float(np.mean(rhos)),
                  "min_pairwise_spearman": float(np.min(rhos)),
                  "top3_set_stability": float(np.mean([set(t) == modal_top3 for t in top3]))}
    out["n_boot"] = n_boot
    out["n_repeats"] = n_repeats
    return out


def monotonicity_check(artifact, ch: Challengers, features=("fico", "dti", "utilization"),
                       n_grid: int = 25, n_ice: int = 1000, seed: int = 3, tol: float = 1e-6) -> tuple[pd.DataFrame, dict]:
    """Binned partial dependence and ICE-based monotonicity for GBM models.

    For each feature, a grid of n_grid quantiles (2.5%-97.5%) of clean dev
    data is used. Partial dependence (PD curve) is the mean predicted PD over
    n_ice sampled applicants with the feature set to each grid value. A
    violation is any step against the expected direction exceeding tol.
    Reported: number of PD-curve violations, the largest reversal, and the
    share of individual (ICE) curves with at least one reversal larger than
    0.5 pp -- the quantity that matters for an individual adverse-action
    explanation.
    """
    rng = np.random.default_rng(seed)
    d = ch.test[clean_mask(ch.test)]
    X, _ = prepare(d, ch.fill)
    Xs = X.iloc[rng.choice(len(X), min(n_ice, len(X)), replace=False)].reset_index(drop=True)
    models = {"production": artifact["model"], "gbm": ch.gbm, "gbm_monotone": ch.gbm_mono}
    rows, curves = [], {}
    for f in features:
        grid = np.unique(np.quantile(X[f], np.linspace(0.025, 0.975, n_grid)))
        sign = MONOTONE[f]
        for name, mdl in models.items():
            ice = np.empty((len(Xs), len(grid)))
            for gi, v in enumerate(grid):
                Xg = Xs.copy()
                Xg[f] = v
                ice[:, gi] = mdl.predict_proba(Xg)[:, 1]
            pdc = ice.mean(0)
            steps = np.diff(pdc) * sign
            ice_steps = np.diff(ice, axis=1) * sign
            rows.append({"feature": f, "model": name, "expected_direction": "increasing" if sign > 0 else "decreasing",
                         "pd_curve_violations": int((steps < -tol).sum()), "n_steps": len(steps),
                         "max_reversal_pp": float(100 * max(0.0, -steps.min())),
                         "ice_share_reversal_gt_50bp": float((ice_steps.min(1) < -0.005).mean()),
                         "pd_range_pp": float(100 * (pdc.max() - pdc.min()))})
            curves[(f, name)] = pd.DataFrame({"grid": grid, "pd": pdc})
    return pd.DataFrame(rows), curves


# ----------------------------------------------------------------------------
# B8. Ongoing monitoring plan
# ----------------------------------------------------------------------------
def monitoring_plan(baseline: dict) -> dict:
    """Machine-readable KPI thresholds for first-line monitoring.

    SR 26-2 ongoing monitoring: thresholds are set before the fact, each
    KPI has an owner, a frequency and an escalation path, and breaches
    trigger a documented response. Baselines are the development-sample
    values produced by this validation.
    """
    dev_auc, dev_ks = baseline["dev_auc"], baseline["dev_ks"]
    return {
        "model_id": "CR-PD-0142",
        "model_name": "Consumer PD Model v1.0",
        "guidance": "SR 26-2 / OCC Bulletin 2026-13 (ongoing monitoring component); bank Model Risk Management Policy",
        "effective_from": baseline["report_date"],
        "baseline_sample": "Development vintages 2023H1-2023H2",
        "baseline_values": baseline,
        "escalation_matrix": {
            "green": "No action; reported in quarterly model performance pack.",
            "amber": "Model owner root-cause analysis within 30 days; MRM notified; recorded in model inventory.",
            "red": "Escalate to Model Risk Committee within 10 business days; MRM decides on overlay, restricted use or accelerated revalidation.",
            "two_consecutive_amber": "Treated as red.",
        },
        "kpis": [
            {"kpi": "Score PSI (dev vs current quarter applications)", "metric": "psi", "green": "< 0.10", "amber": "0.10 - 0.25",
             "red": ">= 0.25", "frequency": "Monthly", "owner": "Retail Credit Analytics (model owner)", "escalation": "MRM"},
            {"kpi": "Characteristic stability (CSI), each input", "metric": "csi", "green": "< 0.10", "amber": "0.10 - 0.25",
             "red": ">= 0.25", "frequency": "Monthly", "owner": "Retail Credit Analytics", "escalation": "MRM"},
            {"kpi": "AUC decay vs development", "metric": "auc_dev - auc_current", "baseline": round(dev_auc, 4),
             "green": "< 0.03", "amber": "0.03 - 0.05", "red": ">= 0.05 or lower 95% CI below 0.80", "frequency": "Quarterly (12-month performance window)",
             "owner": "Retail Credit Analytics", "escalation": "MRM / Model Risk Committee"},
            {"kpi": "KS decay vs development", "metric": "ks_dev - ks_current", "baseline": round(dev_ks, 4),
             "green": "< 0.04", "amber": "0.04 - 0.07", "red": ">= 0.07", "frequency": "Quarterly", "owner": "Retail Credit Analytics", "escalation": "MRM"},
            {"kpi": "Calibration ratio (observed DR / mean PD), portfolio", "metric": "obs_over_pred", "green": "0.90 - 1.10",
             "amber": "0.80 - 0.90 or 1.10 - 1.20", "red": "< 0.80 or > 1.20", "frequency": "Quarterly", "owner": "Retail Credit Analytics", "escalation": "MRM"},
            {"kpi": "Calibration ratio, income-missing segment", "metric": "obs_over_pred", "green": "0.90 - 1.10",
             "amber": "0.80 - 0.90 or 1.10 - 1.20", "red": "< 0.80 or > 1.20", "frequency": "Quarterly", "owner": "Retail Credit Analytics", "escalation": "MRM",
             "note": "Segment KPI added because of finding F-01."},
            {"kpi": f"Calibration ratio, DTI > {baseline['dti_knot']:.2f} segment (data-selected knot)", "metric": "obs_over_pred", "green": "0.90 - 1.10",
             "amber": "0.80 - 0.90 or 1.10 - 1.20", "red": "< 0.80 or > 1.20", "frequency": "Quarterly", "owner": "Retail Credit Analytics", "escalation": "MRM",
             "note": "Segment KPI added because of finding F-02."},
            {"kpi": "Grade-level Jeffreys test (one-sided, under-estimation)", "metric": "count of red grades", "green": "0 red, <= 1 amber",
             "amber": "1 red or >= 2 amber", "red": ">= 2 red", "frequency": "Quarterly", "owner": "Retail Credit Analytics", "escalation": "MRM"},
            {"kpi": "Approval rate by segment (channel, income-missing, DTI band)", "metric": "approval rate change vs prior 4-quarter average",
             "green": "< 5 pp", "amber": "5 - 10 pp", "red": ">= 10 pp", "frequency": "Monthly", "owner": "Credit Policy", "escalation": "Credit Risk Committee"},
            {"kpi": "Adverse impact ratio (proxy-based, BISG or equivalent)", "metric": "air", "green": ">= 0.90", "amber": "0.80 - 0.90",
             "red": "< 0.80", "frequency": "Quarterly", "owner": "Fair Lending Compliance", "escalation": "Fair Lending Committee and MRM"},
            {"kpi": "Data quality: range-violation rate (FICO outside 300-850, DTI outside 0-1)", "metric": "rate", "green": "< 0.01%",
             "amber": "0.01% - 0.10%", "red": ">= 0.10%", "frequency": "Monthly", "owner": "Data Management / Model owner", "escalation": "MRM"},
            {"kpi": "Data quality: income missing rate", "metric": "rate", "baseline": round(baseline["income_missing_rate_dev"], 4),
             "green": "within +/- 2 pp of baseline", "amber": "2 - 5 pp", "red": "> 5 pp", "frequency": "Monthly", "owner": "Data Management / Model owner", "escalation": "MRM"},
            {"kpi": "Override rate (manual decisions against model)", "metric": "rate", "green": "< 5%", "amber": "5% - 10%", "red": ">= 10%",
             "frequency": "Monthly", "owner": "Credit Policy", "escalation": "MRM"},
        ],
    }
