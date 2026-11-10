"""
Run the full independent validation of Consumer PD Model v1.0 end to end.

Usage:  python -m validation.run_validation      (from the repository root)

Writes
  outputs/tables/*.json, *.csv     every numerical result cited in the report
  outputs/figures/*.png            300 dpi figures
  outputs/monitoring_thresholds.json
  outputs/summary.json             headline numbers used by the report builder
  outputs/run_manifest.json        seeds, library versions, SHA-256 of inputs

All randomness is seeded; two runs on the same inputs produce identical
outputs (bar timestamps in the manifest).
"""
from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from data.loader import DEV_VINTAGES, OOT_VINTAGES, load_portfolio, split  # noqa: E402
from model.develop_model import FEATURES  # noqa: E402
from validation import advanced as A  # noqa: E402
from validation import figures as F  # noqa: E402
from validation import tests as T  # noqa: E402

OUT = ROOT / "outputs"
TAB = OUT / "tables"
FIG = OUT / "figures"
N_BOOT = 1000
N_BOOT_IMPORTANCE = 20
SEEDS = {"data_generation": 20261109, "developer_split": 7, "bootstrap_discrimination": 11, "sobol": 5,
         "coef_simulation": 9, "importance_bootstrap": 21, "ice_sample": 3, "gbm": 0}
REPORT_DATE = "2026-11-09"


# ----------------------------------------------------------------------------
def _default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, pd.DataFrame):
        return o.to_dict(orient="records")
    if isinstance(o, pd.Interval):
        return str(o)
    raise TypeError(type(o))


def wjson(name: str, obj) -> None:
    with open(TAB / f"{name}.json", "w") as f:
        json.dump(obj, f, indent=2, default=_default)


def wtab(name: str, df: pd.DataFrame) -> None:
    df.to_csv(TAB / f"{name}.csv", index=False)
    wjson(name, df)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        return "not under version control (see file hashes)"


