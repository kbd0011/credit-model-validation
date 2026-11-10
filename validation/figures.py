"""
Figures for the validation report.

One consistent style: system sans, thin marks, hairline grid, labelled axes,
titles that state the sample and the metric, 300 dpi PNG. Colours follow a
CVD-validated categorical order (blue, orange, aqua, ...) and a reserved
status palette for traffic lights (never reused for series).
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.metrics import roc_curve  # noqa: E402

BLUE, ORANGE, AQUA, YELLOW, MAGENTA, GREEN, VIOLET = "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6"
SERIES = [BLUE, ORANGE, AQUA, YELLOW, MAGENTA, GREEN, VIOLET]
STATUS = {"green": "#0ca30c", "amber": "#fab219", "red": "#d03b3b"}
INK, INK2, MUTED, GRID, AXIS = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 8.5, "axes.titlesize": 9.5, "axes.titleweight": "bold",
    "axes.titlelocation": "left", "axes.labelsize": 8.5, "axes.labelcolor": INK2, "axes.edgecolor": AXIS,
    "axes.linewidth": 0.8, "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
    "grid.color": GRID, "grid.linewidth": 0.6, "axes.axisbelow": True, "xtick.color": INK2, "ytick.color": INK2,
    "xtick.labelsize": 7.5, "ytick.labelsize": 7.5, "legend.fontsize": 7.5, "legend.frameon": False,
    "figure.dpi": 100, "savefig.dpi": 300, "savefig.bbox": "tight", "lines.linewidth": 1.8,
    "figure.facecolor": "white", "text.color": INK,
})


class FigureWriter:
    """Saves figures with a running index for the report's figure list."""

    def __init__(self, out_dir: Path):
        self.out = out_dir
        self.out.mkdir(parents=True, exist_ok=True)
        self.index: list[dict] = []

    def save(self, fig, name: str, caption: str):
        """Save as figNN_<name>.png, numbering figures in the order produced."""
        import re
        name = f"fig{len(self.index) + 1:02d}_" + re.sub(r"^fig\d+_", "", name)
        path = self.out / f"{name}.png"
        fig.savefig(path)
        plt.close(fig)
        self.index.append({"file": f"{name}.png", "caption": caption})


def _suptitle(fig, text: str):
    fig.suptitle(text, x=0.01, ha="left", fontsize=10, fontweight="bold", color=INK)


# ----------------------------------------------------------------------------
def vintage_profile(fw: FigureWriter, by_vintage: pd.DataFrame, miss: pd.DataFrame):
    fig, axs = plt.subplots(1, 4, figsize=(9.2, 2.6))
    v = by_vintage.vintage.tolist()
    cols = [BLUE if x.startswith("2023") else ORANGE for x in v]
    for ax, col, lab, fmt in zip(axs[:3], ["default_rate", "mean_fico", "mean_util"],
                                 ["12-month default rate", "Mean FICO", "Mean revolving utilization"],
                                 ["{:.1%}", "{:.0f}", "{:.3f}"]):
        ax.bar(v, by_vintage[col], color=cols, width=0.6)
        ax.set_title(lab)
        for i, val in enumerate(by_vintage[col]):
            ax.text(i, val, fmt.format(val), ha="center", va="bottom", fontsize=7, color=INK2)
        if col == "mean_fico":
            ax.set_ylim(650, 715)
        ax.tick_params(axis="x", rotation=0)
    ax = axs[3]
    x = np.arange(len(miss))
    ax.bar(x - 0.18, miss.dr_present, 0.34, color=BLUE, label="Income reported")
    ax.bar(x + 0.18, miss.dr_missing, 0.34, color=ORANGE, label="Income missing")
    ax.errorbar(x + 0.18, miss.dr_missing, yerr=[miss.dr_missing - miss.lo, miss.hi - miss.dr_missing], fmt="none", ecolor=INK2, lw=0.8, capsize=2)
    ax.set_xticks(x, miss.vintage)
    ax.set_title("Default rate by income status")
    ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1, 0))
    ax.legend(loc="upper left")
    axs[0].yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1, 0))
    _suptitle(fig, "Portfolio composition by vintage (all 54,000 loans; blue = development, orange = out-of-time)")
    fig.tight_layout()
    fw.save(fig, "fig01_vintage_profile", "Default rate, mean FICO, mean utilization and income-missing default rate by vintage")


