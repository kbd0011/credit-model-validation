"""
SECOND LINE OF DEFENSE: independent validation tests.

Each function maps to a section of the validation report and to an element
of SR 26-2 / OCC 2026-13 (which retains the three validation components of
its predecessor SR 11-7):

  data_quality        -> data review (conceptual soundness)
  replicate           -> independent re-implementation (conceptual soundness)
  conceptual_checks   -> sign/shape checks, variable-level evidence
  outcomes            -> outcomes analysis: discrimination + calibration
  stability           -> PSI / CSI (ongoing monitoring evidence)
  benchmark           -> challenger / benchmark models
  sensitivity         -> sensitivity and stress analysis
  fairness            -> fair-lending / disparate impact assessment

The production model is loaded from model/pd_model_v1.pkl and never refit
by these tests, except inside `replicate`, which re-implements the
developer's recipe independently to confirm it can be reproduced.
"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score, roc_curve

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from model.develop_model import FEATURES, prepare  # noqa: E402

EXPECTED_SIGNS = {
    "fico": -1, "dti": +1, "utilization": +1, "income_log": -1,
    "inquiries_6m": +1, "delinq_24m": +1, "employment_years": -1,
    "region_risk": +1, "channel_broker": +1,
}


def load_model():
    with open(ROOT / "model" / "pd_model_v1.pkl", "rb") as f:
        return pickle.load(f)


def score(artifact, df: pd.DataFrame) -> np.ndarray:
    X, _ = prepare(df, artifact["income_fill"])
    return artifact["model"].predict_proba(X)[:, 1]


# ----------------------------------------------------------------------------
# 1. Data quality
# ----------------------------------------------------------------------------
def data_quality(df: pd.DataFrame) -> dict:
    """Completeness, validity and informativeness of the input data.

    Conceptual soundness (SR 26-2): data used to develop and run the model
    must be relevant and of adequate quality. Missingness that is correlated with the
    outcome (informative missingness) is a model-specification issue, not
    only a data issue, and is tested explicitly.
    """
    out = {}
    out["n_rows"] = int(len(df))
    out["duplicate_loan_ids"] = int(df.loan_id.duplicated().sum())
    out["missing_pct"] = (df.isna().mean() * 100).round(2).to_dict()
    # Is income missingness informative?
    miss = df.income.isna()
    dr_missing = df.loc[miss, "default_12m"].mean()
    dr_present = df.loc[~miss, "default_12m"].mean()
    ct = pd.crosstab(miss, df.default_12m)
    chi2, p, _, _ = stats.chi2_contingency(ct)
    out["income_missing_vs_default"] = {
        "default_rate_when_missing": round(float(dr_missing), 4),
        "default_rate_when_present": round(float(dr_present), 4),
        "chi2_p_value": float(p),
    }
    out["range_violations"] = {
        "fico_below_300": int((df.fico < 300).sum()),
        "dti_above_1": int((df.dti > 1).sum()),
        "utilization_outside_0_1": int(((df.utilization < 0) | (df.utilization > 1)).sum()),
    }
    out["by_vintage"] = (
        df.groupby("vintage")
        .agg(n=("loan_id", "size"), default_rate=("default_12m", "mean"),
             mean_fico=("fico", "mean"), mean_util=("utilization", "mean"))
        .round(4)
        .reset_index()
        .to_dict(orient="records")
    )
    return out


# ----------------------------------------------------------------------------
# 2. Replication
# ----------------------------------------------------------------------------
def replicate(artifact, dev: pd.DataFrame) -> dict:
    """Independently re-implement the developer's recipe and compare.

    Model risk guidance (SR 26-2) expects the validator to confirm that the model in production is
    the model that was documented. The developer's recipe is re-run from
    the documentation (split seed, imputation, estimator) and coefficients
    and scores are compared with the frozen artifact.
    """
    train, test = dev_train_split(dev)
    Xtr, fill = prepare(train)
    repl = LogisticRegression(C=1e6, max_iter=5000, solver="newton-cholesky", tol=1e-10).fit(Xtr, train.default_12m)
    prod = artifact["model"]
    coef_diff = np.abs(repl.coef_[0] - prod.coef_[0])
    Xte, _ = prepare(test, fill)
    p_repl = repl.predict_proba(Xte)[:, 1]
    p_prod = prod.predict_proba(Xte)[:, 1]
    return {
        "income_fill_match": abs(fill - artifact["income_fill"]) < 1,
        "max_abs_coef_diff": float(coef_diff.max()),
        "max_abs_score_diff": float(np.abs(p_repl - p_prod).max()),
        "score_correlation": float(np.corrcoef(p_repl, p_prod)[0, 1]),
        "replicated_test_auc": round(float(roc_auc_score(test.default_12m, p_repl)), 4),
        "production_test_auc": round(float(roc_auc_score(test.default_12m, p_prod)), 4),
        "n_test": int(len(test)),
    }


# ----------------------------------------------------------------------------
# 3. Conceptual soundness checks
# ----------------------------------------------------------------------------
def _wald(artifact, X: pd.DataFrame) -> pd.DataFrame:
    """Standard errors from the observed information matrix.

    ``X`` must be the sample the coefficients were estimated on (the
    developer's training split); evaluating the information matrix on a
    larger sample would understate the standard errors.
    """
    model = artifact["model"]
    p = model.predict_proba(X)[:, 1]
    Xd = np.column_stack([np.ones(len(X)), X.values])
    W = p * (1 - p)
    H = (Xd * W[:, None]).T @ Xd
    cov = np.linalg.inv(H)
    se = np.sqrt(np.diag(cov))
    beta = np.concatenate([model.intercept_, model.coef_[0]])
    z = beta / se
    pval = 2 * (1 - stats.norm.cdf(np.abs(z)))
    return pd.DataFrame(
        {"variable": ["intercept"] + list(X.columns), "coef": beta.round(5),
         "std_err": se.round(5), "z": z.round(2), "p_value": pval.round(4)}
    )


def dev_train_split(dev: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The developer's documented 70/30 split (seed 7)."""
    rng = np.random.default_rng(7)
    mask = rng.uniform(size=len(dev)) < 0.7
    return dev[mask], dev[~mask]


def conceptual_checks(artifact, dev: pd.DataFrame, knot: float) -> dict:
    """Coefficient significance, sign, functional-form and collinearity checks.

    SR 26-2 conceptual soundness: the validator confirms that each input is
    statistically supported, enters in the economically expected direction,
    has an appropriate functional form, and is not redundant with others.
    """
    train, _ = dev_train_split(dev)
    Xtr, _ = prepare(train, artifact["income_fill"])
    wald = _wald(artifact, Xtr)
    X, _ = prepare(dev, artifact["income_fill"])
    coefs = dict(zip(FEATURES, artifact["model"].coef_[0]))
    sign_ok = {k: bool(np.sign(coefs[k]) == EXPECTED_SIGNS[k]) for k in FEATURES}

    # Linearity of DTI in the logit: binned empirical log-odds vs. model's linear term
    bins = pd.qcut(dev.dti, 12, duplicates="drop")
    g = dev.groupby(bins, observed=True).agg(dti=("dti", "mean"), dr=("default_12m", "mean"), n=("dti", "size"))
    g["emp_logit"] = np.log(g.dr.clip(1e-4, 1 - 1e-4) / (1 - g.dr.clip(1e-4, 1 - 1e-4)))
    # Compare linear fit on low-DTI bins vs. residual in top bins
    low = g[g.dti < knot]
    slope, intercept, *_ = stats.linregress(low.dti, low.emp_logit)
    g["linear_extrap"] = intercept + slope * g.dti
    g["residual"] = g.emp_logit - g.linear_extrap
    tail_resid = float(g[g.dti >= knot].residual.mean()) if (g.dti >= knot).any() else 0.0

    # Multicollinearity: VIF
    vif = {}
    Xv = X.values
    for i, c in enumerate(X.columns):
        others = np.delete(Xv, i, axis=1)
        others = np.column_stack([np.ones(len(Xv)), others])
        beta, *_ = np.linalg.lstsq(others, Xv[:, i], rcond=None)
        resid = Xv[:, i] - others @ beta
        r2 = 1 - resid.var() / Xv[:, i].var()
        vif[c] = round(float(1 / max(1 - r2, 1e-9)), 3)

    return {
        "wald_table": wald.to_dict(orient="records"),
        "sign_checks": sign_ok,
        "dti_linearity": {
            "bins": g.reset_index(drop=True).round(4).to_dict(orient="records"),
            "mean_tail_residual_logit": round(tail_resid, 3),
            "knot": knot,
        },
        "vif": vif,
    }


# ----------------------------------------------------------------------------
# 4. Outcomes analysis
# ----------------------------------------------------------------------------
def ks_stat(y, p):
    fpr, tpr, _ = roc_curve(y, p)
    return float(np.max(tpr - fpr))


def hosmer_lemeshow(y, p, g=10):
    df = pd.DataFrame({"y": y, "p": p})
    df["bin"] = pd.qcut(df.p, g, duplicates="drop")
    grp = df.groupby("bin", observed=True).agg(obs=("y", "sum"), exp=("p", "sum"), n=("y", "size"))
    hl = (((grp.obs - grp.exp) ** 2) / (grp.exp * (1 - grp.exp / grp.n))).sum()
    dof = len(grp) - 2
    return float(hl), int(dof), float(1 - stats.chi2.cdf(hl, dof)), grp


def calibration_slope_intercept(y, p):
    """Logistic recalibration: logit(y) ~ a + b*logit(p). Ideal a=0, b=1."""
    lp = np.log(p / (1 - p)).reshape(-1, 1)
    m = LogisticRegression(C=1e6, max_iter=2000, solver="newton-cholesky", tol=1e-10).fit(lp, y)
    return float(m.intercept_[0]), float(m.coef_[0][0])


def outcomes(artifact, samples: dict[str, pd.DataFrame]) -> dict:
    """Discrimination and calibration on each sample (SR 26-2 outcomes analysis)."""
    res = {}
    for name, d in samples.items():
        y = d.default_12m.values
        p = score(artifact, d)
        hl, dof, hlp, grp = hosmer_lemeshow(y, p)
        a, b = calibration_slope_intercept(y, p)
        deciles = pd.DataFrame({"y": y, "p": p})
        deciles["decile"] = pd.qcut(deciles.p, 10, labels=False, duplicates="drop") + 1
        dec = deciles.groupby("decile").agg(n=("y", "size"), predicted=("p", "mean"), observed=("y", "mean")).round(4)
        auc = roc_auc_score(y, p)
        res[name] = {
            "n": int(len(d)),
            "default_rate": round(float(y.mean()), 4),
            "mean_pd": round(float(p.mean()), 4),
            "auc": round(float(auc), 4),
            "gini": round(float(2 * auc - 1), 4),
            "ks": round(ks_stat(y, p), 4),
            "brier": round(float(brier_score_loss(y, p)), 4),
            "log_loss": round(float(log_loss(y, p)), 4),
            "hosmer_lemeshow": {"stat": round(hl, 2), "dof": dof, "p_value": round(hlp, 4)},
            "calibration_intercept": round(a, 3),
            "calibration_slope": round(b, 3),
            "deciles": dec.reset_index().to_dict(orient="records"),
        }
    return res


# ----------------------------------------------------------------------------
# 5. Stability
# ----------------------------------------------------------------------------
def psi(base: np.ndarray, comp: np.ndarray, bins=10) -> float:
    edges = np.quantile(base, np.linspace(0, 1, bins + 1))
    edges[0], edges[-1] = -np.inf, np.inf
    b = np.histogram(base, edges)[0] / len(base)
    c = np.histogram(comp, edges)[0] / len(comp)
    b, c = np.clip(b, 1e-6, None), np.clip(c, 1e-6, None)
    return float(np.sum((c - b) * np.log(c / b)))


def stability(artifact, dev: pd.DataFrame, oot: dict[str, pd.DataFrame]) -> dict:
    """Score PSI and characteristic CSI vs development (ongoing-monitoring evidence).

    For the binary channel_broker input the CSI entry is the absolute change
    in the broker share, since a 2-bin PSI is uninformative at this scale.
    """
    base_scores = score(artifact, dev)
    Xb, _ = prepare(dev, artifact["income_fill"])
    out = {}
    for name, d in oot.items():
        Xc, _ = prepare(d, artifact["income_fill"])
        csi = {c: round(psi(Xb[c].values, Xc[c].values), 4) for c in FEATURES if Xb[c].nunique() > 2}
        csi["channel_broker"] = round(float(abs(Xc.channel_broker.mean() - Xb.channel_broker.mean())), 4)
        out[name] = {"score_psi": round(psi(base_scores, score(artifact, d)), 4), "csi": csi}
    return out


# ----------------------------------------------------------------------------
# 6. Benchmark / challenger models
# ----------------------------------------------------------------------------
def _enhanced_features(df: pd.DataFrame, fill: float, knot: float) -> pd.DataFrame:
    """Validator's minimal-fix challenger: missing indicator + DTI hinge at a
    data-selected knot (see advanced.select_dti_knot)."""
    X, _ = prepare(df, fill)
    X = X.copy()
    X["income_missing"] = df.income.isna().astype(int).values
    X["dti_hinge"] = np.maximum(df.dti.values - knot, 0)
    return X


def benchmark(artifact, dev: pd.DataFrame, oot: dict[str, pd.DataFrame], knot: float) -> dict:
    """Challenger AUCs (point estimates). See advanced.benchmark_delong for tests."""
    train, test = dev_train_split(dev)
    fill = artifact["income_fill"]

    Xtr, _ = prepare(train, fill)
    gbm = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, max_depth=4, random_state=0)
    gbm.fit(Xtr, train.default_12m)

    Xtr_e = _enhanced_features(train, fill, knot)
    enh = LogisticRegression(C=1e6, max_iter=5000, solver="newton-cholesky", tol=1e-10).fit(Xtr_e, train.default_12m)

    samples = {"dev_test": test, **oot}
    rows = []
    for name, d in samples.items():
        y = d.default_12m
        Xd, _ = prepare(d, fill)
        rows.append({
            "sample": name,
            "production_auc": round(float(roc_auc_score(y, score(artifact, d))), 4),
            "enhanced_logit_auc": round(float(roc_auc_score(y, enh.predict_proba(_enhanced_features(d, fill, knot))[:, 1])), 4),
            "gbm_challenger_auc": round(float(roc_auc_score(y, gbm.predict_proba(Xd)[:, 1])), 4),
        })
    enh_coefs = dict(zip(Xtr_e.columns, enh.coef_[0].round(4).tolist()))
    return {"table": rows, "enhanced_logit_coefs": enh_coefs}


