"""
Build the validation report from outputs/.

Every number in the report is read from outputs/ and inserted into
report/template.md through {{placeholders}}; no figure is typed by hand.
Before rendering, `check_finding_triggers` re-tests the evidence that each
finding in the register relies on. If a re-run of the validation changes
the evidence (e.g. new data), the build fails rather than publishing a
register that no longer matches the numbers.

Outputs: report/validation_report.md, .docx, .pdf
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
TAB = ROOT / "outputs" / "tables"
REP = ROOT / "report"


def J(name):
    return json.loads((TAB / f"{name}.json").read_text())


def T(name):
    return pd.read_csv(TAB / f"{name}.csv")


def f(x, d=3):
    return f"{x:,.{d}f}"


def pct(x, d=1):
    return f"{100 * x:.{d}f}%"


def pv(p):
    """p-value formatting used throughout the report."""
    if p < 1e-4:
        return "< 0.0001"
    return f"{p:.4f}" if p < 0.001 else f"{p:.3f}"


def md_table(df: pd.DataFrame, align: str | None = None) -> str:
    cols = list(df.columns)
    al = align or ("l" + "r" * (len(cols) - 1))
    sep = ["---:" if a == "r" else ":---" if a == "l" else ":---:" for a in al]
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join(sep) + " |"]
    for _, r in df.iterrows():
        lines.append("| " + " | ".join(str(v) for v in r.values) + " |")
    return "\n".join(lines)


# ----------------------------------------------------------------------------
def build_context() -> dict:
    C: dict[str, str] = {}
    ks = J("knot_selection")
    SN = ks["segment_names"]
    S = json.loads((ROOT / "outputs" / "summary.json").read_text())
    man = json.loads((ROOT / "outputs" / "run_manifest.json").read_text())
    doc = json.loads((ROOT / "model" / "developer_documentation.json").read_text())
    dq = J("data_quality")
    rep = J("replication")
    cc = J("conceptual_soundness")
    disc = T("discrimination_ci").set_index("sample")
    cal = T("calibration_tests").set_index("sample")
    seg = T("segment_calibration").set_index(["sample", "segment"])
    gb = T("grade_backtest")
    mig = J("grade_migration_summary")
    mix = T("grade_mix_dev_vs_2024H2")
    bench = T("benchmark_delong").set_index(["sample", "challenger"])
    stab = J("stability")
    el = T("elasticity")
    sob = T("sobol_indices").set_index("feature")
    cp = T("coefficient_perturbation")
    cpj = J("coefficient_uncertainty_joint")
    mi = T("missing_income_counterfactual").set_index("sample")
    fx = T("fairness_extended").set_index(["sample", "model"])
    px = J("proxy_marginal_effect")
    iv = T("woe_iv_summary").set_index("characteristic")
    woe = J("woe_tables")
    enh = J("enhanced_logit_coefficients")
    sens = J("sensitivity_baseline")
    imp = J("importance_stability_summary")
    impg = T("importance_stability_gbm").set_index("feature")
    mono = T("monotonicity").set_index(["feature", "model"])
    ms = J("master_scale")
    mon = json.loads((ROOT / "outputs" / "monitoring_thresholds.json").read_text())
    outc = J("outcomes_baseline")
    wald = T("wald_table").set_index("variable")
    dti_prof = T("binned_logit_dti")

    # --- general
    C["report_date"] = S["report_date"]
    C["n_total"] = f"{S['n_total']:,}"
    C["n_dev"] = f"{S['n_dev']:,}"
    C["n_h1"] = f"{S['n_oot']['2024H1']:,}"
    C["n_h2"] = f"{S['n_oot']['2024H2']:,}"
    C["n_train"] = f"{doc['n_train']:,}"
    C["n_test"] = f"{doc['n_test']:,}"
    C["income_fill"] = f"{float(doc['income_imputation'].split('fill=')[1].split(',')[0]):,.0f}"
    C["cutoff_pd"] = pct(S["approval_cutoff_pd"], 2)
    C["intercept"] = f(doc["intercept"], 3)

    # --- DTI knot (data-selected)
    C["knot"] = f"{ks['knot']:.2f}"
    C["knot_lo"], C["knot_hi"] = f"{ks['ci_lo']:.2f}", f"{ks['ci_hi']:.2f}"
    C["knot_lr"] = f"{ks['lr_vs_linear']:.1f}"
    C["knot_nfit"] = f"{ks['n_fit']:,}"
    C["tail"] = f"{ks['dti_tail_threshold_p90']:.2f}"
    C["seg_knot"], C["seg_tail"] = SN["dti_gt_knot"], SN["dti_tail"]
    C["n_dev_clean"] = f"{ks['n_dev_clean']:,}"
    C["n_dev_excl"] = str(S["n_dev"] - ks["n_dev_clean"])
    C["n_unit_tests"] = str(len(re.findall(r"^def test_", (ROOT / "tests" / "test_stats.py").read_text(), re.M)))

    # --- data quality
    C["inc_miss_all"] = f"{dq['missing_pct']['income']:.2f}%"
    mr = [r["missing_rate"] for r in dq["income_missing_by_vintage"]]
    C["inc_miss_min"], C["inc_miss_max"] = pct(min(mr)), pct(max(mr))
    C["dr_miss_all"] = pct(dq["income_missing_vs_default"]["default_rate_when_missing"])
    C["dr_present_all"] = pct(dq["income_missing_vs_default"]["default_rate_when_present"])
    C["chi2_p"] = pv(dq["income_missing_vs_default"]["chi2_p_value"])
    C["n_fico0"] = str(dq["range_violations"]["fico_below_300"])
    C["n_dti1"] = str(dq["range_violations"]["dti_above_1"])
    C["n_bad"] = str(dq["range_violations"]["fico_below_300"] + dq["range_violations"]["dti_above_1"])
    C["bad_rate"] = f"{100 * int(C['n_bad']) / S['n_total']:.3f}%"
    C["n_bad_train"] = str(dq["range_violations_in_dev_train"])
    C["pd_fico0"] = f(dq["pd_on_range_violations"]["fico_zero_mean_pd"], 4)
    C["pd_dti1"] = f(dq["pd_on_range_violations"]["dti_gt1_mean_pd"], 3)
    imv = {r["vintage"]: r for r in dq["income_missing_by_vintage"]}
    bad = {r["vintage"]: r for r in dq["range_violations_by_vintage"]}
    vt = pd.DataFrame(dq["by_vintage"])
    C["tbl_vintage"] = md_table(pd.DataFrame({
        "Vintage": vt.vintage, "Role": ["Development", "Development", "Out-of-time", "Out-of-time"], "Loans": vt.n.map("{:,}".format),
        "Default rate": vt.default_rate.map(pct), "Mean FICO": vt.mean_fico.map(lambda x: f"{x:.1f}"),
        "Mean utilization": vt.mean_util.map(lambda x: f"{x:.3f}"),
        "Income missing": [pct(imv[v]["missing_rate"]) for v in vt.vintage],
        "FICO < 300": [bad[v]["bad_fico"] for v in vt.vintage], "DTI > 1": [bad[v]["bad_dti"] for v in vt.vintage]}), "llrrrrrrr")
    C["dr_2024H2"] = pct(vt.set_index("vintage").loc["2024H2", "default_rate"])
    C["fico_2024H2"] = f"{vt.set_index('vintage').loc['2024H2', 'mean_fico']:.1f}"
    C["util_2024H2"] = f"{vt.set_index('vintage').loc['2024H2', 'mean_util']:.3f}"
    C["fico_dev"] = f"{vt.set_index('vintage').loc[['2023H1', '2023H2'], 'mean_fico'].mean():.1f}"
    C["util_dev"] = f"{vt.set_index('vintage').loc[['2023H1', '2023H2'], 'mean_util'].mean():.3f}"

    # --- replication
    rr = rep["reported_auc_reproduction"]
    C["rep_train_auc"] = f(rr["train"]["reproduced_auc"], 6)
    C["rep_test_auc"] = f(rr["test"]["reproduced_auc"], 6)
    C["rep_train_rep"] = f(rr["train"]["reported_auc"], 4)
    C["rep_test_rep"] = f(rr["test"]["reported_auc"], 4)
    C["rep_train_diff"] = f"{rr['train']['abs_diff']:.1e}"
    C["rep_test_diff"] = f"{rr['test']['abs_diff']:.1e}"
    C["rep_coef_diff"] = f"{rep['independent_refit']['max_abs_coef_diff']:.1e}"
    C["rep_score_diff"] = f"{rep['independent_refit']['max_abs_score_diff']:.1e}"

    # --- conceptual
    w = wald.reset_index()
    w["sign"] = ["n/a"] + ["As expected" if cc["sign_checks"][v] else "UNEXPECTED" for v in w.variable[1:]]
    w["VIF"] = ["n/a"] + [f"{cc['vif'][v]:.3f}" for v in w.variable[1:]]
    C["tbl_wald"] = md_table(pd.DataFrame({"Variable": w.variable, "Coefficient": w.coef.map(lambda x: f"{x:.5f}"),
                                           "Std. error": w.std_err.map(lambda x: f"{x:.5f}"), "z": w.z.map(lambda x: f"{x:.2f}"),
                                           "p-value": w.p_value.map(pv), "Sign": w.sign, "VIF": w.VIF}))
    C["inc_z"] = f"{wald.loc['income_log', 'z']:.2f}"
    C["inc_p"] = f"{wald.loc['income_log', 'p_value']:.3f}"
    C["vif_max"] = f"{max(cc['vif'].values()):.3f}"
    C["n_sig"] = str(int((wald.drop('intercept').p_value < 0.01).sum()))
    C["dti_tail_resid"] = f(cc["dti_linearity"]["mean_tail_residual_logit"], 3)
    C["hinge_coef"] = f(enh["dti_hinge"], 2)
    C["enh_dti_coef"] = f(enh["dti"], 2)
    C["prod_dti_coef"] = f(doc["coefficients"]["dti"], 2)
    C["miss_coef"] = f(enh["income_missing"], 2)
    C["miss_or"] = f"{__import__('math').exp(enh['income_missing']):.2f}"
    top = dti_prof.iloc[-1]
    mid = dti_prof.iloc[15]
    C["dti_top_x"] = f(top.x, 3)
    C["dti_top_obs"] = pct(top.observed_dr)
    C["dti_top_pred"] = pct(top.model_pd)
    C["dti_mid_x"] = f(mid.x, 3)
    C["dti_mid_obs"] = pct(mid.observed_dr)
    C["dti_mid_pred"] = pct(mid.model_pd)
    C["iv_fico"] = f(iv.loc["fico", "iv"], 3)
    C["iv_inc_raw"] = f(iv.loc["income (raw, missing as bin)", "iv"], 3)
    C["iv_inc_imp"] = f(iv.loc["income_log (as imputed by model)", "iv"], 3)
    wt = pd.DataFrame(woe["income (raw, missing as bin)"]).set_index("bin")
    C["iv_inc_missing_share"] = pct(wt.loc["Missing", "iv_contrib"] / wt.iv_contrib.sum(), 0)
    C["iv_region"] = f(iv.loc["region_risk", "iv"], 3)
    ivt = iv.reset_index()
    C["tbl_iv"] = md_table(pd.DataFrame({"Characteristic": ivt.characteristic, "IV": ivt.iv.map(lambda x: f"{x:.3f}"),
                                         "Strength": ivt.strength, "Bins": ivt.n_bins}))

    # --- outcomes
    def auc_ci(s):
        r = disc.loc[s]
        return f"{r.auc:.4f} [{r.auc_lo:.4f}, {r.auc_hi:.4f}]"
    for s, k in (("dev", "dev"), ("dev_test", "test"), ("2024H1", "h1"), ("2024H2", "h2"), ("2023H1", "v1"), ("2023H2", "v2")):
        C[f"auc_{k}"] = auc_ci(s)
        C[f"aucp_{k}"] = f"{disc.loc[s, 'auc']:.4f}"
        C[f"ks_{k}"] = f"{disc.loc[s, 'ks']:.4f}"
        C[f"gini_{k}"] = f"{disc.loc[s, 'gini']:.4f}"
    C["auc_drop_h2"] = f"{round(disc.loc['dev', 'auc'], 4) - round(disc.loc['2024H2', 'auc'], 4):.4f}"
    rows = []
    for s in ["2023H1", "2023H2", "dev", "dev_test", "2024H1", "2024H2"]:
        r = disc.loc[s]
        rows.append({"Sample": s, "Loans": f"{int(r.n):,}", "Defaults": f"{int(r.n_defaults):,}", "AUC [95% CI]": f"{r.auc:.4f} [{r.auc_lo:.4f}, {r.auc_hi:.4f}]",
                     "Gini [95% CI]": f"{r.gini:.4f} [{r.gini_lo:.4f}, {r.gini_hi:.4f}]", "KS [95% CI]": f"{r.ks:.4f} [{r.ks_lo:.4f}, {r.ks_hi:.4f}]"})
    C["tbl_disc"] = md_table(pd.DataFrame(rows))
    rows = []
    for s in ["dev", "2024H1", "2024H2"]:
        r = cal.loc[s]
        rows.append({"Sample": s, "Observed DR": pct(r.observed_rate, 2), "Mean PD": pct(r.mean_pd, 2), "O/P": f"{r.obs_over_pred:.3f}",
                     "CITL p": pv(r.citl_p), "Spiegelhalter z (p)": f"{r.spiegelhalter_z:.2f} ({pv(r.spiegelhalter_p)})",
                     "HL stat (p, 8 df)": f"{r.hl_stat:.2f} ({pv(r.hl_p)})", "Slope": f"{r.calib_slope:.3f}", "Intercept": f"{r.calib_intercept:.3f}",
                     "ECE": f"{r.ece:.4f}"})
    C["tbl_cal"] = md_table(pd.DataFrame(rows))
    for s, k in (("dev", "dev"), ("2024H1", "h1"), ("2024H2", "h2")):
        C[f"hl_p_{k}"] = pv(cal.loc[s, "hl_p"])
        C[f"hl_pg_{k}"] = pv(cal.loc[s, "hl_p_dof_g"])
        C[f"sp_p_{k}"] = pv(cal.loc[s, "spiegelhalter_p"])
        C[f"op_{k}"] = f"{cal.loc[s, 'obs_over_pred']:.3f}"
        C[f"ece_{k}"] = f"{cal.loc[s, 'ece']:.4f}"
        C[f"slope_{k}"] = f"{cal.loc[s, 'calib_slope']:.3f}"
        C[f"odr_{k}"] = pct(cal.loc[s, "observed_rate"], 2)
        C[f"mpd_{k}"] = pct(cal.loc[s, "mean_pd"], 2)
    C["ece_ratio_h2"] = f"{cal.loc['2024H2', 'ece'] / cal.loc['dev', 'ece']:.1f}"
    C["bins_out_h2"] = str(int(cal.loc["2024H2", "bins_pred_outside_ci"]))
    rel = T("reliability_2024H2")
    out = rel[~rel.pred_in_ci]
    C["bins_out_desc"] = "; ".join(f"decile {int(r.bin) + 1}: predicted {pct(r.predicted)} vs observed {pct(r.observed)} [{pct(r.obs_lo)}, {pct(r.obs_hi)}]" for _, r in out.iterrows())
    C["bins_out_direction"] = "over-predicted" if (out.predicted > out.observed).all() else "mixed"
    C["ms_bounds"] = ", ".join(pct(x, 2) for x in ms["pd_upper_bounds"][:-1])
    g = gb[gb["sample"] != "dev"]
    C["n_grade_tests_oot"] = str(len(g))
    C["n_red_oot"] = str(int((g.traffic_light == "red").sum()))
    C["n_amber_oot"] = str(int((g.traffic_light == "amber").sum()))
    gd = gb[gb["sample"] == "dev"]
    am = gd[gd.traffic_light == "amber"]
    C["dev_amber_desc"] = ", ".join(f"grade {int(r.grade)} (predicted {pct(r.predicted_pd, 2)}, observed {pct(r.observed_dr, 2)}, Jeffreys p = {r.jeffreys_p_under:.3f})" for _, r in am.iterrows()) or "none"
    C["n_amber_dev"] = str(len(am))
    gbt = gb[gb["sample"].isin(["2024H1", "2024H2"])].copy()
    piv = []
    for k in range(1, 9):
        r1 = gbt[(gbt["sample"] == "2024H1") & (gbt.grade == k)].iloc[0]
        r2 = gbt[(gbt["sample"] == "2024H2") & (gbt.grade == k)].iloc[0]
        piv.append({"Grade": k, "PD upper bound": pct(ms["pd_upper_bounds"][k - 1], 2) if k < 8 else "100%",
                    "2024H1 n": f"{int(r1.n):,}", "2024H1 PD / DR": f"{pct(r1.predicted_pd, 2)} / {pct(r1.observed_dr, 2)}",
                    "2024H1 Jeffreys p": f"{r1.jeffreys_p_under:.3f}", "2024H1 light": r1.traffic_light.capitalize(),
                    "2024H2 n": f"{int(r2.n):,}", "2024H2 PD / DR": f"{pct(r2.predicted_pd, 2)} / {pct(r2.observed_dr, 2)}",
                    "2024H2 Jeffreys p": f"{r2.jeffreys_p_under:.3f}", "2024H2 light": r2.traffic_light.capitalize()})
    C["tbl_grades"] = md_table(pd.DataFrame(piv))
    C["grade_psi"] = f(mig["grade_psi"], 3)
    C["g8_dev"], C["g8_h2"] = pct(mix.iloc[7].dev_share), pct(mix.iloc[7].target_share)
    C["g1_dev"], C["g1_h2"] = pct(mix.iloc[0].dev_share), pct(mix.iloc[0].target_share)
    C["same_grade"] = pct(mig["share_same_grade"])
    C["within_one"] = pct(mig["share_within_one_grade"])
    C["moved"] = pct(1 - mig["share_same_grade"])
    C["n_far"] = f"{mig['n_moved_2plus']:,}"
    C["far_miss"] = pct(mig["share_2plus_income_missing"], 1)
    C["far_up"] = pct(mig["share_2plus_to_riskier"], 0)
    rc = pd.read_csv(TAB / "reclassification_production_vs_enhanced_2024H2.csv", index_col=0)
    rc.index.name = None
    rc_md = rc.copy()
    rc_md.insert(0, "Production grade", rc.index)
    C["tbl_reclass"] = md_table(rc_md.astype(str), "l" + "r" * 8)

    # segments
    rows = []
    for sname in ["2024H1", "2024H2"]:
        for sg in ["All loans", "Income missing", "Income reported", SN["dti_le_knot"], SN["dti_gt_knot"], SN["dti_tail"], "FICO < 640", "Utilization > 0.60", "Broker channel"]:
            r = seg.loc[(sname, sg)]
            pu = r.jeffreys_p_under
            flag = "Under-prediction" if pu < 0.01 else "Over-prediction" if r.jeffreys_p_over < 0.01 else "-"
            rows.append({"Sample": sname, "Segment": sg, "Loans": f"{int(r.n):,}", "Share": pct(r.share), "Observed DR": pct(r.observed_dr),
                         "Production PD": pct(r.production_pd), "Prod. O/P": f"{r.production_ratio:.2f}", "Challenger O/P": f"{r.enhanced_ratio:.2f}",
                         "Significant (1%)": flag})
    C["tbl_seg"] = md_table(pd.DataFrame(rows))
    for s, k in (("dev", "dev"), ("2024H1", "h1"), ("2024H2", "h2")):
        C[f"op_miss_{k}"] = f"{seg.loc[(s, 'Income missing'), 'production_ratio']:.2f}"
        C[f"op_rep_{k}"] = f"{seg.loc[(s, 'Income reported'), 'production_ratio']:.2f}"
        C[f"op_dtitail_{k}"] = f"{seg.loc[(s, SN['dti_tail']), 'production_ratio']:.2f}"
        C[f"op_dtiknot_{k}"] = f"{seg.loc[(s, SN['dti_gt_knot']), 'production_ratio']:.2f}"
        C[f"eop_miss_{k}"] = f"{seg.loc[(s, 'Income missing'), 'enhanced_ratio']:.2f}"
        C[f"eop_dtitail_{k}"] = f"{seg.loc[(s, SN['dti_tail']), 'enhanced_ratio']:.2f}"
        C[f"dtitail_share_{k}"] = pct(seg.loc[(s, SN["dti_tail"]), "share"])
        C[f"dtitail_obs_{k}"] = pct(seg.loc[(s, SN["dti_tail"]), "observed_dr"])
        C[f"dtitail_pred_{k}"] = pct(seg.loc[(s, SN["dti_tail"]), "production_pd"])
        C[f"dtiknot_p_{k}"] = pv(seg.loc[(s, SN["dti_gt_knot"]), "jeffreys_p_under"])
    under = [1 - 1 / seg.loc[(s, "Income missing"), "production_ratio"] for s in ("dev", "2024H1", "2024H2")]
    C["miss_under_lo"], C["miss_under_hi"] = pct(min(under), 0), pct(max(under), 0)
    rng_ = lambda vals, d=2: f"{min(vals):.{d}f} to {max(vals):.{d}f}"  # noqa: E731
    C["op_rep_range_oot"] = rng_([seg.loc[(s, "Income reported"), "production_ratio"] for s in ("2024H1", "2024H2")])
    C["op_rep_range_all"] = rng_([seg.loc[(s, "Income reported"), "production_ratio"] for s in ("dev", "2024H1", "2024H2")])
    C["eop_miss_range"] = rng_([seg.loc[(s, "Income missing"), "enhanced_ratio"] for s in ("dev", "2024H1", "2024H2")])
    C["eop_dtitail_range"] = rng_([seg.loc[(s, SN["dti_tail"]), "enhanced_ratio"] for s in ("dev", "2024H1", "2024H2")])
    C["miss_obs_dev"] = pct(mi.loc["dev", "observed_dr"])
    C["miss_pred_dev"] = pct(mi.loc["dev", "production_pd"])
    C["miss_obs_h2"] = pct(mi.loc["2024H2", "observed_dr"])
    C["miss_pred_h2"] = pct(mi.loc["2024H2", "production_pd"])
    C["miss_obs_h1"] = pct(mi.loc["2024H1", "observed_dr"])
    C["miss_pred_h1"] = pct(mi.loc["2024H1", "production_pd"])
    C["miss_share_dev"] = pct(mi.loc["dev", "share_missing"])
    C["miss_excess_dev"] = f"{mi.loc['dev', 'excess_defaults_vs_production']:.0f}"
    C["miss_excess_h1"] = f"{mi.loc['2024H1', 'excess_defaults_vs_production']:.0f}"
    C["miss_excess_h2"] = f"{mi.loc['2024H2', 'excess_defaults_vs_production']:.0f}"
    C["fill_p10_dev"] = pct(mi.loc["dev", "production_pd_fill_p10"])
    C["fill_p90_dev"] = pct(mi.loc["dev", "production_pd_fill_p90"])
    pooled = sum(mi.loc[s, "observed_dr"] * mi.loc[s, "n_missing"] for s in mi.index) / sum(mi.loc[s, "production_pd"] * mi.loc[s, "n_missing"] for s in mi.index)
    C["overlay_mult"] = f"{pooled:.2f}"
    rows = []
    for s in mi.index:
        r = mi.loc[s]
        rows.append({"Sample": s, "Income-missing loans": f"{int(r.n_missing):,} ({pct(r.share_missing)})", "Observed DR": pct(r.observed_dr),
                     "Production PD": pct(r.production_pd), "Production O/P": f"{r.production_obs_over_pred:.2f}",
                     "PD with fill at p10 / p90": f"{pct(r.production_pd_fill_p10)} / {pct(r.production_pd_fill_p90)}",
                     "Challenger PD (O/P)": f"{pct(r.enhanced_pd)} ({r.enhanced_obs_over_pred:.2f})",
                     "Excess defaults": f"{r.excess_defaults_vs_production:.0f}"})
    C["tbl_miss"] = md_table(pd.DataFrame(rows))

    # --- benchmarking
    rows = []
    names = {"enhanced_logit": "Enhanced logit", "gbm": "GBM", "gbm_monotone": "GBM (monotone)", "no_region_logit": "Logit w/o region_risk"}
    for (s, c), r in bench.iterrows():
        rows.append({"Sample": s, "Challenger": names[c], "Production AUC": f"{r.auc_production:.4f}", "Challenger AUC": f"{r.auc_challenger:.4f}",
                     "Difference [95% CI]": f"{r.auc_diff:+.4f} [{r.diff_lo:+.4f}, {r.diff_hi:+.4f}]", "DeLong z": f"{r.z:.2f}", "p-value": pv(r.p_value)})
    C["tbl_bench"] = md_table(pd.DataFrame(rows))
    for s, k in (("dev_test", "test"), ("2024H1", "h1"), ("2024H2", "h2")):
        for c, ck in (("enhanced_logit", "enh"), ("gbm", "gbm"), ("gbm_monotone", "mono"), ("no_region_logit", "nor")):
            r = bench.loc[(s, c)]
            C[f"d_{ck}_{k}"] = f"{r.auc_diff:+.4f}"
            C[f"p_{ck}_{k}"] = pv(r.p_value)
            C[f"a_{ck}_{k}"] = f"{r.auc_challenger:.4f}"
            C[f"abs_{ck}_{k}"] = f"{abs(r.auc_diff):.4f}"
    # derived from the rounded table values so text and Table 8 agree exactly
    C["gbm_minus_enh_h2"] = f"{round(bench.loc[('2024H2', 'enhanced_logit'), 'auc_challenger'], 4) - round(bench.loc[('2024H2', 'gbm'), 'auc_challenger'], 4):.4f}"

    # --- sensitivity
    C["base_pd"] = pct(el.base_mean_pd.iloc[0], 2)
    rows = []
    for _, r in el.iterrows():
        rows.append({"Rank": int(r["rank"]), "Input": r.feature, "1 SD": "binary" if pd.isna(r.sd) else f"{r.sd:.4g}",
                     "d mean PD per SD (pp)": f"{100 * r.dPD_per_sd:+.2f}", "Mean PD at -1 SD": pct(r.pd_minus_1sd, 2), "Mean PD at +1 SD": pct(r.pd_plus_1sd, 2),
                     "Sobol S1 [95% CI]": f"{sob.loc[r.feature, 'S1']:.3f} [{sob.loc[r.feature, 'S1_lo']:.3f}, {sob.loc[r.feature, 'S1_hi']:.3f}]",
                     "Sobol ST": f"{sob.loc[r.feature, 'ST']:.3f}"})
    C["tbl_elast"] = md_table(pd.DataFrame(rows))
    C["fico_plus"], C["fico_minus"] = pct(el.set_index("feature").loc["fico", "pd_plus_1sd"], 2), pct(el.set_index("feature").loc["fico", "pd_minus_1sd"], 2)
    C["s1_fico"], C["st_fico"] = f(sob.loc["fico", "S1"], 3), f(sob.loc["fico", "ST"], 3)
    C["s1_dti"], C["st_dti"] = f(sob.loc["dti", "S1"], 3), f(sob.loc["dti", "ST"], 3)
    C["s1_util"] = f(sob.loc["utilization", "S1"], 3)
    C["s1_sum"] = f(sob.S1.sum(), 3)
    C["st_inc"] = f(sob.loc["income_log", "ST"], 4)
    C["st_region"] = f(sob.loc["region_risk", "ST"], 4)
    C["stress_pd"] = pct(sens["stress_scenario"]["mean_pd"], 2)
    C["stress_rel"] = pct(sens["stress_scenario"]["relative_increase"], 1)
    C["cp_cutoff"] = pct(cpj["cutoff_pd"], 2)
    C["cp_app_lo"], C["cp_app_hi"] = pct(cpj["approval_p05"], 1), pct(cpj["approval_p95"], 1)
    C["cp_pd_lo"], C["cp_pd_hi"] = pct(cpj["mean_pd_p05"], 2), pct(cpj["mean_pd_p95"], 2)
    C["cp_flip_med"], C["cp_flip_p95"] = f"{cpj['flipped_pct_median']:.2f}%", f"{cpj['flipped_pct_p95']:.2f}%"
    C["cp_corr_inc"] = f"{cpj['corr_intercept_income_log']:.2f}"
    C["cp_corr_fico"] = f"{cpj['corr_intercept_fico']:.2f}"
    C["cp_naive_int_flip"] = f"{cp[(cp.parameter == 'intercept') & (cp['shift'] == '+1 SE')].naive_flipped_pct.iloc[0]:.1f}%"
    C["cp_naive_inc_flip"] = f"{cp[(cp.parameter == 'income_log') & (cp['shift'] == '+1 SE')].naive_flipped_pct.iloc[0]:.1f}%"
    C["cp_cond_max_flip"] = f"{cp.conditional_flipped_pct.max():.2f}%"
    C["cp_cond_max_app"] = f"{cp.conditional_approval_change_pp.abs().max():.2f}"
    rows = []
    for p in ["intercept", "fico", "dti", "utilization", "income_log", "region_risk"]:
        for sh in ["+1 SE", "-1 SE"]:
            r = cp[(cp.parameter == p) & (cp["shift"] == sh)].iloc[0]
            rows.append({"Parameter": p, "Shift": sh, "Naive: approval change (pp)": f"{r.naive_approval_change_pp:+.2f}",
                         "Naive: decisions flipped": f"{r.naive_flipped_pct:.2f}%", "Covariance-consistent: approval change (pp)": f"{r.conditional_approval_change_pp:+.2f}",
                         "Covariance-consistent: decisions flipped": f"{r.conditional_flipped_pct:.2f}%"})
    C["tbl_cp"] = md_table(pd.DataFrame(rows))

    # --- stability
    rows = [{"Variable": "Score (PD)", "2024H1": f"{stab['2024H1']['score_psi']:.4f}", "2024H2": f"{stab['2024H2']['score_psi']:.4f}"}]
    for v in stab["2024H1"]["csi"]:
        rows.append({"Variable": v + (" (abs. share change)" if v == "channel_broker" else ""), "2024H1": f"{stab['2024H1']['csi'][v]:.4f}", "2024H2": f"{stab['2024H2']['csi'][v]:.4f}"})
    C["tbl_psi"] = md_table(pd.DataFrame(rows))
    C["psi_h1"] = f(stab["2024H1"]["score_psi"], 4)
    C["psi_h2"] = f(stab["2024H2"]["score_psi"], 4)
    C["csi_fico_h2"] = f(stab["2024H2"]["csi"]["fico"], 4)
    C["csi_util_h2"] = f(stab["2024H2"]["csi"]["utilization"], 4)
    C["app_h2"] = pct(fx.loc[("2024H2", "production"), "approval_rate"])
    C["app_dev"] = pct(fx.loc[("dev", "production"), "approval_rate"])
    rows = [{"KPI": k["kpi"], "Green": k["green"], "Amber": k["amber"], "Red": k["red"], "Frequency": k["frequency"], "Owner": k["owner"]} for k in mon["kpis"]]
    C["tbl_monitor"] = md_table(pd.DataFrame(rows), "llllll")
    C["n_kpis"] = str(len(mon["kpis"]))

    # --- fairness
    for s, k in (("dev", "dev"), ("2024H1", "h1"), ("2024H2", "h2")):
        P, N = fx.loc[(s, "production")], fx.loc[(s, "no_region_logit")]
        C[f"air_{k}"] = f"{P.air:.3f}"
        C[f"air70_{k}"] = f"{P.air_at_70pct:.3f}"
        C[f"air_nor_{k}"] = f"{N.air:.3f}"
        C[f"dp_{k}"] = f"{100 * P.dp_diff:+.2f}"
        C[f"eo_{k}"] = f"{100 * P.eo_diff:+.2f}"
        C[f"fpr_{k}"] = f"{100 * P.fpr_diff:+.2f}"
        C[f"cr_A_{k}"], C[f"cr_B_{k}"] = f"{P.calib_ratio_A:.3f}", f"{P.calib_ratio_B:.3f}"
        C[f"nor_cr_B_{k}"] = f"{N.calib_ratio_B:.3f}"
        C[f"auc_A_{k}"], C[f"auc_B_{k}"] = f"{P.auc_A:.4f}", f"{P.auc_B:.4f}"
    rows = []
    for s in ["dev", "2024H1", "2024H2"]:
        for m, lab in (("production", "Production"), ("no_region_logit", "Without region_risk")):
            r = fx.loc[(s, m)]
            rows.append({"Sample": s, "Model": lab, "Approval A / B": f"{pct(r.approval_A)} / {pct(r.approval_B)}", "AIR": f"{r.air:.3f}",
                         "DP diff (pp)": f"{100 * r.dp_diff:+.2f}", "EO diff (pp)": f"{100 * r.eo_diff:+.2f}", "FPR gap (pp)": f"{100 * r.fpr_diff:+.2f}",
                         "O/P A / B": f"{r.calib_ratio_A:.3f} / {r.calib_ratio_B:.3f}", "AUC": f"{r.auc:.4f}"})
    C["tbl_fair"] = md_table(pd.DataFrame(rows))
    C["px_corr"] = f(px["corr_region_risk_class_B"], 3)
    C["px_auc"] = f(px["auc_region_risk_predicting_class_B"], 3)
    C["px_rr_A"], C["px_rr_B"] = f(px["mean_region_risk_A"], 3), f(px["mean_region_risk_B"], 3)
    C["px_dr_A"], C["px_dr_B"] = pct(px["raw_default_rate_A"]), pct(px["raw_default_rate_B"])
    C["lr_rr"] = f(px["lr_test_region_risk_given_class"]["stat"], 2)
    C["lr_rr_p"] = f"{px['lr_test_region_risk_given_class']['p_value']:.1e}"
    C["lr_cls"] = f(px["lr_test_class_given_inputs"]["stat"], 3)
    C["lr_cls_p"] = f"{px['lr_test_class_given_inputs']['p_value']:.3f}"
    C["ame_with"] = f"{100 * px['ame_region_risk_with_class']['ame']:.2f}"
    C["ame_with_se"] = f"{100 * px['ame_region_risk_with_class']['se']:.2f}"
    C["ame_without"] = f"{100 * px['ame_region_risk_without_class']['ame']:.2f}"
    C["ame_att"] = f"{px['ame_attenuation_pct']:.1f}%"

    # --- ML
    C["imp_rho_gbm"], C["imp_rho_logit"] = f(imp["gbm"]["mean_pairwise_spearman"], 3), f(imp["logit"]["mean_pairwise_spearman"], 3)
    C["imp_min_gbm"] = f(imp["gbm"]["min_pairwise_spearman"], 3)
    C["imp_top3_gbm"], C["imp_top3_logit"] = pct(imp["gbm"]["top3_set_stability"], 0), pct(imp["logit"]["top3_set_stability"], 0)
    C["imp_nboot"] = str(imp["n_boot"])
    C["imp_inc_rank_gbm"] = f"{impg.loc['income_log', 'mean_rank']:.2f}"
    C["imp_inc_gbm"] = f"{impg.loc['income_log', 'mean_importance']:.4f}"
    il = T("importance_stability_logit").set_index("feature")
    C["imp_inc_logit"] = f"{il.loc['income_log', 'mean_importance']:.4f}"
    C["imp_inc_rank_logit"] = f"{il.loc['income_log', 'mean_rank']:.0f}"
    C["cv_emp_gbm"] = f"{impg.loc['employment_years', 'cv']:.2f}"
    C["cv_region_gbm"] = f"{impg.loc['region_risk', 'cv']:.2f}"
    for feat in ("fico", "dti", "utilization"):
        r = mono.loc[(feat, "gbm")]
        C[f"mono_{feat}_viol"] = f"{int(r.pd_curve_violations)}/{int(r.n_steps)}"
        C[f"mono_{feat}_ice"] = pct(r.ice_share_reversal_gt_50bp, 0)
        C[f"mono_{feat}_max"] = f"{r.max_reversal_pp:.2f}"
    rows = []
    for (feat, m), r in mono.iterrows():
        rows.append({"Input": feat, "Model": m, "Expected": r.expected_direction, "PD-curve reversals": f"{int(r.pd_curve_violations)}/{int(r.n_steps)}",
                     "Largest reversal (pp)": f"{r.max_reversal_pp:.2f}", "ICE curves with reversal > 0.5 pp": pct(r.ice_share_reversal_gt_50bp, 1)})
    C["tbl_mono"] = md_table(pd.DataFrame(rows))

    # --- appendices
    for s in ("dev", "2024H1", "2024H2"):
        d = pd.DataFrame(outc[s]["deciles"])
        d["O/P"] = (d.observed / d.predicted).map(lambda x: f"{x:.3f}")
        C[f"tbl_dec_{s}"] = md_table(pd.DataFrame({"Decile": d.decile, "Loans": d.n.map("{:,}".format), "Mean PD": d.predicted.map(lambda x: pct(x, 2)),
                                                   "Observed DR": d.observed.map(lambda x: pct(x, 2)), "O/P": d["O/P"]}))
    figs = S["figures"]
    C["tbl_figs"] = md_table(pd.DataFrame({"Figure": [f"Figure {i + 1}" for i in range(len(figs))], "File": [f"`outputs/figures/{x['file']}`" for x in figs],
                                           "Content": [x["caption"] for x in figs]}), "lll")
    C["git_commit"] = man["git_commit"]
    C["run_date"] = man["run_date_utc"]
    C["py_ver"] = man["python"]
    C["libs"] = ", ".join(f"{k} {v}" for k, v in man["libraries"].items())
    C["seeds"] = ", ".join(f"{k} = {v}" for k, v in man["seeds"].items())
    C["tbl_hash"] = md_table(pd.DataFrame({"File": [f"`{k}`" for k in man["sha256"]], "SHA-256 (first 16 hex)": [v[:16] for v in man["sha256"].values()]}), "ll")
    C["n_boot"] = str(man["n_bootstrap_discrimination"])
    return C


# ----------------------------------------------------------------------------
def check_finding_triggers() -> list[str]:
    """Re-test the evidence behind each finding; return list of failures."""
    SN = J("knot_selection")["segment_names"]
    seg = T("segment_calibration").set_index(["sample", "segment"])
    bench = T("benchmark_delong").set_index(["sample", "challenger"])
    stab = J("stability")
    fx = T("fairness_extended").set_index(["sample", "model"])
    px = J("proxy_marginal_effect")
    dq = J("data_quality")
    wald = T("wald_table").set_index("variable")
    cal = T("calibration_tests").set_index("sample")
    gb = T("grade_backtest")
    disc = T("discrimination_ci").set_index("sample")
    mono = T("monotonicity")
    oot = ["2024H1", "2024H2"]
    checks = {
        "F-01 income-missing O/P > 1.3 and significant on dev and OOT":
            all(seg.loc[(s, "Income missing"), "production_ratio"] > 1.3 and seg.loc[(s, "Income missing"), "jeffreys_p_under"] < 0.01 for s in ["dev"] + oot),
        "F-02 DTI top-decile tail O/P > 1.1 and p < 0.0001 on dev and OOT (text says each p < 0.0001)":
            all(seg.loc[(s, SN["dti_tail"]), "production_ratio"] > 1.1 and seg.loc[(s, SN["dti_tail"]), "jeffreys_p_under"] < 1e-4 for s in ["dev"] + oot),
        "F-02 knot interval is informative (width <= 0.10)": J("knot_selection")["ci_hi"] - J("knot_selection")["ci_lo"] <= 0.10,
        "F-01/F-02 enhanced challenger significantly better on OOT":
            all(bench.loc[(s, "enhanced_logit"), "p_value"] < 0.001 and bench.loc[(s, "enhanced_logit"), "auc_diff"] > 0 for s in oot),
        "F-03 2024H2 score PSI amber (0.10-0.25) with aggregate calibration intact":
            0.10 <= stab["2024H2"]["score_psi"] < 0.25 and 0.9 < cal.loc["2024H2", "obs_over_pred"] < 1.1,
        "F-04 region_risk proxy corr > 0.3, AIR above 0.80, LDA improves AIR":
            px["corr_region_risk_class_B"] > 0.3 and all(fx.loc[(s, "production"), "air"] > 0.8 for s in oot)
            and all(fx.loc[(s, "no_region_logit"), "air"] > fx.loc[(s, "production"), "air"] for s in oot),
        "F-05 range violations present and scored near PD = 1":
            dq["range_violations"]["fico_below_300"] > 0 and dq["pd_on_range_violations"]["fico_zero_mean_pd"] > 0.9,
        "F-07 income_log not significant at 5%": wald.loc["income_log", "p_value"] > 0.05,
        "Text: no calibration test rejects at 5% on any sample":
            all((cal[c] > 0.05).all() for c in ("citl_p", "spiegelhalter_p", "hl_p")),
        "Text: dev-vintage AUC spread exceeds dev-to-2024H2 movement":
            abs(disc.loc["2023H1", "auc"] - disc.loc["2023H2", "auc"]) > abs(disc.loc["dev", "auc"] - disc.loc["2024H2", "auc"]),
        "Text: DTI above knot significant (1%) on 2024H1 only":
            [seg.loc[(s, SN["dti_gt_knot"]), "jeffreys_p_under"] < 0.01 for s in ("dev", "2024H1", "2024H2")] == [False, True, False],
        "Text: enhanced logit beats GBM on 2024H2; monotone GBM beats unconstrained GBM on OOT":
            bench.loc[("2024H2", "enhanced_logit"), "auc_challenger"] > bench.loc[("2024H2", "gbm"), "auc_challenger"]
            and all(bench.loc[(s, "gbm_monotone"), "auc_challenger"] > bench.loc[(s, "gbm"), "auc_challenger"] for s in oot),
        "Text: monotone GBM has no reversals": (mono[mono.model == "gbm_monotone"].pd_curve_violations == 0).all(),
        "Text: 2024H2 deciles outside CI are over-predicted":
            (lambda r: bool((r[~r.pred_in_ci].predicted > r[~r.pred_in_ci].observed).all()))(T("reliability_2024H2")),
        "Text: >= 95% of loans moving >= 2 grades are income-missing; all move to riskier grades":
            J("grade_migration_summary")["share_2plus_income_missing"] >= 0.95 and J("grade_migration_summary")["share_2plus_to_riskier"] == 1.0,
        "Text: all non-score CSI on 2024H2 below 0.01 except FICO and utilization":
            all(v < 0.01 for k, v in stab["2024H2"]["csi"].items() if k not in ("fico", "utilization")),
        "Text: production AIR above 0.90 on all samples": all(fx.loc[(s, "production"), "air"] > 0.90 for s in ["dev"] + oot),
        "F-08 2024H2 deciles outside CI, no red grades OOT":
            cal.loc["2024H2", "bins_pred_outside_ci"] > 0 and ((gb["sample"] != "dev") & (gb.traffic_light != "green")).sum() == 0,
    }
    return [k for k, ok in checks.items() if not ok]


def render(template: str, C: dict) -> str:
    missing = sorted(set(re.findall(r"\{\{(\w+)\}\}", template)) - set(C))
    if missing:
        raise KeyError(f"Template placeholders without values: {missing}")
    return re.sub(r"\{\{(\w+)\}\}", lambda m: C[m.group(1)], template)


def stamp_footer(pdf: Path) -> None:
    """Add 'Page n of N' footers (the bundled wkhtmltopdf lacks footer support)."""
    try:
        from io import BytesIO

        from pypdf import PdfReader, PdfWriter
        from reportlab.pdfgen import canvas
    except ImportError:
        return
    reader = PdfReader(str(pdf))
    writer = PdfWriter()
    n = len(reader.pages)
    for i, page in enumerate(reader.pages, 1):
        w, h = float(page.mediabox.width), float(page.mediabox.height)
        buf = BytesIO()
        c = canvas.Canvas(buf, pagesize=(w, h))
        c.setFont("Helvetica", 7)
        c.setFillColorRGB(0.32, 0.32, 0.31)
        c.drawString(42, 24, "CR-PD-0142 Independent Validation Report  |  Internal  |  Model Risk Management")
        c.drawRightString(w - 42, 24, f"Page {i} of {n}")
        c.save()
        buf.seek(0)
        page = writer.add_page(page)  # attach first: pypdf >= 7 refuses to merge into a page that has no writer
        page.merge_page(PdfReader(buf).pages[0])
    with open(pdf, "wb") as fh:
        writer.write(fh)


def polish_docx(path: Path) -> None:
    """Give DOCX tables gridlines, a shaded header row and compact type."""
    try:
        import docx
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        from docx.shared import Pt, RGBColor
    except ImportError:
        return
    d = docx.Document(str(path))
    for st in ("Normal", "Body Text", "First Paragraph", "Compact"):
        if st in [x.name for x in d.styles]:
            d.styles[st].font.name = "Calibri"
            d.styles[st].font.size = Pt(10)
    if "Verbatim Char" in [x.name for x in d.styles]:
        d.styles["Verbatim Char"].font.size = Pt(8.5)
    for t in d.tables:
        tblPr = t._tbl.tblPr
        borders = OxmlElement("w:tblBorders")
        for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
            e = OxmlElement(f"w:{edge}")
            e.set(qn("w:val"), "single")
            e.set(qn("w:sz"), "4")
            e.set(qn("w:color"), "A8A79F")
            borders.append(e)
        tblPr.append(borders)
        for i, row in enumerate(t.rows):
            for cell in row.cells:
                if i == 0:
                    shd = OxmlElement("w:shd")
                    shd.set(qn("w:val"), "clear")
                    shd.set(qn("w:fill"), "10305A")
                    cell._tc.get_or_add_tcPr().append(shd)
                for par in cell.paragraphs:
                    for run in par.runs:
                        run.font.size = Pt(7.5)
                        if i == 0:
                            run.font.bold = True
                            run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    d.save(str(path))


def convert(md_path: Path) -> None:
    build = REP / "_build"
    build.mkdir(exist_ok=True)
    html = build / "validation_report.html"
    css = REP / "report.css"
    subprocess.run(["pandoc", str(md_path), "-f", "markdown+pipe_tables+yaml_metadata_block", "-t", "html5", "-s", "--embed-resources",
                    "--resource-path", str(REP), "--css", str(css), "--metadata", "pagetitle=Model Validation Report CR-PD-0142",
                    "-o", str(html)], check=True, cwd=REP)
    pdf = REP / "validation_report.pdf"
    if shutil.which("wkhtmltopdf"):
        subprocess.run(["wkhtmltopdf", "--quiet", "--enable-local-file-access", "-s", "Letter", "-T", "16mm", "-B", "18mm", "-L", "15mm", "-R", "15mm",
                        str(html), str(pdf)], check=True, stderr=subprocess.DEVNULL)
        stamp_footer(pdf)
    else:
        subprocess.run(["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(REP), str(html)], check=True)
    ref = REP / "reference.docx"
    args = ["pandoc", str(md_path), "-f", "markdown+pipe_tables+yaml_metadata_block", "-t", "docx", "--resource-path", str(REP),
            "-o", str(REP / "validation_report.docx")]
    if ref.exists():
        args += ["--reference-doc", str(ref)]
    subprocess.run(args, check=True, cwd=REP)
    polish_docx(REP / "validation_report.docx")


def main() -> None:
    failures = check_finding_triggers()
    if failures:
        print("Evidence no longer supports these findings; revise report/template.md:")
        for x in failures:
            print("  -", x)
        sys.exit(1)
    C = build_context()
    md = render((REP / "template.md").read_text(), C)
    out = REP / "validation_report.md"
    out.write_text(md)
    print(f"wrote {out} ({len(md.split()):,} words)")
    convert(out)
    print("wrote", REP / "validation_report.docx")
    print("wrote", REP / "validation_report.pdf")


if __name__ == "__main__":
    main()