def binned_logit(fw: FigureWriter, g: pd.DataFrame, feature: str, label: str, name: str, hinge: float | None = None):
    fig, ax = plt.subplots(figsize=(6.2, 3.4))
    ax.fill_between(g.x, g.emp_logit_lo, g.emp_logit_hi, color=MUTED, alpha=0.18, lw=0, label="Empirical 95% CI (Jeffreys)")
    ax.plot(g.x, g.emp_logit, "o", color=INK, ms=4, label="Empirical log-odds (observed)")
    ax.plot(g.x, g.model_logit_of_mean_pd, "-", color=BLUE, label="Production model (linear)")
    ax.plot(g.x, g.enhanced_logit_of_mean_pd, "--", color=ORANGE, label="Validator challenger (hinge + missing flag)")
    if hinge is not None:
        ax.axvline(hinge, color=MUTED, lw=0.8, ls=":")
        ax.text(hinge, ax.get_ylim()[1], f" data-selected knot = {hinge:.2f}", va="top", fontsize=7, color=INK2)
    ax.set_xlabel(f"{label} (bin mean; 20 equal-count bins)")
    ax.set_ylabel("Log-odds of 12-month default")
    ax.set_title(f"Functional form of {label}: empirical vs model log-odds (development, range violations excluded, n = {int(g.n.sum()):,})")
    ax.legend(loc="upper left" if feature == "dti" else "upper right")
    fw.save(fig, name, f"Binned empirical log-odds vs production and challenger log-odds across {label}")


def knot_profile(fw: FigureWriter, ks: dict):
    g, ll = np.array(ks["grid"]), np.array(ks["loglik"])
    fig, ax = plt.subplots(figsize=(6.2, 2.9))
    ax.axvspan(ks["ci_lo"] - 0.005, ks["ci_hi"] + 0.005, color=BLUE, alpha=0.12, lw=0, label=f"95% profile-likelihood interval [{ks['ci_lo']:.2f}, {ks['ci_hi']:.2f}]")
    ax.plot(g, ll - ll.max(), "-o", color=BLUE, ms=2.5, lw=1.4, label="Profile log-likelihood (relative to maximum)")
    ax.axhline(-1.92, color=MUTED, lw=0.8, ls=":")
    ax.text(g[0], -1.92, " -1.92 (chi-square 95% cut-off / 2)", va="bottom", fontsize=7, color=INK2)
    ax.axvline(ks["knot"], color=ORANGE, lw=1.2, ls="--", label=f"Selected knot = {ks['knot']:.2f}")
    ax.axhline(ks["loglik_linear_dti"] - ll.max(), color=INK2, lw=0.8, ls="--")
    ax.text(g[-1], ks["loglik_linear_dti"] - ll.max(), f"linear DTI (no hinge): {ks['loglik_linear_dti'] - ll.max():.1f} ", va="bottom", ha="right", fontsize=7, color=INK2)
    ax.set_xlabel("Candidate DTI knot k (grid 0.20 to 0.65, step 0.01)")
    ax.set_ylabel("Log-likelihood minus maximum")
    ax.set_title(f"Profile likelihood for the DTI hinge location (development training split, clean rows, n = {ks['n_fit']:,})")
    ax.legend(loc="lower left", fontsize=7)
    fw.save(fig, "dti_knot_profile", "Profile log-likelihood of the enhanced specification across candidate DTI knots, with 95% interval")


def iv_bars(fw: FigureWriter, iv: pd.DataFrame):
    fig, ax = plt.subplots(figsize=(6.2, 3.0))
    t = iv.sort_values("iv")
    cols = [ORANGE if "income" in c else BLUE for c in t.characteristic]
    ax.barh(t.characteristic, t.iv, color=cols, height=0.6)
    for th, lab in [(0.02, "0.02"), (0.10, "0.10"), (0.30, "0.30")]:
        ax.axvline(th, color=MUTED, lw=0.7, ls=":")
    for i, v in enumerate(t.iv):
        ax.text(v, i, f" {v:.3f}", va="center", fontsize=7, color=INK2)
    ax.set_xscale("log")
    ax.set_xlabel("Information value (log scale); reference lines at 0.02 / 0.10 / 0.30")
    ax.set_title("Information value by characteristic (development sample, 28,000 loans)")
    fw.save(fig, "fig05_information_value", "Information value of each characteristic; income shown raw (missing as its own bin) and as imputed by the model")