# ----------------------------------------------------------------------------
# 7. Sensitivity and stress
# ----------------------------------------------------------------------------
def sensitivity(artifact, dev: pd.DataFrame) -> dict:
    """+/- 1 SD shocks, a combined stress scenario and imputation sensitivity.

    Shock sizes use standard deviations from rows that pass range edits, so
    that the planted data-entry errors (FICO = 0, DTI > 1) do not inflate
    them.
    """
    clean = dev[(dev.fico >= 300) & (dev.dti <= 1)]
    base = score(artifact, dev)
    out = {"base_mean_pd": round(float(base.mean()), 4), "one_sd_shocks": {}}
    for col, raw in [("fico", "fico"), ("dti", "dti"), ("utilization", "utilization"),
                     ("inquiries_6m", "inquiries_6m"), ("delinq_24m", "delinq_24m"),
                     ("employment_years", "employment_years"), ("region_risk", "region_risk")]:
        sd = clean[raw].std()
        up = dev.copy(); up[raw] = up[raw] + sd
        dn = dev.copy(); dn[raw] = dn[raw] - sd
        out["one_sd_shocks"][col] = {
            "plus_1sd_mean_pd": round(float(score(artifact, up).mean()), 4),
            "minus_1sd_mean_pd": round(float(score(artifact, dn).mean()), 4),
        }
    # Macro-style stress: FICO -30, utilization +0.10, inquiries +1
    s = dev.copy()
    s["fico"] -= 30; s["utilization"] = (s.utilization + 0.10).clip(0, 1); s["inquiries_6m"] += 1
    out["stress_scenario"] = {
        "description": "FICO -30, utilization +0.10, inquiries +1",
        "mean_pd": round(float(score(artifact, s).mean()), 4),
        "relative_increase": round(float(score(artifact, s).mean() / base.mean() - 1), 3),
    }
    # Imputation sensitivity: fill missing income at p10 vs p90 instead of median
    res = {}
    for q in (0.10, 0.50, 0.90):
        alt = {**artifact, "income_fill": float(dev.income.quantile(q))}
        res[f"fill_p{int(q*100)}"] = round(float(score(alt, dev[dev.income.isna()]).mean()), 4)
    out["income_imputation_sensitivity_missing_rows"] = res
    return out


