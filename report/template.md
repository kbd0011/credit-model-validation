<div class="cover">

# Independent Model Validation Report

## Consumer PD Model v1.0 (CR-PD-0142)

| | |
|:---|:---|
| **Model name** | Consumer PD Model v1.0: 12-month probability of default, unsecured consumer loans |
| **Model ID** | CR-PD-0142 |
| **Model owner (first line)** | Retail Credit Analytics |
| **Model use** | Underwriting approve/decline cut-off; risk-based pricing |
| **Model tier** | Tier 1 (highest materiality band) |
| **Standard applied** | SR 26-2 / OCC Bulletin 2026-13, Revised Guidance on Model Risk Management (April 17, 2026); bank Model Risk Management Policy |
| **Validation type** | Initial full-scope validation (model in production without prior independent validation) |
| **Validator** | Model Risk Management, Retail Credit Model Validation (second line) |
| **Validation period** | 2026-09-14 to 2026-11-06 |
| **Report date** | {{report_date}} |
| **Next scheduled review** | Full revalidation on redevelopment, no later than 2027-06-30; annual review thereafter |
| **Overall rating** | **FIT WITH CONDITIONS** |

</div>

<div class="note">

**Data notice.** The portfolio analysed in this report is synthetic. It was generated from a fully documented data-generating process (`data/make_data.py`) with known weaknesses, so that each finding can be traced to its cause. The validation code is data-agnostic and runs unchanged on a real portfolio. Model ID, owners, dates and policy references are illustrative.

</div>

## 1. Executive summary

**Overall rating: Fit with Conditions.** Consumer PD Model v1.0 rank-orders risk well and is accurate for the portfolio in aggregate. It may stay in use for underwriting and pricing, subject to the conditions in Section 1.3. The model's average accuracy hides two material segment-level errors. The model owner must remediate both through a time-bound redevelopment.

The validation used {{n_total}} loans across four half-year vintages. These comprised the development sample (2023H1 to 2023H2, {{n_dev}} loans) and two out-of-time (OOT) vintages that the developer never tested (2024H1, {{n_h1}} loans; 2024H2, {{n_h2}} loans). The validator reproduced the developer's results exactly before testing the model.

### 1.1 Key findings

- **Discrimination is strong and stable out of time.** AUC was {{auc_dev}} on development, {{auc_h1}} on 2024H1 and {{auc_h2}} on 2024H2 (95% bootstrap CIs). All three intervals overlap. KS was {{ks_dev}}, {{ks_h1}} and {{ks_h2}} (Figure 7).
- **Aggregate calibration passes every test, and all {{n_grade_tests_oot}} OOT grade-level backtests are green.** The observed-to-predicted (O/P) default ratio was {{op_h1}} on 2024H1 and {{op_h2}} on 2024H2. Hosmer-Lemeshow p-values were {{hl_p_dev}} (development), {{hl_p_h1}} (2024H1) and {{hl_p_h2}} (2024H2) (Table 5, Figures 8 and 9).
- **High (F-01): for borrowers with missing income, predicted PD is {{miss_under_lo}} to {{miss_under_hi}} below the observed default rate.** These borrowers are {{miss_share_dev}} of development loans. Their observed default rate was {{miss_obs_h2}} in 2024H2 against a predicted {{miss_pred_h2}} (O/P {{op_miss_h2}}). The O/P ratio was {{op_miss_dev}} on development and {{op_miss_h1}} on 2024H1. The cause is median imputation with no missing-value indicator. Borrowers who report income are over-predicted (O/P {{op_rep_range_all}} across the three samples), so the two errors offset in aggregate (Figures 10 and 14).
- **High (F-02): DTI enters the model linearly, but its effect on default is non-linear.** As a result, high-DTI borrowers are under-predicted. In the top DTI decile ({{seg_tail}}; {{dtitail_share_h2}} of 2024H2 loans), O/P was {{op_dtitail_dev}}, {{op_dtitail_h1}} and {{op_dtitail_h2}} on the three samples (each p < 0.0001). A challenger that adds a DTI hinge and a missing-income flag beat production on both OOT vintages: AUC {{d_enh_h1}} on 2024H1 and {{d_enh_h2}} on 2024H2, DeLong p {{p_enh_h2}} (Figures 2, 3 and 11).
- **Medium (F-03): the 2024H2 population shifted materially.** Score PSI reached {{psi_h2}} (amber), driven by FICO (CSI {{csi_fico_h2}}) and utilization (CSI {{csi_util_h2}}). Calibration held because the shift stayed inside the range the model was built on. However, the developer's "annual review" does not meet the standard for an ongoing monitoring plan.
- **Medium (F-04): `region_risk` partly proxies for the protected class, and no fair-lending review was documented.** Its correlation with the class is {{px_corr}}. The adverse impact ratio (AIR) of {{air_h2}} on 2024H2 passes the four-fifths threshold. Removing the variable raises AIR to {{air_nor_h2}} at an AUC cost of {{abs_nor_h2}}. That cost is small but statistically significant on 2024H2.
- **Other findings.** F-05 (Medium): no input range edits. F-06 (Medium): developer documentation incomplete. F-07 (Low): `income_log` is insignificant. F-08 (Low): early calibration drift in 2024H2. See the findings register (Section 11).

### 1.2 Use restrictions

1. Until F-01 is remediated, no PD for an income-missing applicant may be used for pricing or cut-off decisions without the interim overlay in Condition 1.
2. The model must not be applied to products or channels outside unsecured consumer instalment lending. Examples are secured lending and small-business borrowers.
3. Any applicant record that fails the range edits in Condition 3 must be referred for manual review. The model must not decline it automatically.

