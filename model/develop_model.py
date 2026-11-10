"""
FIRST LINE OF DEFENSE: the "production" probability-of-default (PD) model.

This script stands in for the model development team. It fits a logistic
regression PD model on the 2023 vintages, freezes it, and writes the
developer documentation that the validator will review. The validator must
NOT modify this file; everything in validation/ treats the model as a black
box handed over by another team.

Deliberate development choices a validator should challenge:
  - Income is median-imputed with no missing indicator.
  - DTI enters linearly.
  - region_risk is included without a fair-lending review.
  - No out-of-time test was performed by the developer.
"""
from __future__ import annotations

import json
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

ROOT = Path(__file__).resolve().parents[1]
FEATURES = [
    "fico", "dti", "utilization", "income_log", "inquiries_6m",
    "delinq_24m", "employment_years", "region_risk", "channel_broker",
]


def prepare(df: pd.DataFrame, income_fill: float | None = None):
    """Developer's feature pipeline. Returns X, fitted fill value."""
    X = pd.DataFrame(index=df.index)
    X["fico"] = df["fico"]
    X["dti"] = df["dti"]
    X["utilization"] = df["utilization"]
    inc = df["income"]
    if income_fill is None:
        income_fill = float(inc.median())
    X["income_log"] = np.log(inc.fillna(income_fill))
    X["inquiries_6m"] = df["inquiries_6m"]
    X["delinq_24m"] = df["delinq_24m"]
    X["employment_years"] = df["employment_years"]
    X["region_risk"] = df["region_risk"]
    X["channel_broker"] = (df["channel"] == "broker").astype(int)
    return X[FEATURES], income_fill


def develop():
    import sys
    sys.path.insert(0, str(ROOT))
    from data.loader import load_portfolio, split

    df = load_portfolio()
    dev, _ = split(df)
    rng = np.random.default_rng(7)
    mask = rng.uniform(size=len(dev)) < 0.7
    train, test = dev[mask], dev[~mask]

    Xtr, fill = prepare(train)
    Xte, _ = prepare(test, fill)
    model = LogisticRegression(C=1e6, max_iter=2000, solver="newton-cholesky", tol=1e-10)  # effectively unpenalised
    model.fit(Xtr, train["default_12m"])

    auc_tr = roc_auc_score(train["default_12m"], model.predict_proba(Xtr)[:, 1])
    auc_te = roc_auc_score(test["default_12m"], model.predict_proba(Xte)[:, 1])

    artifact = {"model": model, "income_fill": fill, "features": FEATURES}
    (ROOT / "model").mkdir(exist_ok=True)
    with open(ROOT / "model" / "pd_model_v1.pkl", "wb") as f:
        pickle.dump(artifact, f)

    coefs = dict(zip(FEATURES, model.coef_[0].round(5).tolist()))
    dev_doc = {
        "model_name": "Consumer PD Model v1.0",
        "owner": "Retail Credit Analytics (1st line)",
        "purpose": "12-month probability of default for unsecured consumer loans; "
                   "used in underwriting cut-off and risk-based pricing.",
        "methodology": "Logistic regression, unpenalised, 9 predictors.",
        "development_sample": "Vintages 2023H1-2023H2, 70/30 random split",
        "n_train": int(len(train)), "n_test": int(len(test)),
        "intercept": float(model.intercept_[0]),
        "coefficients": coefs,
        "income_imputation": f"median imputation, fill={fill:.0f}, no missing indicator",
        "developer_reported_auc": {"train": round(auc_tr, 4), "test": round(auc_te, 4)},
        "out_of_time_testing": "none performed",
        "fair_lending_review": "not documented",
        "monitoring_plan": "annual review",
    }
    with open(ROOT / "model" / "developer_documentation.json", "w") as f:
        json.dump(dev_doc, f, indent=2)
    print(json.dumps(dev_doc, indent=2))


if __name__ == "__main__":
    develop()