def roc_curves(fw: FigureWriter, curves: dict[str, tuple[np.ndarray, np.ndarray]], aucs: dict[str, str]):
    fig, ax = plt.subplots(figsize=(4.2, 3.8))
    for (name, (y, p)), c in zip(curves.items(), SERIES):
        fpr, tpr, _ = roc_curve(y, p)
        ax.plot(fpr, tpr, color=c, lw=1.6, label=f"{name}: AUC {aucs[name]}")
    ax.plot([0, 1], [0, 1], color=AXIS, lw=0.8, ls="--")
    ax.set_xlabel("False positive rate (non-defaulters flagged)")
    ax.set_ylabel("True positive rate (defaulters flagged)")
    ax.set_title("ROC curves, production model, by sample")
    ax.legend(loc="lower right")
    fw.save(fig, "fig06_roc", "ROC curves of the production model on development and out-of-time samples")


def discrimination_trend(fw: FigureWriter, t: pd.DataFrame):
    fig, axs = plt.subplots(1, 3, figsize=(9.2, 2.8), sharex=True)
    x = np.arange(len(t))
    for ax, m, lab in zip(axs, ["auc", "gini", "ks"], ["AUC", "Gini", "KS"]):
        cols = [BLUE if s.startswith("2023") else ORANGE for s in t["sample"]]
        ax.errorbar(x, t[m], yerr=[t[m] - t[f"{m}_lo"], t[f"{m}_hi"] - t[m]], fmt="none", ecolor=INK2, lw=1, capsize=3)
        ax.scatter(x, t[m], c=cols, s=36, zorder=3)
        ax.axhline(t[m].iloc[:2].mean(), color=MUTED, lw=0.8, ls=":")
        ax.set_xticks(x, t["sample"])
        ax.set_title(f"{lab} with 95% bootstrap CI")
        ax.set_ylabel(lab)
        for i, v in enumerate(t[m]):
            ax.text(i + 0.12, v, f"{v:.3f}", fontsize=6.5, color=INK2, va="center")
    _suptitle(fig, "Discrimination by vintage, production model (1,000 bootstrap resamples; dotted line = 2023 average)")
    fig.tight_layout()
    fw.save(fig, "fig07_discrimination_trend", "AUC, Gini and KS by vintage with 95% bootstrap confidence intervals")


def reliability(fw: FigureWriter, rel: dict[str, pd.DataFrame], cal: pd.DataFrame):
    names = list(rel)
    fig, axs = plt.subplots(1, len(names), figsize=(9.2, 3.1), sharey=False)
    for ax, n in zip(axs, names):
        g = rel[n]
        lim = max(g.observed.max(), g.predicted.max()) * 1.08
        ax.plot([0, lim], [0, lim], color=AXIS, lw=0.8, ls="--")
        ax.errorbar(g.predicted, g.observed, yerr=[g.observed - g.obs_lo, g.obs_hi - g.observed], fmt="o", color=BLUE,
                    ecolor=INK2, ms=4, lw=0.8, capsize=2)
        r = cal.set_index("sample").loc[n]
        ax.text(0.04, 0.96, f"HL p = {r.hl_p:.3f}\nSpiegelhalter p = {r.spiegelhalter_p:.3f}\nECE = {r.ece:.4f}\nslope = {r.calib_slope:.3f}",
                transform=ax.transAxes, va="top", fontsize=7, color=INK2)
        ax.set_title(f"{n}")
        ax.set_xlabel("Mean predicted PD (decile)")
        ax.set_ylabel("Observed default rate")
    _suptitle(fig, "Reliability: observed vs predicted PD by score decile, with 95% Jeffreys intervals")
    fig.tight_layout()
    fw.save(fig, "fig08_reliability", "Reliability diagrams (deciles) with Jeffreys intervals and calibration statistics")