### 1.3 Conditions for use and required remediation

| # | Condition / remediation | Finding | Owner | Deadline |
|:--|:------------------------------------------------|:--------|:-------------|:--------|
| 1 | Apply an interim PD overlay to income-missing applicants. The validator's indicative pooled O/P multiplier is {{overlay_mult}}. The owner must calibrate and document the final overlay, and MRM must review it. | F-01 | Head of Retail Credit Analytics | 2026-12-11 |
| 2 | Redevelop the model with a missing-income indicator and a non-linear DTI term (or equivalent). Submit it for validation. | F-01, F-02, F-07 | Head of Retail Credit Analytics | 2027-03-31 |
| 3 | Implement input range edits (FICO 300 to 850, DTI 0 to 1) in the decision engine, with referral on failure. | F-05 | Retail Credit Technology | 2026-12-31 |
| 4 | Adopt the monitoring plan in `outputs/monitoring_thresholds.json`, including segment KPIs. The first quarterly pack is due by the deadline shown. | F-03, F-08 | Retail Credit Analytics | 2027-01-31 |
| 5 | Complete a fair-lending review of `region_risk`, including a documented less-discriminatory-alternative (LDA) decision. | F-04 | Fair Lending Compliance | 2027-01-31 |
| 6 | Bring the development documentation up to the bank's Model Documentation Standard. | F-06 | Retail Credit Analytics | 2027-03-31 |

If Condition 1 or 3 is missed, the rating becomes **Restricted Use** and the matter goes to the Model Risk Committee.

## 2. Scope, model description and intended use

### 2.1 Model description

Consumer PD Model v1.0 is an unpenalised logistic regression. It estimates the 12-month probability of default for unsecured consumer instalment loans at origination. It uses nine inputs: FICO, debt-to-income (DTI), revolving utilization, log income, inquiries in the last six months, delinquencies in the last 24 months, years in employment, a zip-level `region_risk` index and a broker-channel flag. Missing income is filled with the development-sample median (${{income_fill}}), and no missing-value indicator is used. The developer fit the model on a 70/30 random split of the 2023 vintages ({{n_train}} training and {{n_test}} test loans). The developer reported train and test AUCs of {{rep_train_rep}} and {{rep_test_rep}}. No out-of-time testing, sensitivity analysis or fair-lending review was performed. The monitoring plan was stated as "annual review".

### 2.2 Intended use and materiality

SR 26-2 states that model purpose, together with model exposure, determines model materiality.

- **Purpose.** The model makes automated underwriting decisions: it sets the approve/decline cut-off, and the policy approves the lowest-risk 70% of applicants (PD ≤ {{cutoff_pd}} at development). It also sets risk-based pricing tiers, and it drives adverse-action decisions under ECOA/Regulation B. A model error therefore changes credit losses, the price each customer pays and the bank's compliance with consumer-protection law.
- **Exposure.** Every applicant for an unsecured consumer instalment loan is scored. The four vintages reviewed contain {{n_total}} booked loans.

High-consequence purpose combined with portfolio-wide exposure places the model in the bank's highest materiality band (**Tier 1**). SR 26-2 states that higher-materiality models "warrant more comprehensive and rigorous oversight". Under the bank's policy, that means three things: a full-scope independent validation covering all three validation components, quarterly threshold-based monitoring, and an annual review.

### 2.3 Scope and approach

**Standard applied.** The validation applied SR 26-2, "Revised Guidance on Model Risk Management" (Federal Reserve, April 17, 2026). That guidance was issued jointly as OCC Bulletin 2026-13 and FDIC FIL-15-2026. It also applied the bank's Model Risk Management Policy and Model Validation Standard. SR 26-2 superseded SR 11-7 / OCC 2011-12 (April 4, 2011). It retains its predecessor's three validation components:

- conceptual soundness, with benchmarking listed as a practical assessment alternative;
- outcomes analysis;
- ongoing monitoring.

This validation covered all three. It also covered sensitivity analysis and fair lending, which the bank's policy requires. SR 26-2 does not set enforceable standards. The bank's policy makes these requirements binding internally. SR 26-2 also states that the quality of validation depends on the rigor and effectiveness of the review rather than the organizational structure of the risk function. The evidence in Sections 3 to 10 is presented so that its rigor can be judged directly.

The validator treated the model as a frozen artifact (`model/pd_model_v1.pkl`) and did not change it. All tests used the validator's own code base. That code includes independently written estimators: an IRLS logistic fit, DeLong, Jeffreys and Spiegelhalter tests, and PSI. Each estimator is unit-tested against closed-form results (`tests/test_stats.py`, {{n_unit_tests}} tests). Challenger models were fit on the developer's own training split, so every comparison is like-for-like. All results are reproducible from a single command (`make all`); see Appendix E.

## 3. Data review

**Table 1. Portfolio composition by vintage**

{{tbl_vintage}}

![Figure 1. Portfolio composition by vintage and default rate by income status (95% Jeffreys intervals).](../outputs/figures/fig01_vintage_profile.png){width=100%}

**Completeness.** Income was the only field with missing values: {{inc_miss_all}} of all loans, between {{inc_miss_min}} and {{inc_miss_max}} per vintage. The missingness is informative. Borrowers with missing income defaulted at {{dr_miss_all}}, against {{dr_present_all}} for borrowers who reported income (chi-square p {{chi2_p}}; Figure 1, right panel). A median fill without an indicator discards this signal. Sections 4 and 5 and finding F-01 address the consequences.