# ----------------------------------------------------------------------------
def main() -> dict:
    t0 = time.time()
    TAB.mkdir(parents=True, exist_ok=True)
    FIG.mkdir(parents=True, exist_ok=True)
    for old in FIG.glob("fig*.png"):  # figure numbers are assigned per run; drop stale files
        old.unlink()
    fw = F.FigureWriter(FIG)

    df = load_portfolio()
    dev, oot = split(df)
    artifact = T.load_model()
    dev_doc = json.loads((ROOT / "model" / "developer_documentation.json").read_text())
    knot_sel = A.select_dti_knot(artifact, dev)
    knot = knot_sel["knot"]
    tail = A.dti_tail_threshold(dev)
    knot_sel["dti_tail_threshold_p90"] = tail
    knot_sel["segment_names"] = {"dti_le_knot": f"DTI <= {knot:.2f}", "dti_gt_knot": f"DTI > {knot:.2f}", "dti_tail": f"DTI > {tail:.2f}"}
    knot_sel["n_dev_clean"] = int(A.clean_mask(dev).sum())
    ch = A.fit_challengers(artifact, dev, knot)
    samples = {"dev": dev, **oot}
    by_vintage = {v: df[df.vintage == v] for v in DEV_VINTAGES + OOT_VINTAGES}
    cutoff = float(np.quantile(T.score(artifact, dev), A.APPROVAL_RATE))
    S: dict = {"report_date": REPORT_DATE, "approval_cutoff_pd": cutoff}
    log = []

    def step(msg):
        log.append(f"[{time.time() - t0:6.1f}s] {msg}")
        print(log[-1], flush=True)

    # 1. Data quality ------------------------------------------------------------
    dq = T.data_quality(df)
    dq["income_missing_by_vintage"] = (df.assign(miss=df.income.isna()).groupby("vintage")
                                       .agg(n=("miss", "size"), missing_rate=("miss", "mean")).reset_index().to_dict("records"))
    dq["range_violations_by_vintage"] = (df.assign(bad_fico=df.fico < 300, bad_dti=df.dti > 1).groupby("vintage")
                                         [["bad_fico", "bad_dti"]].sum().reset_index().to_dict("records"))
    dq["range_violations_in_dev_train"] = int((~A.clean_mask(ch.train)).sum())
    bad = df[~A.clean_mask(df)]
    dq["pd_on_range_violations"] = {"fico_zero_mean_pd": float(T.score(artifact, bad[bad.fico < 300]).mean()),
                                    "dti_gt1_mean_pd": float(T.score(artifact, bad[bad.dti > 1]).mean())}
    wjson("data_quality", dq)
    miss_rows = []
    from validation.stats_core import jeffreys_interval
    for v, d in by_vintage.items():
        m = d.income.isna()
        k, n = int(d.default_12m[m].sum()), int(m.sum())
        lo, hi = jeffreys_interval(k, n)
        miss_rows.append({"vintage": v, "dr_missing": k / n, "dr_present": d.default_12m[~m].mean(), "lo": float(lo), "hi": float(hi)})
    miss_df = pd.DataFrame(miss_rows)
    wtab("income_missing_by_vintage", miss_df)
    step("data quality")

    # 2. Replication -------------------------------------------------------------
    rep = T.replicate(artifact, dev)
    rep_reported = A.replicate_reported(artifact, dev, dev_doc)
    wjson("replication", {"independent_refit": rep, "reported_auc_reproduction": rep_reported})
    step("replication")

    # 3. Conceptual soundness ---------------------------------------------------
    wjson("knot_selection", knot_sel)
    cc = T.conceptual_checks(artifact, dev, knot)
    wjson("conceptual_soundness", cc)
    wtab("wald_table", pd.DataFrame(cc["wald_table"]))
    iv_sum, iv_tabs = A.woe_iv_all(dev)
    wtab("woe_iv_summary", iv_sum)
    wjson("woe_tables", {k: v for k, v in iv_tabs.items()})
    prof = {f: A.binned_logit_profile(artifact, ch, dev, f) for f in ("dti", "fico", "utilization")}
    for f, g in prof.items():
        wtab(f"binned_logit_{f}", g)
    step("conceptual soundness")

    # 4. Outcomes ---------------------------------------------------------------
    outc = T.outcomes(artifact, {"dev": dev, "dev_train": ch.train, "dev_test": ch.test, **oot})
    wjson("outcomes_baseline", outc)
    for k, v in outc.items():
        pd.DataFrame(v["deciles"]).to_csv(TAB / f"deciles_{k}.csv", index=False)
    disc = A.discrimination_with_ci(artifact, {"dev": dev, "dev_test": ch.test, **by_vintage}, n_boot=N_BOOT, seed=SEEDS["bootstrap_discrimination"])
    wtab("discrimination_ci", disc)
    cal, rel = A.calibration_suite(artifact, samples)
    wtab("calibration_tests", cal)
    for k, v in rel.items():
        wtab(f"reliability_{k}", v)
    edges = A.master_scale(artifact, dev)
    wjson("master_scale", {"n_grades": A.N_GRADES, "pd_upper_bounds": edges.tolist() + [1.0], "method": "equal-population quantiles of development PD"})
    gb = A.grade_backtest(artifact, samples, edges)
    wtab("grade_backtest", gb)
    mig = A.grade_migration(artifact, ch, dev, oot["2024H2"], edges)
    wtab("grade_mix_dev_vs_2024H2", mig["grade_mix"])
    mig["reclass_counts"].to_csv(TAB / "reclassification_production_vs_enhanced_2024H2.csv")
    wjson("grade_migration_summary", {"grade_psi": mig["grade_psi"], "share_same_grade": mig["share_same_grade"],
                                      "share_within_one_grade": mig["share_within_one_grade"],
                                      "n_moved_2plus": mig["n_moved_2plus"], "share_2plus_income_missing": mig["share_2plus_income_missing"],
                                      "share_2plus_to_riskier": mig["share_2plus_to_riskier"],
                                      "reclass_counts": mig["reclass_counts"].values.tolist()})
    seg = A.segment_calibration(artifact, ch, samples, A.make_segments(knot, tail))
    wtab("segment_calibration", seg)
    step("outcomes analysis")

    # 5. Stability --------------------------------------------------------------
    stab = T.stability(artifact, dev, oot)
    wjson("stability", stab)
    rows = [{"sample": s, "variable": "SCORE", "psi": v["score_psi"]} for s, v in stab.items()]
    rows += [{"sample": s, "variable": k, "psi": x} for s, v in stab.items() for k, x in v["csi"].items()]
    wtab("psi_csi", pd.DataFrame(rows))
    step("stability")

    # 6. Benchmarking -------------------------------------------------------------
    bench = A.benchmark_delong(artifact, ch, {"dev_test": ch.test, **oot})
    wtab("benchmark_delong", bench)
    wjson("enhanced_logit_coefficients", {"intercept": float(ch.enhanced.intercept_[0]),
                                          **dict(zip(A._enhanced_features(dev.head(5), ch.fill, knot).columns, ch.enhanced.coef_[0].tolist()))})
    step("benchmarking")

    # 7. Sensitivity ------------------------------------------------------------
    sens = T.sensitivity(artifact, dev)
    wjson("sensitivity_baseline", sens)
    el = A.elasticity_table(artifact, dev)
    wtab("elasticity", el)
    sob = A.sobol_indices(artifact, dev, seed=SEEDS["sobol"])
    wtab("sobol_indices", sob)
    cp, cpj = A.coefficient_perturbation(artifact, dev, seed=SEEDS["coef_simulation"])
    wtab("coefficient_perturbation", cp)
    wjson("coefficient_uncertainty_joint", cpj)
    mi = A.missing_income_counterfactual(artifact, ch, samples)
    wtab("missing_income_counterfactual", mi)
    step("sensitivity")

    # 8. Fair lending -----------------------------------------------------------
    fair_base = T.fairness(artifact, samples)
    wjson("fairness_baseline", fair_base)
    fx, frel = A.fairness_extended(artifact, ch, samples, cutoff)
    wtab("fairness_extended", fx)
    wjson("fairness_reliability_by_group", {s: {c: t for c, t in v.items()} for s, v in frel.items()})
    proxy = A.proxy_and_marginal_effect(dev, artifact)
    wjson("proxy_marginal_effect", proxy)
    step("fair lending")

    # 9. ML challenger validation ----------------------------------------------
    imp = A.importance_stability(artifact, ch, n_boot=N_BOOT_IMPORTANCE, seed=SEEDS["importance_bootstrap"])
    for k in ("gbm", "logit"):
        wtab(f"importance_stability_{k}", imp[k]["table"])
    wjson("importance_stability_summary", {k: {kk: vv for kk, vv in imp[k].items() if kk not in ("table", "raw")} for k in ("gbm", "logit")}
          | {"n_boot": imp["n_boot"], "n_repeats": imp["n_repeats"]})
    mono, curves = A.monotonicity_check(artifact, ch, seed=SEEDS["ice_sample"])
    wtab("monotonicity", mono)
    step("ML challenger validation")


    # Figures, numbered in order of appearance in the report -----------------
    F.vintage_profile(fw, pd.DataFrame(dq["by_vintage"]), miss_df)
    F.binned_logit(fw, prof["dti"], "dti", "DTI", "dti_functional_form", hinge=knot)
    F.knot_profile(fw, knot_sel)
    F.binned_logit(fw, prof["fico"], "fico", "FICO", "fico_functional_form")
    F.iv_bars(fw, iv_sum)
    F.roc_curves(fw, {k: (d.default_12m.values, T.score(artifact, d)) for k, d in samples.items()},
                 {k: f"{outc[k]['auc']:.4f}" for k in samples})
    F.discrimination_trend(fw, disc[disc["sample"].isin(DEV_VINTAGES + OOT_VINTAGES)].reset_index(drop=True))
    F.reliability(fw, rel, cal)
    F.grade_backtest(fw, gb, ["dev", "2024H1", "2024H2"])
    F.segment_ratio(fw, seg, ["dev", "2024H1", "2024H2"])
    F.benchmark_forest(fw, bench)
    F.elasticity(fw, el)
    F.sobol(fw, sob)
    F.missing_income(fw, mi)
    F.psi_csi(fw, stab)
    F.score_distribution(fw, {k: T.score(artifact, d) for k, d in samples.items()})
    F.grade_mix(fw, mig["grade_mix"], mig["grade_psi"])
    F.fairness_tradeoff(fw, fx)
    F.calibration_by_group(fw, frel, "2024H2")
    F.importance_stability(fw, imp, FEATURES)
    F.monotonicity(fw, curves, mono)
    step("figures")

    # 10. Monitoring plan ------------------------------------------------------
    d0 = disc.set_index("sample")
    baseline = {"report_date": REPORT_DATE, "dti_knot": knot, "dev_auc": float(d0.loc["dev", "auc"]), "dev_ks": float(d0.loc["dev", "ks"]),
                "dev_mean_pd": float(cal.set_index("sample").loc["dev", "mean_pd"]),
                "approval_cutoff_pd": cutoff, "income_missing_rate_dev": float(dev.income.isna().mean()),
                "air_dev": float(fx[(fx.model == "production") & (fx["sample"] == "dev")].air.iloc[0])}
    plan = A.monitoring_plan(baseline)
    (OUT / "monitoring_thresholds.json").write_text(json.dumps(plan, indent=2, default=_default))
    step("monitoring plan")

    # Summary for the report ----------------------------------------------------
    def r(sample, col, t=disc):
        return float(t.set_index("sample").loc[sample, col])

    S.update({
        "n_total": int(len(df)), "n_dev": int(len(dev)), "n_oot": {k: int(len(v)) for k, v in oot.items()},
        "auc": {s: {"auc": r(s, "auc"), "lo": r(s, "auc_lo"), "hi": r(s, "auc_hi"), "ks": r(s, "ks"), "ks_lo": r(s, "ks_lo"), "ks_hi": r(s, "ks_hi"),
                    "gini": r(s, "gini"), "gini_lo": r(s, "gini_lo"), "gini_hi": r(s, "gini_hi")} for s in disc["sample"]},
        "psi_2024H1": stab["2024H1"]["score_psi"], "psi_2024H2": stab["2024H2"]["score_psi"],
        "hl_p": {s: float(cal.set_index("sample").loc[s, "hl_p"]) for s in samples},
        "air_fixed_cutoff": {s: float(fx[(fx.model == "production") & (fx["sample"] == s)].air.iloc[0]) for s in samples},
        "delong": bench.to_dict("records"),
        "missing_income": mi.to_dict("records"),
        "grade_red_count_oot": int(((gb["sample"] != "dev") & (gb.traffic_light == "red")).sum()),
        "figures": fw.index,
    })
    wjson("summary", S)
    (OUT / "summary.json").write_text(json.dumps(S, indent=2, default=_default))

    import matplotlib
    import scipy
    import sklearn
    manifest = {
        "run_date_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "report_date": REPORT_DATE,
        "git_commit": git_commit(), "python": platform.python_version(),
        "libraries": {"numpy": np.__version__, "pandas": pd.__version__, "scikit-learn": sklearn.__version__,
                      "scipy": scipy.__version__, "matplotlib": matplotlib.__version__},
        "seeds": SEEDS, "dti_knot": knot, "n_bootstrap_discrimination": N_BOOT, "n_bootstrap_importance": N_BOOT_IMPORTANCE,
        "sha256": {p: sha256(ROOT / p) for p in ["data/portfolio.csv", "data/make_data.py", "model/pd_model_v1.pkl",
                                                  "model/develop_model.py", "model/developer_documentation.json",
                                                  "validation/tests.py", "validation/advanced.py", "validation/stats_core.py"]},
        "runtime_seconds": round(time.time() - t0, 1),
        "log": log,
    }
    (OUT / "run_manifest.json").write_text(json.dumps(manifest, indent=2))
    _print_summary(S, cal, seg, fx, proxy, rep_reported, today=date.today(), runtime=manifest["runtime_seconds"], knot_sel=knot_sel)
    return S