def grade_backtest(fw: FigureWriter, gb: pd.DataFrame, samples: list[str]):
    fig, axs = plt.subplots(1, len(samples), figsize=(9.2, 3.0), sharey=True)
    for ax, s in zip(axs, samples):
        g = gb[gb["sample"] == s]
        ax.plot(g.grade, g.predicted_pd, "-", color=BLUE, lw=1.4, label="Predicted PD (grade mean)")
        ax.errorbar(g.grade, g.observed_dr, yerr=[g.observed_dr - g.obs_lo, g.obs_hi - g.observed_dr], fmt="none", ecolor=INK2, lw=0.8, capsize=2)
        for _, r in g.iterrows():
            ax.scatter(r.grade, r.observed_dr, color=STATUS[r.traffic_light], s=30, zorder=3, edgecolor="white", lw=0.6)
        ax.set_yscale("log")
        ax.set_xticks(range(1, 9))
        ax.set_xlabel("Master-scale grade (1 = lowest risk)")
        ax.set_title(s)
        nred = int((g.traffic_light == "red").sum())
        namb = int((g.traffic_light == "amber").sum())
        ax.text(0.04, 0.96, f"red: {nred}  amber: {namb}  green: {len(g) - nred - namb}", transform=ax.transAxes, va="top", fontsize=7, color=INK2)
    axs[0].set_ylabel("Default rate (log scale)")
    axs[0].legend(loc="lower right")
    _suptitle(fig, "Grade-level backtest: observed DR (dot, coloured by Jeffreys traffic light) vs predicted PD (line)")
    fig.tight_layout()
    fw.save(fig, "fig09_grade_backtest", "Per-grade Jeffreys backtest with traffic lights on development and out-of-time vintages")


def grade_mix(fw: FigureWriter, mix: pd.DataFrame, psi_g: float):
    fig, ax = plt.subplots(figsize=(6.2, 2.8))
    x = mix.grade.values
    ax.bar(x - 0.2, mix.dev_share, 0.38, color=BLUE, label="Development (2023H1-H2)")
    ax.bar(x + 0.2, mix.target_share, 0.38, color=ORANGE, label="2024H2")
    ax.set_xticks(x)
    ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1, 0))
    ax.set_xlabel("Master-scale grade (1 = lowest risk)")
    ax.set_ylabel("Share of loans")
    ax.set_title(f"Grade distribution, development vs 2024H2 (grade-level PSI = {psi_g:.3f})")
    ax.legend(loc="upper left")
    fw.save(fig, "fig10_grade_mix", "Distribution of loans across master-scale grades, development vs 2024H2")


def psi_csi(fw: FigureWriter, stab: dict):
    rows = []
    for s, v in stab.items():
        rows.append({"sample": s, "variable": "SCORE", "psi": v["score_psi"]})
        for k, val in v["csi"].items():
            if k != "channel_broker":
                rows.append({"sample": s, "variable": k, "psi": val})
    t = pd.DataFrame(rows)
    order = t[t["sample"] == "2024H2"].sort_values("psi").variable.tolist()
    fig, ax = plt.subplots(figsize=(6.2, 3.3))
    y = np.arange(len(order))
    for off, (s, c) in zip((-0.2, 0.2), (("2024H1", BLUE), ("2024H2", ORANGE))):
        vals = t[t["sample"] == s].set_index("variable").loc[order, "psi"]
        ax.barh(y + off, vals, 0.38, color=c, label=s)
    ax.axvline(0.10, color=STATUS["amber"], lw=1, ls="--")
    ax.axvline(0.25, color=STATUS["red"], lw=1, ls="--")
    ax.text(0.10, len(order) - 0.4, " 0.10 amber", fontsize=7, color=INK2)
    ax.text(0.25, len(order) - 0.4, " 0.25 red", fontsize=7, color=INK2)
    ax.set_yticks(y, order)
    ax.set_xlabel("PSI / CSI vs development (10 quantile bins)")
    ax.set_title("Population stability: score PSI and characteristic CSI, out-of-time vs development")
    ax.legend(loc="center right")
    fw.save(fig, "fig11_psi_csi", "Score PSI and characteristic CSI for 2024H1 and 2024H2 against development")


def score_distribution(fw: FigureWriter, scores: dict[str, np.ndarray]):
    fig, ax = plt.subplots(figsize=(6.2, 2.9))
    bins = np.logspace(-3, 0, 50)
    for (n, s), c in zip(scores.items(), SERIES):
        ax.hist(s, bins=bins, density=True, histtype="step", lw=1.6, color=c, label=n)
    ax.set_xscale("log")
    ax.set_xlabel("Predicted 12-month PD (log scale)")
    ax.set_ylabel("Density")
    ax.set_title("Score distribution by sample, production model")
    ax.legend(loc="upper left")
    fw.save(fig, "fig12_score_distribution", "Distribution of predicted PD by sample")