**Validity.** Range edits found {{n_bad}} invalid records ({{bad_rate}} of the portfolio): {{n_fico0}} with FICO = 0 and {{n_dti1}} with DTI > 1. These errors occur in every vintage. {{n_bad_train}} of them were in the developer's training sample. The production model scores the FICO = 0 records at a mean PD of {{pd_fico0}} and the DTI > 1 records at {{pd_dti1}}. These applicants would be declined automatically on erroneous data. Neither the development code nor the documentation contains input edits (F-05). The records are too few to bias the coefficients materially. The control gap is the issue. The {{n_dev_excl}} development loans that fail range edits are excluded from analyses that fit or profile relationships ({{n_dev_clean}} loans): functional-form plots, knot search, sensitivity and Sobol analysis, coefficient perturbation and the proxy tests. All discrimination, calibration, stability and fair-lending tests use the full {{n_dev}} development loans, because the production model scores every applicant. WOE/IV and the challenger fits also use all rows, matching the developer's recipe.

**Population.** The 2024H2 vintage differs from development. Mean FICO fell from {{fico_dev}} to {{fico_2024H2}}, mean utilization rose from {{util_dev}} to {{util_2024H2}}, and the default rate rose to {{dr_2024H2}}. The other inputs did not move (Section 8). 2024H1 closely matches development (score PSI {{psi_h1}}). No duplicate loan IDs were found.

## 4. Conceptual soundness

### 4.1 Methodology

Logistic regression is the industry-standard method for application PD and is appropriate for this use. It is transparent and stable. It also produces the reason codes that adverse-action notices require. The validator does not object to the method. The objections concern two specification choices: the treatment of missing income and the functional form of DTI. It also objects to the absence of out-of-time evidence.

### 4.2 Replication

The validator re-ran the developer's documented recipe independently. The recipe covered the split seed, median imputation and estimator. The largest coefficient difference from the frozen artifact was {{rep_coef_diff}}, and the largest score difference was {{rep_score_diff}}. Scoring the frozen artifact reproduced the reported AUCs: train {{rep_train_auc}} (reported {{rep_train_rep}}; difference {{rep_train_diff}}) and test {{rep_test_auc}} (reported {{rep_test_rep}}; difference {{rep_test_diff}}). The pre-set tolerance was half a unit in the fourth decimal place (5e-5). Both values passed, as did the sample counts. **Replication passed.** The model in production is the model that was documented.

### 4.3 Coefficients, signs and collinearity