# ----------------------------------------------------------------------------
# 8. Fairness / fair lending
# ----------------------------------------------------------------------------
def fairness(artifact, samples: dict[str, pd.DataFrame], approval_rate=0.70) -> dict:
    """Adverse impact ratio at a sample-specific 70% approval rate, plus
    within-class AUC and calibration (differential validity)."""
    out = {}
    for name, d in samples.items():
        p = score(artifact, d)
        cutoff = float(np.quantile(p, approval_rate))  # approve lowest-risk 70%
        approved = p <= cutoff
        rows = []
        for cls in sorted(d.protected_class.unique()):
            m = (d.protected_class == cls).values
            y = d.default_12m.values[m]
            rows.append({
                "class": cls, "n": int(m.sum()),
                "approval_rate": round(float(approved[m].mean()), 4),
                "observed_default_rate": round(float(y.mean()), 4),
                "mean_pd": round(float(p[m].mean()), 4),
                "auc_within_class": round(float(roc_auc_score(y, p[m])), 4),
                "calibration_ratio_obs_over_pred": round(float(y.mean() / p[m].mean()), 3),
            })
        rates = {r["class"]: r["approval_rate"] for r in rows}
        air = rates["B"] / rates["A"]
        corr = float(np.corrcoef((d.protected_class == "B").astype(int), d.region_risk)[0, 1])
        out[name] = {"cutoff_pd": round(cutoff, 4), "by_class": rows,
                     "adverse_impact_ratio_B_over_A": round(float(air), 3),
                     "region_risk_corr_with_class_B": round(corr, 3)}
    return out
