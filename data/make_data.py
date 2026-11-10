"""
Synthetic consumer-loan portfolio used as the validation dataset.

WHY SYNTHETIC
-------------
This repository is a demonstration of an SR 11-7 / OCC 2011-12 independent
model validation. A public dataset (Home Credit Default Risk, Lending Club,
FICO HELOC) can be dropped in by replacing `load_portfolio()` in
`data/loader.py`; every validation test downstream is data-agnostic.

The synthetic data-generating process (DGP) below is documented in full so
that findings in the validation report can be traced to a known cause. It
deliberately contains realistic weaknesses that a validator should detect:

  1. Income is missing for ~12% of applicants, and missingness is correlated
     with default (thin-file / self-employed borrowers).
  2. The true relationship between debt-to-income (DTI) and default is
     non-linear (sharp increase above 0.43); the production model is linear
     in DTI, so calibration deteriorates in the tail.
  3. Vintage 2024H2 (the out-of-time sample) shifts toward lower FICO and
     higher utilization, so population stability (PSI) degrades.
  4. A zip-level "region_risk" variable is a partial proxy for a protected
     class, producing a modest adverse-impact ratio.

Columns
-------
loan_id, vintage, fico, dti, utilization, income, loan_amount, tenure_months,
inquiries_6m, delinq_24m, employment_years, region_risk, channel,
protected_class (simulated, used ONLY for fairness testing), default_12m
"""
from __future__ import annotations

import numpy as np
import pandas as pd

SEED = 20261109
N_PER_VINTAGE = {"2023H1": 14000, "2023H2": 14000, "2024H1": 14000, "2024H2": 12000}


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def make_portfolio(seed: int = SEED) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    frames = []
    for vintage, n in N_PER_VINTAGE.items():
        # Population shift in the out-of-time vintage (weakness 3)
        shift = vintage == "2024H2"
        fico = rng.normal(705 - (22 if shift else 0), 58, n).clip(480, 850)
        utilization = rng.beta(2.0, 4.0 if not shift else 2.8, n)
        dti = rng.beta(2.2, 4.0, n) * 0.9
        employment_years = rng.gamma(2.0, 3.0, n).clip(0, 40)
        income = np.exp(rng.normal(11.0, 0.45, n))  # ~ $60k median
        loan_amount = (income * rng.uniform(0.08, 0.45, n)).round(-2)
        tenure_months = rng.choice([36, 48, 60, 72], n, p=[0.35, 0.25, 0.3, 0.1])
        inquiries_6m = rng.poisson(1.2, n)
        delinq_24m = rng.poisson(0.25, n)
        channel = rng.choice(["branch", "online", "broker"], n, p=[0.4, 0.45, 0.15])

        # Protected class (simulated). region_risk is a partial proxy (weakness 4)
        protected_class = rng.choice(["A", "B"], n, p=[0.68, 0.32])
        region_risk = np.where(
            protected_class == "B",
            rng.normal(0.6, 0.25, n),
            rng.normal(0.4, 0.25, n),
        ).clip(0, 1)

        # True default process. Non-linear DTI effect (weakness 2).
        dti_kink = np.maximum(dti - 0.43, 0) * 6.0
        z = (
            -4.5
            - 0.028 * (fico - 700)
            + 2.4 * utilization
            + 1.6 * dti
            + dti_kink
            + 0.22 * inquiries_6m
            + 0.55 * np.minimum(delinq_24m, 3)
            - 0.035 * employment_years
            + 0.45 * region_risk
            + np.where(channel == "broker", 0.35, 0.0)
            - 0.15 * (np.log(income) - 11.0)
        )
        default = rng.binomial(1, _sigmoid(z))

        # Missing income correlated with default (weakness 1)
        p_missing = 0.08 + 0.18 * default
        income = np.where(rng.uniform(size=n) < p_missing, np.nan, income)

        frames.append(
            pd.DataFrame(
                {
                    "vintage": vintage,
                    "fico": fico.round(0),
                    "dti": dti.round(4),
                    "utilization": utilization.round(4),
                    "income": income.round(0),
                    "loan_amount": loan_amount,
                    "tenure_months": tenure_months,
                    "inquiries_6m": inquiries_6m,
                    "delinq_24m": delinq_24m,
                    "employment_years": employment_years.round(1),
                    "region_risk": region_risk.round(3),
                    "channel": channel,
                    "protected_class": protected_class,
                    "default_12m": default,
                }
            )
        )
    df = pd.concat(frames, ignore_index=True)
    df.insert(0, "loan_id", np.arange(1, len(df) + 1))
    # A handful of data-entry errors a data-quality review should catch
    bad = rng.choice(df.index, 25, replace=False)
    df.loc[bad[:10], "fico"] = 0
    df.loc[bad[10:], "dti"] = df.loc[bad[10:], "dti"] + 2.0
    return df


if __name__ == "__main__":
    out = make_portfolio()
    out.to_csv("data/portfolio.csv", index=False)
    print(out.shape, "default rate by vintage:")
    print(out.groupby("vintage")["default_12m"].mean().round(4))