**Table 2. Production coefficients with Wald statistics (information matrix on the developer's training split)**

{{tbl_wald}}

All nine signs match economic expectation. {{n_sig}} of the nine inputs are significant at the 1% level. The exception is `income_log` (z = {{inc_z}}, p = {{inc_p}}, F-07). All variance inflation factors are at most {{vif_max}}, so collinearity is negligible. The intercept ({{intercept}}) is large because the inputs are not centred. The intercept is strongly correlated with the FICO and income coefficients (correlations {{cp_corr_fico}} and {{cp_corr_inc}}). Section 7.2 shows why this matters for sensitivity testing.

### 4.4 Characteristic analysis (WOE / IV)

**Table 3. Information value on development data**

{{tbl_iv}}

FICO dominates (IV {{iv_fico}}). Raw income with missing values as their own bin has IV {{iv_inc_raw}}, and **{{iv_inc_missing_share}} of that comes from the missing bin alone** (Figure 5). The model actually sees median-imputed `income_log`, which has IV {{iv_inc_imp}}. That value is also inflated, because the imputed median bin collects the high-risk missing records. The linear coefficient cannot use this signal. Income therefore matters to default only through its missingness, and the model specification discards exactly that information. `region_risk` has a low standalone IV ({{iv_region}}). It is still significant in the multivariate model and is examined in Section 9.

![Figure 5. Information value by characteristic.](../outputs/figures/fig05_information_value.png){width=78%}

### 4.5 Functional form

Binned empirical log-odds were compared with the model's predicted log-odds across 20 equal-count bins (Figures 2 and 4). FICO is well described by a linear term. DTI is not. Empirical log-odds are flat up to about {{knot}} and then rise steeply. The linear term over-predicts the middle of the range: at DTI ≈ {{dti_mid_x}}, predicted PD is {{dti_mid_pred}} against an observed {{dti_mid_obs}}. It under-predicts the top bin: at DTI ≈ {{dti_top_x}}, predicted PD is {{dti_top_pred}} against an observed {{dti_top_obs}}. Above {{knot}}, the mean residual relative to the low-DTI linear trend is +{{dti_tail_resid}} on the logit scale. When a hinge at the data-selected knot is added, its coefficient is {{hinge_coef}}, and the linear DTI coefficient falls from {{prod_dti_coef}} to {{enh_dti_coef}}. The validator's challenger tracks the empirical curve within its confidence band (F-02).

**Knot estimation.** The validator estimated the hinge location from the data rather than assuming it. A profile-likelihood search fitted the enhanced specification (nine production inputs, an income-missing flag and max(DTI − k, 0)) for every k from 0.20 to 0.65 in steps of 0.01. The fits used the developer's training split ({{knot_nfit}} loans that pass range edits). The log-likelihood peaks at **k = {{knot}}**, with a 95% profile-likelihood interval of [{{knot_lo}}, {{knot_hi}}] (Figure 3). Relative to a linear-DTI specification, the hinge raises twice the log-likelihood by {{knot_lr}}. The knot was selected from the same data, so this statistic is descriptive and not a formal chi-square test. The selected knot defines the challenger's hinge, the DTI segment ("{{seg_knot}}") and the corresponding monitoring KPI. The high-DTI tail segment ("{{seg_tail}}") is the top decile of development DTI.

![Figure 2. DTI: empirical vs model log-odds. The production model's linear term misses the change in slope near the data-selected knot.](../outputs/figures/fig02_dti_functional_form.png){width=88%}

![Figure 3. Profile log-likelihood for the DTI knot, with the 95% interval shaded.](../outputs/figures/fig03_dti_knot_profile.png){width=88%}

![Figure 4. FICO: empirical vs model log-odds. The linear form is adequate.](../outputs/figures/fig04_fico_functional_form.png){width=88%}

### 4.6 Documentation quality

The developer documentation (`model/developer_documentation.json`) records the purpose, sample, coefficients, imputation and train/test AUC. It lacks the following elements, which the bank's documentation standard requires for a Tier 1 model (F-06):

- assumptions and limitations;
- a justification for each variable, including `region_risk` and `income_log`;
- an analysis of alternative specifications;
- out-of-time testing;
- calibration testing beyond AUC;
- sensitivity analysis;
- a fair-lending review;
- an implementation and input-control description;
- a monitoring plan with thresholds.

The documentation was sufficient to replicate the model exactly. It was not sufficient for a reviewer to judge whether the model is fit for purpose.

## 5. Outcomes analysis

### 5.1 Discrimination

**Table 4. Discrimination with 95% bootstrap confidence intervals ({{n_boot}} resamples)**

{{tbl_disc}}

Discrimination did not deteriorate out of time. The 2024H2 AUC ({{aucp_h2}}) is {{auc_drop_h2}} below development, and the confidence intervals overlap almost completely. Variation between the two development vintages (2023H1 {{aucp_v1}}, 2023H2 {{aucp_v2}}) is larger than the OOT movement, so the movement is consistent with sampling noise. The lower AUC on the developer's random test split ({{aucp_test}}) reflects the same noise. That split's interval is the widest in the table because it is the smallest sample.

![Figure 6. ROC curves by sample.](../outputs/figures/fig06_roc.png){width=52%}

![Figure 7. AUC, Gini and KS by vintage with 95% bootstrap intervals.](../outputs/figures/fig07_discrimination_trend.png){width=100%}

<div style="page-break-before: always;"></div>

### 5.2 Calibration

**Table 5. Calibration tests**

{{tbl_cal}}

Aggregate calibration is strong on all three samples. No test rejects at 5%. The tests were calibration-in-the-large, Spiegelhalter, Hosmer-Lemeshow and the recalibration slope. HL p-values are shown with g − 2 = 8 degrees of freedom. On the OOT samples the stricter g = 10 convention gives larger p-values: {{hl_pg_h1}} and {{hl_pg_h2}}. Calibration slopes of {{slope_dev}} to {{slope_h2}} show no over-fitting.

On 2024H2 the expected calibration error rose to {{ece_h2}}, {{ece_ratio_h2}} times its development value. {{bins_out_h2}} of 10 deciles fell outside their 95% Jeffreys interval: {{bins_out_desc}}. Both are {{bins_out_direction}}, which is the conservative direction. This is an early drift signal (F-08), not a calibration failure.

![Figure 8. Reliability by decile, with Jeffreys intervals.](../outputs/figures/fig08_reliability.png){width=100%}

### 5.3 Grade-level backtesting

The validator built an 8-grade master scale with equal-population grades on development PD. The upper bounds were {{ms_bounds}}. In each grade, observed defaults were tested against the grade's mean PD with a one-sided Jeffreys test for under-estimation (green p ≥ 0.05, amber 0.01 to 0.05, red p < 0.01). An exact binomial test was run as a cross-check.

**Table 6. Grade-level backtest, out-of-time vintages**

{{tbl_grades}}

All {{n_grade_tests_oot}} OOT grade tests were green ({{n_red_oot}} red, {{n_amber_oot}} amber). On development, {{n_amber_dev}} grade was amber: {{dev_amber_desc}}. It was green on both OOT vintages.

![Figure 9. Grade-level backtest with Jeffreys traffic lights.](../outputs/figures/fig09_grade_backtest.png){width=100%}

### 5.4 Segment calibration

Grade-level and aggregate tests can pass even when one segment is wrong, because errors in different segments offset. The validator therefore tested calibration within business segments (Table 7, Figure 10).

**Table 7. Observed/predicted by segment, out-of-time vintages (production vs enhanced challenger)**

{{tbl_seg}}

Two segments fail on every sample. **Income-missing borrowers** are under-predicted by a factor of {{op_miss_dev}}, {{op_miss_h1}} and {{op_miss_h2}}. Income-reporting borrowers are over-predicted (O/P {{op_rep_dev}}, {{op_rep_h1}}, {{op_rep_h2}}). The model therefore charges reporting borrowers for losses that come from non-reporting ones. **Borrowers in the top DTI decile ({{seg_tail}})** are under-predicted by {{op_dtitail_dev}}, {{op_dtitail_h1}} and {{op_dtitail_h2}}. The broader {{seg_knot}} segment is significant at 1% only on 2024H1 (Jeffreys p {{dtiknot_p_h1}}), because over-prediction in the {{knot}} to {{tail}} band offsets the tail. With only two terms added, the enhanced challenger brings income-missing O/P to {{eop_miss_range}} and {{seg_tail}} O/P to {{eop_dtitail_range}} across the three samples. Each error therefore has a single identified cause.

![Figure 10. Segment calibration: observed/predicted ratio, production vs enhanced challenger.](../outputs/figures/fig10_segment_calibration.png){width=100%}

## 6. Benchmarking

SR 26-2 lists benchmarking as a practical assessment alternative under conceptual soundness. The validator fit four challengers on the developer's training split. The **enhanced logit** is the production recipe plus a missing-income indicator and a DTI hinge at the data-selected knot ({{knot}}); it is the minimal fix for F-01 and F-02. The **GBM** is unconstrained gradient boosting on the nine production inputs. The **monotone GBM** is the same model with monotonicity constraints. The **logit without region_risk** is the LDA candidate. Each challenger was compared with production on the same loans using the paired DeLong test.

**Table 8. Challenger comparison (DeLong)**

{{tbl_bench}}

![Figure 11. AUC difference vs production with 95% DeLong intervals.](../outputs/figures/fig11_benchmark_delong.png){width=90%}

The enhanced logit beats production on every sample: {{d_enh_test}} (dev test), {{d_enh_h1}} (2024H1) and {{d_enh_h2}} (2024H2), all p < 0.0001. The unconstrained GBM gains less: {{d_gbm_h1}} (p {{p_gbm_h1}}) and {{d_gbm_h2}} (p {{p_gbm_h2}}). The two-term logit also beats the GBM by {{gbm_minus_enh_h2}} AUC on 2024H2. The evidence therefore points to a **specification gap, not a methodology gap**. The production model leaves signal unused because of two named design choices, not because logistic regression is too simple. A switch to machine learning is not warranted. The fix is a re-specified logistic model.

## 7. Sensitivity and stress testing

### 7.1 Input sensitivity

**Table 9. One-at-a-time sensitivity and Sobol indices (development, clean rows; base mean PD {{base_pd}})**

{{tbl_elast}}

The model responds to its inputs in the expected direction and in plausible proportion. FICO dominates. A ±1 SD move takes mean PD from {{base_pd}} to {{fico_plus}} or {{fico_minus}}. FICO also explains {{s1_fico}} of PD variance on its own (first-order Sobol index) and {{st_fico}} including interactions. DTI (S1 {{s1_dti}}) and utilization (S1 {{s1_util}}) follow. First-order indices sum to {{s1_sum}}. The remainder is interaction created by the logistic link, which is expected. `income_log` has almost no influence (total index {{st_inc}}), consistent with F-07.

![Figure 12. Mean PD under ±1 SD shocks.](../outputs/figures/fig12_sensitivity_tornado.png){width=85%}

![Figure 13. Sobol indices with bootstrap CIs.](../outputs/figures/fig13_sobol.png){width=85%}

A combined stress scenario (FICO −30, utilization +0.10, inquiries +1) raised the mean PD to {{stress_pd}}, an increase of {{stress_rel}}. The response is monotone and has no discontinuities.

### 7.2 Parameter uncertainty

**Table 10. Coefficient perturbation at the fixed cut-off (PD {{cp_cutoff}})**

{{tbl_cp}}

Shifting one coefficient by 1 SE while holding the others fixed (the naive test) suggests the model is fragile. On this test, 1 SE on the intercept flips {{cp_naive_int_flip}} of decisions, and 1 SE on `income_log` flips {{cp_naive_inc_flip}}. That result is an artifact of uncentred inputs: the naive test produces coefficient combinations the data rule out. With the other coefficients moved by their conditional expectation (the covariance-consistent test), no single 1 SE shift flips more than {{cp_cond_max_flip}} of decisions. None moves the approval rate by more than {{cp_cond_max_app}} pp. A joint draw of all coefficients from their sampling distribution (2,000 draws) gives a 90% range for the approval rate of {{cp_app_lo}} to {{cp_app_hi}} and for mean PD of {{cp_pd_lo}} to {{cp_pd_hi}}. In the median draw, {{cp_flip_med}} of decisions flip. **Estimation error is not a material source of model risk.**

### 7.3 Missing-income counterfactual

**Table 11. Income-missing borrowers: observed vs predicted**

{{tbl_miss}}

Changing the imputation value does not fix F-01. Filling missing income at the 10th or 90th percentile moves the development PD for these borrowers only between {{fill_p10_dev}} and {{fill_p90_dev}}, because `income_log` has almost no weight. The gap requires a missing-value indicator. In the challenger, that indicator has a coefficient of {{miss_coef}} (odds ratio {{miss_or}}). It closes the gap on every sample. Without the fix, the model under-predicted defaults among income-missing borrowers by {{miss_excess_dev}} (development), {{miss_excess_h1}} (2024H1) and {{miss_excess_h2}} (2024H2).

![Figure 14. Income-missing borrowers: observed vs production vs counterfactual PD.](../outputs/figures/fig14_missing_income.png){width=78%}

## 8. Stability and ongoing monitoring

### 8.1 Population stability

**Table 12. Score PSI and characteristic CSI vs development**

{{tbl_psi}}

2024H1 is stable (score PSI {{psi_h1}}). 2024H2 is amber (score PSI {{psi_h2}}). The shift is confined to FICO (CSI {{csi_fico_h2}}) and utilization (CSI {{csi_util_h2}}). Every other input has a CSI below 0.01.

At the grade level, the share of loans in the riskiest grade rose from {{g8_dev}} to {{g8_h2}}, and the share in the safest grade fell from {{g1_dev}} to {{g1_h2}} (grade PSI {{grade_psi}}). At the fixed production cut-off, the approval rate fell from {{app_dev}} to {{app_h2}}.

The shift is a change in borrower mix along variables the model already uses (covariate shift), not a change in how those variables relate to default (concept drift). Outcomes analysis confirms this: 2024H2 calibration and discrimination held. The shift is therefore not a defect of the model. It is still a risk that must be monitored, because the next shift may fall outside the development range (F-03).

![Figure 15. Score PSI and characteristic CSI.](../outputs/figures/fig15_psi_csi.png){width=85%}

![Figure 16. Score distribution by sample.](../outputs/figures/fig16_score_distribution.png){width=78%}

![Figure 17. Grade distribution, development vs 2024H2.](../outputs/figures/fig17_grade_mix.png){width=78%}

A true obligor-level grade migration matrix cannot be estimated from origination data, because each loan is observed only once. The validator reports the grade-mix migration above instead. It also reports a 2024H2 reclassification matrix comparing the production grade with the grade the enhanced challenger would assign (Table 13). The remediation would change the grade of {{moved}} of 2024H2 loans. {{within_one}} of loans stay within one grade. {{n_far}} loans move two or more grades. Of these, {{far_miss}} are income-missing borrowers and {{far_up}} move to a riskier grade.

**Table 13. 2024H2 reclassification: production grade (rows) vs enhanced-challenger grade (columns), loan counts**

{{tbl_reclass}}

### 8.2 Proposed monitoring plan

The developer's plan of "annual review" has no KPIs, thresholds or escalation. That does not meet the ongoing-monitoring component of SR 26-2. That component asks whether the model still performs as expected as products, data and market conditions change, and it notes that a model which no longer does so "may warrant overlays, adjustment, or redevelopment". The bank's policy requires such monitoring to be threshold-based for a Tier 1 model. The validator specified a {{n_kpis}}-KPI plan with pre-set thresholds, owners and escalation. It is delivered in machine-readable form at `outputs/monitoring_thresholds.json` (Table 14). Two consecutive amber results count as red. The segment KPIs for income-missing and high-DTI loans stay in force until F-01 and F-02 are closed.

**Table 14. Monitoring KPIs and thresholds**

{{tbl_monitor}}

## 9. Fair lending and disparate impact

The portfolio carries a simulated protected-class flag (group B; group A is the control group). It is used only for testing, as a stand-in for the proxy-based methods (e.g., BISG) that a lender would use in practice. All metrics are measured at the fixed production cut-off.

**Table 15. Group outcome metrics, production vs model without `region_risk`**

{{tbl_fair}}

**Disparate-impact testing.** The production model approved group B less often than group A on every sample. AIR was {{air_dev}} (development), {{air_h1}} (2024H1) and {{air_h2}} (2024H2). On 2024H2 the demographic-parity difference (approval rate, B minus A) was {{dp_h2}} pp. The equal-opportunity difference (the same gap among borrowers who did not default) was {{eo_h2}} pp, and the FPR gap (among borrowers who defaulted) was {{fpr_h2}} pp. Every AIR is above the four-fifths threshold (0.80) and the bank's internal review trigger (0.90). The model therefore does not breach a disparate-impact screen.

**Differential validity.** The model is equally accurate for both groups. Within-group AUC on 2024H2 was {{auc_A_h2}} (A) and {{auc_B_h2}} (B). O/P was {{cr_A_h2}} (A) and {{cr_B_h2}} (B) (Figure 19).

**Proxy analysis.** `region_risk` is a partial proxy for group membership. Its correlation with group B is {{px_corr}}. On its own it predicts group membership with an AUC of {{px_auc}}. Mean `region_risk` is {{px_rr_A}} in group A and {{px_rr_B}} in group B. Two likelihood-ratio tests on development data separate proxy effect from risk signal. First, `region_risk` stays predictive after controlling for group membership (LR = {{lr_rr}}, p = {{lr_rr_p}}). Its average marginal effect is {{ame_with}} pp of PD per unit (SE {{ame_with_se}}) with group in the model, against {{ame_without}} pp without it, an attenuation of only {{ame_att}}. Second, group membership adds nothing once the nine inputs are in the model (LR = {{lr_cls}}, p = {{lr_cls_p}}). Taken together, `region_risk` carries genuine default signal and is not mainly standing in for group membership. The raw default-rate gap (A {{px_dr_A}}, B {{px_dr_B}}) is fully explained by the model's inputs.

**Less discriminatory alternative.** Removing `region_risk` raises AIR to {{air_nor_dev}}, {{air_nor_h1}} and {{air_nor_h2}}. It costs {{abs_nor_test}}, {{abs_nor_h1}} and {{abs_nor_h2}} AUC on the dev test, 2024H1 and 2024H2 samples (DeLong p {{p_nor_test}}, {{p_nor_h1}}, {{p_nor_h2}}). The alternative has a cost the AUC change does not show: group B becomes under-predicted (O/P {{nor_cr_B_h2}} on 2024H2, against {{cr_B_h2}} for production). That shortfall is mispriced risk.

**Regulatory assessment.** Under ECOA and Regulation B, a facially neutral variable that disproportionately disadvantages a protected class must serve a legitimate business need that a less discriminatory alternative cannot meet reasonably well. The evidence here supports business justification but also identifies a viable LDA at small cost. The trade-off is a fair-lending policy decision, not a modelling decision. The developer did not document any analysis of it. The regulatory posture on disparate-impact enforcement has changed in recent years, and state law and private litigation risk remain. The bank's Fair Lending Policy still requires the analysis. The validator rates this finding Medium (F-04): the evidence shows no current breach, but the control gap is real.

![Figure 18. Group fairness gaps and the AUC vs AIR trade-off.](../outputs/figures/fig18_fairness.png){width=100%}

![Figure 19. Calibration by group, 2024H2.](../outputs/figures/fig19_calibration_by_group.png){width=52%}

## 10. Validating an ML challenger: what would change

The GBM challenger is not proposed for production (Section 6). It does, however, show how the same framework applies to a machine-learning credit model, and why such a model would require more evidence before approval. SR 26-2 covers non-generative, non-agentic AI/ML models such as this GBM. Generative and agentic AI fall outside it and are governed under the organization's broader risk management practices. This section is therefore within the scope of the guidance.

**Explanation stability.** The GBM and the production recipe were each refit on {{imp_nboot}} bootstrap resamples. Permutation importance (AUC drop) was then measured on the fixed development test split (Figure 20). The logistic recipe kept the same top-three inputs in {{imp_top3_logit}} of resamples, and its rankings had a mean pairwise Spearman correlation of {{imp_rho_logit}}. The GBM kept the same top three in only {{imp_top3_gbm}} (Spearman {{imp_rho_gbm}}, minimum {{imp_min_gbm}}). Low-importance inputs were unstable: the GBM's coefficient of variation was {{cv_emp_gbm}} for `employment_years` and {{cv_region_gbm}} for `region_risk`. Adverse-action reason codes built from such importances would change between model refreshes for the same applicant.

The GBM also gives `income_log` a mean importance of {{imp_inc_gbm}} (mean rank {{imp_inc_rank_gbm}}), against {{imp_inc_logit}} (rank {{imp_inc_rank_logit}}) for the logit. Trees can isolate the exact imputed value ${{income_fill}} and so recover the missing-income flag. Part of the GBM's advantage over production is therefore F-01 rediscovered by accident. An ML validation must look for this kind of hidden leakage of data handling into the model.

![Figure 20. Bootstrap stability of permutation importance.](../outputs/figures/fig20_importance_stability.png){width=100%}

**Monotonicity.** On the unconstrained GBM, partial-dependence curves reversed direction {{mono_dti_viol}} times for DTI (largest reversal {{mono_dti_max}} pp) and {{mono_utilization_viol}} times for utilization ({{mono_utilization_max}} pp). At the individual level, {{mono_dti_ice}} (DTI) and {{mono_utilization_ice}} (utilization) of applicant ICE curves contained a reversal larger than 0.5 pp. Even for FICO, where the average curve was monotone, {{mono_fico_ice}} of ICE curves reversed. A model in which higher debt lowers predicted risk for some applicants cannot support a credible adverse-action reason. The monotone-constrained GBM removed every reversal, and it scored *higher* out of time than the unconstrained version (2024H2 AUC {{a_mono_h2}} vs {{a_gbm_h2}}).

**Table 16. Monotonicity checks (development test split; 25-point grid; 1,000 ICE curves)**

{{tbl_mono}}

![Figure 21. Partial dependence for FICO, DTI and utilization.](../outputs/figures/fig21_monotonicity.png){width=100%}

**Additional requirements for an ML model.** An ML credit model would need four things beyond what this report tests:

- Reason-code generation that is accurate for each individual applicant. CFPB Circulars 2022-03 and 2023-03 confirm that the adverse-action notice requirements of ECOA/Regulation B apply in full to complex models.
- Monotonic constraints on all policy-relevant inputs.
- Hyperparameter governance, with the tuning protocol and seeds documented and reproducible.
- An explicit test of whether data-handling artifacts are learned as signal.

<div style="page-break-before: always;"></div>

## 11. Findings register

**Severity definitions.** *High:* a deficiency that can cause material financial loss, a mis-stated risk estimate or a regulatory breach. It requires a use restriction or compensating control until remediated (target ≤ 6 months). *Medium:* a weakness that does not currently produce a material error but could do so, or a significant gap in a required control or documentation (target ≤ 6 months). *Low:* a minor weakness or improvement with limited impact (target ≤ 12 months, or next redevelopment).

| ID | Severity | Category | Description | Evidence | Root cause | Recommendation | Owner | Target date |
|:----|:------|:--------|:----------------------------------|:-------|:--------------|:-----------------|:---------|:---------|
| F-01 | **High** | Conceptual soundness / data | Income-missing borrowers ({{miss_share_dev}} of loans) are under-predicted: O/P {{op_miss_dev}} (dev), {{op_miss_h1}} (2024H1), {{op_miss_h2}} (2024H2), p < 0.0001. Income-reporting borrowers are over-predicted (O/P {{op_rep_range_all}}). | Tables 7, 11; Figs 10, 14 | Median imputation without a missing indicator discards informative missingness. | Interim overlay (Condition 1); add a missing indicator at redevelopment. | Retail Credit Analytics | Overlay 2026-12-11; fix 2027-03-31 |
| F-02 | **High** | Conceptual soundness | Linear DTI term misses the change in slope at {{knot}} (data-selected; 95% CI {{knot_lo}} to {{knot_hi}}). {{seg_tail}} is under-predicted: O/P {{op_dtitail_dev}}, {{op_dtitail_h1}}, {{op_dtitail_h2}} (p < 0.0001). | Figs 2, 3, 10; Tables 7, 8 | Functional form not tested in development. | Re-specify DTI (hinge, spline or binned WOE); monitor the {{seg_knot}} segment KPI in the interim. | Retail Credit Analytics | 2027-03-31 |
| F-03 | Medium | Ongoing monitoring | 2024H2 score PSI {{psi_h2}} (amber); FICO CSI {{csi_fico_h2}}, utilization CSI {{csi_util_h2}}. Approval rate at the fixed cut-off fell from {{app_dev}} to {{app_h2}}. The plan was "annual review" with no thresholds. | Table 12; Figs 15 to 17 | No monitoring framework defined at development. | Adopt the {{n_kpis}}-KPI plan (Table 14) with quarterly reporting. | Retail Credit Analytics | 2027-01-31 |
| F-04 | Medium | Fair lending | `region_risk` is a partial proxy (correlation {{px_corr}}). AIR {{air_h2}} on 2024H2; an LDA reaches AIR {{air_nor_h2}} at AUC cost {{abs_nor_h2}}. No fair-lending review was documented. | Table 15; Figs 18, 19 | Fair-lending review omitted from the development process. | Document business justification and the LDA decision; add AIR to monitoring. | Fair Lending Compliance; Retail Credit Analytics | 2027-01-31 |
| F-05 | Medium | Data / implementation | {{n_bad}} range violations (FICO = 0, DTI > 1), {{n_bad_train}} of them in training data, scored at mean PD {{pd_fico0}} and {{pd_dti1}}. No input edits. | Table 1; Section 3 | No input validation in pipeline or decision engine. | Add range edits with manual referral; add a DQ KPI. | Retail Credit Technology | 2026-12-31 |
| F-06 | Medium | Documentation | No assumptions, limitations, OOT test, calibration test, sensitivity analysis, variable justification or monitoring plan. | Section 4.6 | Documentation standard not applied. | Remediate to the Model Documentation Standard as part of redevelopment. | Retail Credit Analytics | 2027-03-31 |
| F-07 | Low | Conceptual soundness | `income_log` is not significant (z = {{inc_z}}, p = {{inc_p}}) and has total Sobol index {{st_inc}}. It is retained without justification. | Tables 2, 9 | Variable selection not documented. | Re-assess at redevelopment once the missing indicator is added. | Retail Credit Analytics | 2027-03-31 |
| F-08 | Low | Outcomes | 2024H2: {{bins_out_h2}} deciles outside their 95% interval (over-predicted); ECE {{ece_h2}} vs {{ece_dev}} at development; HL p {{hl_p_h2}}. No grade is red. | Table 5; Fig 8 | Early effect of population shift. | Track via the calibration KPIs; investigate if amber for two quarters. | Retail Credit Analytics | 2027-01-31 |

## 12. Limitations of this validation and conditions for use

**Limitations.**

- The data are synthetic. The effect sizes are realistic but are not estimates for any real portfolio.
- The protected-class flag is directly observed. In practice it would be inferred (e.g., BISG), which adds measurement error to every fairness metric.
- Twelve-month outcomes are observed for every vintage. In production, the latest vintage would be immature, and monitoring would rely on early-delinquency proxies.
- No economic downturn appears in the sample. The stress scenario is a sensitivity test, not a macroeconomic stress test.
- Implementation testing was limited to scoring the frozen artifact in Python. The production decision engine was not tested.
- Challenger hyperparameters were fixed, not tuned. Challenger AUCs are therefore lower bounds.

**Conditions for use** are listed in Section 1.3. MRM will track each condition in the model inventory. Closing a condition requires evidence reviewed by MRM. Failure to meet Condition 1 or 3 on time moves the rating to Restricted Use.

## Appendix A. Full Wald table

See Table 2 (Section 4.3). The coefficient covariance comes from the information matrix on the developer's {{n_train}} training loans. Using all {{n_dev}} development loans would understate the standard errors by about 17%.

<div style="page-break-before: always;"></div>

## Appendix B. Decile tables

**B.1 Development ({{n_dev}} loans)**

{{tbl_dec_dev}}

**B.2 2024H1 ({{n_h1}} loans)**

{{tbl_dec_2024H1}}

**B.3 2024H2 ({{n_h2}} loans)**

{{tbl_dec_2024H2}}

## Appendix C. PSI / CSI detail

PSI uses 10 quantile bins fixed on the development distribution, with empty bins floored at 10⁻⁶. Thresholds: < 0.10 stable, 0.10 to 0.25 amber, ≥ 0.25 red. For the binary `channel_broker`, Table 12 reports the absolute change in the broker share. Full tables: `outputs/tables/psi_csi.csv`, `outputs/tables/stability.json`.

## Appendix D. Figure index

{{tbl_figs}}

## Appendix E. Reproducibility statement

The full validation reproduces from a clean checkout with `make all`. That command regenerates the data, refits and freezes the production model, runs the validation, runs the unit tests and builds this report. Every number in this report is inserted from `outputs/` by `report/build_report.py`. Before rendering, the builder re-tests the evidence behind each finding and refuses to publish if the evidence no longer supports the register.

- **Code version:** {{git_commit}}. The SHA-256 content hashes in Table E.1 identify the exact data, model artifact and validation code used.
- **Run timestamp:** {{run_date}}; Python {{py_ver}}; {{libs}}
- **Random seeds:** {{seeds}}
- **Bootstrap:** {{n_boot}} resamples for discrimination CIs; {{imp_nboot}} refits for importance stability; 2,000 coefficient draws; 20,000 Sobol base samples


**Table E.1. Content hashes of inputs and validation code**

{{tbl_hash}}