def _print_summary(S, cal, seg, fx, proxy, rep, today, runtime, knot_sel):
    a = S["auc"]
    line = "-" * 78
    print(line)
    print(f"VALIDATION SUMMARY  Consumer PD Model v1.0  (run {today}, {runtime}s)")
    print(line)
    print(f"Replication: train AUC {rep['train']['reproduced_auc']:.4f} vs reported {rep['train']['reported_auc']}; "
          f"test {rep['test']['reproduced_auc']:.4f} vs {rep['test']['reported_auc']}  -> "
          f"{'PASS' if rep['train']['within_tolerance'] and rep['test']['within_tolerance'] else 'FAIL'}")
    for s in ("dev", "dev_test", "2024H1", "2024H2"):
        print(f"  {s:9s} AUC {a[s]['auc']:.4f} [{a[s]['lo']:.4f}, {a[s]['hi']:.4f}]  KS {a[s]['ks']:.4f}  Gini {a[s]['gini']:.4f}")
    c = cal.set_index("sample")
    for s in c.index:
        print(f"  {s:9s} O/P {c.loc[s, 'obs_over_pred']:.3f}  HL p {c.loc[s, 'hl_p']:.3f}  Spiegelhalter p {c.loc[s, 'spiegelhalter_p']:.3f}  slope {c.loc[s, 'calib_slope']:.3f}")
    print(f"Score PSI: 2024H1 {S['psi_2024H1']:.4f}  2024H2 {S['psi_2024H2']:.4f}")
    tail_name = knot_sel["segment_names"]["dti_tail"]
    print(f"DTI knot (profile likelihood): {knot_sel['knot']:.2f}  95% CI [{knot_sel['ci_lo']:.2f}, {knot_sel['ci_hi']:.2f}]")
    sg = seg.set_index(["sample", "segment"])
    for s in ("2024H1", "2024H2"):
        print(f"  {s} O/P income-missing {sg.loc[(s, 'Income missing'), 'production_ratio']:.2f}  {tail_name} {sg.loc[(s, tail_name), 'production_ratio']:.2f}")
    for d in S["delong"]:
        if d["sample"] != "dev_test":
            print(f"  DeLong {d['sample']} {d['challenger']:16s} dAUC {d['auc_diff']:+.4f}  p {d['p_value']:.2g}")
    print(f"AIR (fixed cut-off): " + "  ".join(f"{k} {v:.3f}" for k, v in S["air_fixed_cutoff"].items()))
    print(f"region_risk LR test given class p = {proxy['lr_test_region_risk_given_class']['p_value']:.2g}; "
          f"class given inputs p = {proxy['lr_test_class_given_inputs']['p_value']:.3f}")
    print(f"Grade-level red lights on OOT: {S['grade_red_count_oot']}")
    print(f"Outputs: {TAB}  |  {FIG} ({len(S['figures'])} figures)")
    print(line)


if __name__ == "__main__":
    main()