def benchmark_forest(fw: FigureWriter, t: pd.DataFrame):
    labels = {"enhanced_logit": "Enhanced logit (hinge + missing flag)", "gbm": "Gradient boosting (unconstrained)",
              "gbm_monotone": "Gradient boosting (monotone)", "no_region_logit": "Logit without region_risk"}
    samples = t["sample"].unique().tolist()
    fig, ax = plt.subplots(figsize=(6.4, 3.4))
    yt, yl = [], []
    k = 0
    for ci, ch in enumerate(labels):
        for si, s in enumerate(samples):
            r = t[(t.challenger == ch) & (t["sample"] == s)].iloc[0]
            yy = -(ci * (len(samples) + 1) + si)
            c = SERIES[si]
            ax.errorbar(r.auc_diff, yy, xerr=[[r.auc_diff - r.diff_lo], [r.diff_hi - r.auc_diff]], fmt="o", color=c, ms=4, lw=1, capsize=2,
                        label=s if ci == 0 else None)
            ax.text(r.diff_hi + 0.0006, yy, f"p={r.p_value:.1g}" if r.p_value < 0.001 else f"p={r.p_value:.3f}", va="center", fontsize=6.5, color=INK2)
            k += 1
        yt.append(-(ci * (len(samples) + 1) + 1))
        yl.append(labels[ch])
    ax.axvline(0, color=INK2, lw=0.8)
    ax.set_yticks(yt, yl)
    ax.set_xlabel("AUC difference, challenger minus production (95% DeLong CI)")
    ax.set_title("Benchmarking: paired DeLong tests vs production")
    ax.legend(loc="lower right", title="Sample", title_fontsize=7)
    fw.save(fig, "fig13_benchmark_delong", "AUC difference between each challenger and production with DeLong 95% CIs and p-values")


def segment_ratio(fw: FigureWriter, seg: pd.DataFrame, samples: list[str]):
    segs = [s for s in seg.segment.unique()]
    fig, axs = plt.subplots(1, len(samples), figsize=(9.2, 3.4), sharey=True)
    for ax, s in zip(axs, samples):
        g = seg[seg["sample"] == s].set_index("segment").loc[segs]
        y = np.arange(len(segs))[::-1]
        ax.axvspan(0.9, 1.1, color=GRID, alpha=0.6, lw=0)
        ax.axvline(1, color=INK2, lw=0.8)
        ax.scatter(g.production_ratio, y, color=BLUE, s=26, zorder=3, label="Production")
        ax.scatter(g.enhanced_ratio, y, color=ORANGE, marker="D", s=20, zorder=3, label="Enhanced challenger")
        ax.set_yticks(y, segs)
        ax.set_title(s)
        ax.set_xlabel("Observed / predicted default rate")
    axs[0].legend(loc="lower right")
    _suptitle(fig, "Segment calibration: observed/predicted ratio by segment (band = 0.90-1.10 monitoring green zone)")
    fig.tight_layout()
    fw.save(fig, "fig14_segment_calibration", "Observed-to-predicted ratio by business segment, production vs enhanced challenger")


def missing_income(fw: FigureWriter, t: pd.DataFrame):
    fig, ax = plt.subplots(figsize=(6.2, 2.9))
    x = np.arange(len(t))
    w = 0.26
    ax.bar(x - w, t.observed_dr, w, color=INK2, label="Observed default rate")
    ax.bar(x, t.production_pd, w, color=BLUE, label="Production mean PD (median-imputed)")
    ax.bar(x + w, t.enhanced_pd, w, color=ORANGE, label="Counterfactual with missing indicator")
    for i, r in t.reset_index(drop=True).iterrows():
        ax.text(i, r.production_pd - 0.01, f"O/P\n{r.production_obs_over_pred:.2f}", ha="center", va="top", fontsize=7, color="white", fontweight="bold")
    ax.set_xticks(x, [f"{s}\n(n = {n:,})" for s, n in zip(t["sample"], t.n_missing)])
    ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1, 0))
    ax.set_ylabel("Default rate / PD")
    ax.set_title("Income-missing borrowers: observed vs predicted PD")
    ax.legend(loc="upper left")
    fw.save(fig, "fig15_missing_income", "Observed default rate vs production and counterfactual PD for income-missing borrowers")


