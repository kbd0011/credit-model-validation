"""
Data access layer. Swap `load_portfolio` to point at a real dataset.

For Lending Club: default_12m from loan_status within 12 months of issue_d,
vintage from issue_d (half-years), and map fico_range_low, dti/100,
revol_util/100, annual_inc, inq_last_6mths, delinq_2yrs, emp_length to the
inputs used by model/develop_model.py::prepare.

For Home Credit Default Risk (Kaggle): rename TARGET -> default_12m and map
EXT_SOURCE_* / AMT_ANNUITY / AMT_INCOME_TOTAL to the model inputs. The
application table has no origination date, so a pseudo-vintage split must be
documented as a limitation (no true out-of-time test).

The validation code requires only the columns listed in data/make_data.py.
"""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PORTFOLIO = ROOT / "data" / "portfolio.csv"

DEV_VINTAGES = ["2023H1", "2023H2"]   # model development sample (in-time)
OOT_VINTAGES = ["2024H1", "2024H2"]   # out-of-time holdouts used by validation


def load_portfolio() -> pd.DataFrame:
    if not PORTFOLIO.exists():
        from data.make_data import make_portfolio
        make_portfolio().to_csv(PORTFOLIO, index=False)
    return pd.read_csv(PORTFOLIO)


def split(df: pd.DataFrame):
    dev = df[df.vintage.isin(DEV_VINTAGES)].copy()
    oot = {v: df[df.vintage == v].copy() for v in OOT_VINTAGES}
    return dev, oot