def elasticity(fw: FigureWriter, t: pd.DataFrame):
    t = t.sort_values("rank", ascending=False)
    fig, ax = plt.subplots(figsize=(6.2, 3.1))
    base = t.base_mean_pd.iloc[0]
    y = np.arange(len(t))
    ax.barh(y, t.pd_plus_1sd - base, left=base, color=ORANGE, height=0.55, label="+1 SD (broker: all broker)")
    ax.barh(y, t.pd_minus_1sd - base, left=base, color=BLUE, height=0.55, label="-1 SD (broker: none)")
    ax.axvline(base, color=INK, lw=0.8)
    ax.set_yticks(y, t.feature)
    ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1, 0))
    ax.set_xlabel(f"Portfolio mean PD (base = {base:.2%})")
    ax.set_title("One-at-a-time sensitivity: mean PD under +/- 1 SD input shocks (development, clean rows)")
    ax.legend(loc="lower right")
    fw.save(fig, "fig16_sensitivity_tornado", "Tornado chart of portfolio mean PD under +/- 1 SD shocks to each input")


def sobol(fw: FigureWriter, t: pd.DataFrame):
    t = t.sort_values("ST")
    fig, ax = plt.subplots(figsize=(6.2, 3.0))
    y = np.arange(len(t))
    ax.barh(y - 0.2, t.S1, 0.38, color=BLUE, xerr=[t.S1 - t.S1_lo, t.S1_hi - t.S1], ecolor=INK2, error_kw={"lw": 0.8}, label="First-order S1")
    ax.barh(y + 0.2, t.ST, 0.38, color=ORANGE, xerr=[t.ST - t.ST_lo, t.ST_hi - t.ST], ecolor=INK2, error_kw={"lw": 0.8}, label="Total ST")
    ax.set_yticks(y, t.feature)
    ax.set_xlabel("Share of PD variance")
    ax.set_title("Global sensitivity: Sobol indices of predicted PD (20,000 Monte-Carlo draws)")
    ax.legend(loc="lower right")
    fw.save(fig, "fig17_sobol", "First-order and total Sobol indices of predicted PD")


def fairness_tradeoff(fw: FigureWriter, f: pd.DataFrame):
    fig, axs = plt.subplots(1, 2, figsize=(9.2, 3.0))
    ax = axs[0]
    metrics = [("dp_diff", "Demographic parity\n(approval B - A)"), ("eo_diff", "Equal opportunity\n(TPR B - A)"), ("fpr_diff", "FPR gap\n(B - A)")]
    samples = f["sample"].unique().tolist()
    x = np.arange(len(metrics))
    w = 0.13
    k = 0
    for mi, (model, c) in enumerate((("production", BLUE), ("no_region_logit", ORANGE))):
        for si, s in enumerate(samples):
            r = f[(f.model == model) & (f["sample"] == s)].iloc[0]
            off = (k - (2 * len(samples) - 1) / 2) * w
            ax.bar(x + off, [100 * r[m] for m, _ in metrics], w * 0.92, color=c, alpha=0.55 + 0.45 * si / max(1, len(samples) - 1),
                   label=f"{'Production' if model == 'production' else 'Without region_risk'} {s}")
            k += 1
    ax.axhline(0, color=INK2, lw=0.8)
    ax.set_xticks(x, [m[1] for m in metrics])
    ax.set_ylabel("Percentage points")
    ax.set_title("Group fairness gaps at fixed production cut-off")
    ax.legend(fontsize=6.5, ncol=2, loc="upper center", bbox_to_anchor=(0.5, -0.22))
    ax = axs[1]
    for (model, c, mk) in (("production", BLUE, "o"), ("no_region_logit", ORANGE, "D")):
        g = f[f.model == model]
        ax.scatter(g.air, g.auc, color=c, marker=mk, s=34, label="Production" if model == "production" else "Without region_risk")
        for _, r in g.iterrows():
            ax.annotate(r["sample"], (r.air, r.auc), xytext=(4, -2), textcoords="offset points", fontsize=6.5, color=INK2)
    ax.axvline(0.80, color=STATUS["red"], lw=0.8, ls="--")
    ax.axvline(0.90, color=STATUS["amber"], lw=0.8, ls="--")
    ax.set_xlim(0.78, 1.0)
    ax.set_xlabel("Adverse impact ratio (B / A approval)")
    ax.set_ylabel("AUC")
    ax.set_title("Less-discriminatory-alternative trade-off")
    ax.legend(loc="lower left")
    fig.tight_layout()
    fw.save(fig, "fig18_fairness", "Group fairness gaps and AUC vs adverse impact ratio, production vs model without region_risk")


def calibration_by_group(fw: FigureWriter, rel: dict, sample: str):
    fig, ax = plt.subplots(figsize=(4.4, 3.6))
    lim = 0
    for cls, c, mk in (("A", BLUE, "o"), ("B", ORANGE, "D")):
        g = rel[sample][cls]
        ax.errorbar(g.predicted, g.observed, yerr=[g.observed - g.obs_lo, g.obs_hi - g.observed], fmt=mk, color=c, ecolor=c, ms=4, lw=0.8,
                    capsize=2, label=f"Group {cls} (n = {int(g.n.sum()):,})")
        lim = max(lim, g.obs_hi.max())
    ax.plot([0, lim], [0, lim], color=AXIS, ls="--", lw=0.8)
    ax.set_xlabel("Mean predicted PD (decile within group)")
    ax.set_ylabel("Observed default rate")
    ax.set_title(f"Calibration by protected-class group, {sample}")
    ax.legend(loc="upper left")
    fw.save(fig, "fig19_calibration_by_group", f"Reliability by simulated protected-class group, {sample}")


def importance_stability(fw: FigureWriter, imp: dict, features: list[str]):
    fig, axs = plt.subplots(1, 2, figsize=(9.2, 3.1), sharey=True)
    order = imp["gbm"]["table"].feature.tolist()[::-1]
    for ax, k, c, lab in ((axs[0], "gbm", ORANGE, "Gradient boosting"), (axs[1], "logit", BLUE, "Logistic (production recipe)")):
        raw = pd.DataFrame(imp[k]["raw"], columns=features)[order]
        ax.boxplot([raw[c_] for c_ in order], vert=False, widths=0.55, patch_artist=True,
                   boxprops={"facecolor": c, "alpha": 0.5, "edgecolor": c}, medianprops={"color": INK}, whiskerprops={"color": INK2},
                   capprops={"color": INK2}, flierprops={"markersize": 2, "markeredgecolor": INK2})
        ax.set_yticks(range(1, len(order) + 1), order)
        ax.set_xscale("symlog", linthresh=1e-3)
        ax.set_xlabel("Permutation importance (AUC drop, symlog scale)")
        ax.set_title(f"{lab}: mean pairwise Spearman = {imp[k]['mean_pairwise_spearman']:.3f}")
    _suptitle(fig, f"Feature-importance stability across {imp['n_boot']} bootstrap refits (scored on development test split)")
    fig.tight_layout()
    fw.save(fig, "fig20_importance_stability", "Bootstrap distribution of permutation importance, GBM vs logistic")


def monotonicity(fw: FigureWriter, curves: dict, mono: pd.DataFrame):
    feats = ["fico", "dti", "utilization"]
    fig, axs = plt.subplots(1, 3, figsize=(9.2, 2.9))
    for ax, f in zip(axs, feats):
        for (m, c, ls) in (("production", BLUE, "-"), ("gbm", ORANGE, "-"), ("gbm_monotone", AQUA, "--")):
            cv = curves[(f, m)]
            ax.plot(cv.grid, cv.pd, ls, color=c, lw=1.5, label={"production": "Production logit", "gbm": "GBM", "gbm_monotone": "GBM (monotone)"}[m])
        r = mono[(mono.feature == f) & (mono.model == "gbm")].iloc[0]
        ax.text(0.03 if f != "fico" else 0.40, 0.97, f"GBM reversals: {r.pd_curve_violations}/{r.n_steps}\nICE curves with reversal > 0.5pp: {r.ice_share_reversal_gt_50bp:.0%}",
                transform=ax.transAxes, va="top", fontsize=6.8, color=INK2)
        ax.set_xlabel(f)
        ax.set_title(f"Partial dependence: {f}")
        ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1, 0))
    axs[0].set_ylabel("Mean predicted PD")
    axs[2].legend(loc="lower right")
    _suptitle(fig, "Monotonicity check: partial dependence (1,000 applicants, development test split)")
    fig.tight_layout()
    fw.save(fig, "fig21_monotonicity", "Partial-dependence curves for FICO, DTI and utilization: production, GBM and monotone GBM")
