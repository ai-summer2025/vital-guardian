#!/usr/bin/env python3
"""
test_vital_guardian.py — Unit tests for vital_guardian.py

Covers:
  - qSOFA score calculation (all threshold combinations)
  - SIRS criteria calculation
  - NEWS2 score calculation
  - Trend detection (deterioration / stable)
  - Risk stratification (all 5 risk levels)
  - Full agent pipeline (all 5 demo cases)
  - Alert generation (content / structure)
  - Edge cases (missing values, single reading, extreme labs)
"""

import unittest
import sys
import os

# Allow running from repo root
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from vital_guardian import (
    VitalReading, LabValues, PatientContext,
    ClinicalScorer, TrendAnalyzer, RiskStratifier,
    VitalGuardianAgent, RiskLevel, DEMO_PATIENTS,
)


def _v(temp=37.0, hr=75, rr=15, sbp=120, dbp=80, spo2=98, gcs=15, o2=False, ts="T-0"):
    """Helper to build a VitalReading with defaults."""
    return VitalReading(
        timestamp=ts, temp_c=temp, heart_rate=hr, resp_rate=rr,
        systolic_bp=sbp, diastolic_bp=dbp, spo2=spo2, gcs=gcs,
        on_supplemental_o2=o2
    )


def _labs(wbc=8.0, lactate=1.0, creat=0.9, plt=200, bands=0.0):
    return LabValues(wbc=wbc, lactate=lactate, creatinine=creat,
                     platelet_count=plt, bands_pct=bands)


# ─────────────────────────────────────────────────────────────────────────────
class TestQSOFA(unittest.TestCase):

    def setUp(self):
        self.scorer = ClinicalScorer()

    def test_zero_score_healthy(self):
        """Normal vitals → qSOFA = 0."""
        v = _v(rr=14, sbp=120, gcs=15)
        result = self.scorer.calculate_qsofa(v)
        self.assertEqual(result.score, 0)
        self.assertFalse(result.threshold_met)

    def test_rr_threshold(self):
        """RR ≥ 22 scores 1."""
        v = _v(rr=22, sbp=120, gcs=15)
        result = self.scorer.calculate_qsofa(v)
        self.assertEqual(result.components["rr_ge_22"], 1)

    def test_sbp_threshold(self):
        """SBP ≤ 100 scores 1."""
        v = _v(rr=14, sbp=98, gcs=15)
        result = self.scorer.calculate_qsofa(v)
        self.assertEqual(result.components["sbp_le_100"], 1)

    def test_altered_mentation(self):
        """GCS < 15 scores 1."""
        v = _v(rr=14, sbp=120, gcs=13)
        result = self.scorer.calculate_qsofa(v)
        self.assertEqual(result.components["altered_mentation"], 1)

    def test_max_score_all_three(self):
        """All three abnormal → qSOFA = 3, threshold met."""
        v = _v(rr=28, sbp=88, gcs=12)
        result = self.scorer.calculate_qsofa(v)
        self.assertEqual(result.score, 3)
        self.assertTrue(result.threshold_met)

    def test_threshold_met_at_two(self):
        """Score = 2 is sufficient to meet threshold."""
        v = _v(rr=24, sbp=95, gcs=15)
        result = self.scorer.calculate_qsofa(v)
        self.assertEqual(result.score, 2)
        self.assertTrue(result.threshold_met)

    def test_missing_values_no_crash(self):
        """None values should not raise exceptions."""
        v = VitalReading(timestamp="T-0")
        result = self.scorer.calculate_qsofa(v)
        self.assertEqual(result.score, 0)


# ─────────────────────────────────────────────────────────────────────────────
class TestSIRS(unittest.TestCase):

    def setUp(self):
        self.scorer = ClinicalScorer()

    def test_no_criteria_normal(self):
        v = _v(temp=37.0, hr=72, rr=16)
        labs = _labs(wbc=8.0, bands=5.0)
        result = self.scorer.calculate_sirs(v, labs)
        self.assertEqual(result.score, 0)
        self.assertFalse(result.threshold_met)

    def test_fever_criterion(self):
        v = _v(temp=38.5, hr=72, rr=16)
        result = self.scorer.calculate_sirs(v, None)
        self.assertEqual(result.components["temp_abnormal"], 1)

    def test_hypothermia_criterion(self):
        v = _v(temp=35.5, hr=72, rr=16)
        result = self.scorer.calculate_sirs(v, None)
        self.assertEqual(result.components["temp_abnormal"], 1)

    def test_hr_criterion(self):
        v = _v(temp=37.0, hr=98, rr=16)
        result = self.scorer.calculate_sirs(v, None)
        self.assertEqual(result.components["hr_gt_90"], 1)

    def test_wbc_elevated(self):
        v = _v()
        labs = _labs(wbc=14.0)
        result = self.scorer.calculate_sirs(v, labs)
        self.assertEqual(result.components["wbc_abnormal"], 1)

    def test_sirs_threshold_met(self):
        """Fever + tachycardia = 2 criteria → threshold met."""
        v = _v(temp=38.9, hr=104, rr=16)
        result = self.scorer.calculate_sirs(v, None)
        self.assertTrue(result.threshold_met)

    def test_bands_criterion(self):
        """Bands >10% triggers WBC abnormal flag."""
        v = _v()
        labs = LabValues(wbc=10.0, bands_pct=12.0)
        result = self.scorer.calculate_sirs(v, labs)
        self.assertEqual(result.components["wbc_abnormal"], 1)


# ─────────────────────────────────────────────────────────────────────────────
class TestNEWS2(unittest.TestCase):

    def setUp(self):
        self.scorer = ClinicalScorer()

    def test_zero_score_all_normal(self):
        v = _v(temp=37.5, hr=72, rr=16, sbp=118, spo2=98, gcs=15, o2=False)
        result = self.scorer.calculate_news2(v)
        self.assertEqual(result.score, 0)

    def test_high_rr_scores(self):
        v = _v(rr=28)
        result = self.scorer.calculate_news2(v)
        self.assertEqual(result.components["resp_rate"], 3)

    def test_low_spo2_scores(self):
        v = _v(spo2=90, o2=False)
        result = self.scorer.calculate_news2(v)
        self.assertEqual(result.components["spo2"], 3)

    def test_supplemental_o2_adds_2(self):
        v = _v(o2=True)
        result = self.scorer.calculate_news2(v)
        self.assertEqual(result.components["o2_supplement"], 2)

    def test_low_bp_scores(self):
        v = _v(sbp=88)
        result = self.scorer.calculate_news2(v)
        self.assertEqual(result.components["systolic_bp"], 3)

    def test_altered_consciousness_scores_3(self):
        v = _v(gcs=12)
        result = self.scorer.calculate_news2(v)
        self.assertEqual(result.components["consciousness"], 3)

    def test_urgent_threshold_at_7(self):
        """Very abnormal vitals → score ≥7."""
        v = _v(temp=39.5, hr=138, rr=28, sbp=86, spo2=88, gcs=12, o2=True)
        result = self.scorer.calculate_news2(v)
        self.assertGreaterEqual(result.score, 7)
        self.assertTrue(result.threshold_met)


# ─────────────────────────────────────────────────────────────────────────────
class TestTrendAnalyzer(unittest.TestCase):

    def setUp(self):
        self.analyzer = TrendAnalyzer()

    def test_stable_no_flags(self):
        h = [_v(hr=78, sbp=120, rr=15, ts="T-2"), _v(hr=80, sbp=118, rr=16, ts="T-0")]
        result = self.analyzer.analyze_deterioration(h)
        self.assertEqual(result["status"], "STABLE")
        self.assertEqual(len(result["flags"]), 0)

    def test_hr_rising_flag(self):
        h = [_v(hr=72, ts="T-2"), _v(hr=96, ts="T-0")]
        result = self.analyzer.analyze_deterioration(h)
        self.assertEqual(result["status"], "DETERIORATING")
        self.assertTrue(any("HR" in f for f in result["flags"]))

    def test_sbp_falling_flag(self):
        h = [_v(sbp=130, dbp=80, ts="T-2"), _v(sbp=108, dbp=68, ts="T-0")]
        result = self.analyzer.analyze_deterioration(h)
        self.assertEqual(result["status"], "DETERIORATING")
        self.assertTrue(any("SBP" in f for f in result["flags"]))

    def test_spo2_dropping_flag(self):
        h = [_v(spo2=98.0, ts="T-2"), _v(spo2=93.0, ts="T-0")]
        result = self.analyzer.analyze_deterioration(h)
        self.assertEqual(result["status"], "DETERIORATING")

    def test_single_reading_insufficient(self):
        result = self.analyzer.analyze_deterioration([_v()])
        self.assertEqual(result["status"], "INSUFFICIENT_DATA")

    def test_empty_history(self):
        result = self.analyzer.analyze_deterioration([])
        self.assertEqual(result["status"], "INSUFFICIENT_DATA")


# ─────────────────────────────────────────────────────────────────────────────
class TestRiskStratifier(unittest.TestCase):

    def setUp(self):
        self.scorer = ClinicalScorer()
        self.strat  = RiskStratifier()

    def _run(self, vitals, labs=None, extra_ctx=None):
        ctx = PatientContext(
            patient_id="X", age=50, sex="M",
            chief_complaint="test",
            vitals_history=[vitals],
            labs=labs,
            **(extra_ctx or {}),
        )
        qsofa = self.scorer.calculate_qsofa(vitals)
        sirs  = self.scorer.calculate_sirs(vitals, labs)
        news2 = self.scorer.calculate_news2(vitals)
        sofa  = self.scorer.estimate_sofa_components(vitals, labs)
        from vital_guardian import TrendAnalyzer
        trend = TrendAnalyzer().analyze_deterioration(ctx.vitals_history)
        return self.strat.stratify(qsofa, sirs, news2, sofa, trend, ctx, labs)

    def test_green_risk_healthy(self):
        level, _, _ = self._run(_v())
        self.assertEqual(level, RiskLevel.GREEN)

    def test_critical_risk_septic_shock(self):
        v = _v(temp=40.2, hr=142, rr=36, sbp=72, dbp=45, spo2=84, gcs=10, o2=True)
        labs = LabValues(wbc=22.0, lactate=5.8, creatinine=3.5, platelet_count=55)
        level, _, _ = self._run(v, labs, {"known_infection": True, "immunocompromised": True})
        self.assertIn(level, (RiskLevel.RED, RiskLevel.CRITICAL))

    def test_lactate_amplifies_risk(self):
        """Elevated lactate should push risk higher."""
        v = _v(rr=24, sbp=95, gcs=15)
        labs_high_lac = LabValues(lactate=4.5)
        level_with, _, _ = self._run(v, labs_high_lac)
        level_without, _, _ = self._run(v)
        self.assertGreaterEqual(
            list(RiskLevel).index(level_with),
            list(RiskLevel).index(level_without),
        )


# ─────────────────────────────────────────────────────────────────────────────
class TestFullAgentPipeline(unittest.TestCase):

    def setUp(self):
        self.agent = VitalGuardianAgent(verbose=False)

    def test_case1_green(self):
        """Healthy post-op patient → GREEN."""
        alert, risk = self.agent.run(DEMO_PATIENTS[1])
        self.assertEqual(risk, RiskLevel.GREEN)
        self.assertIn("GREEN", alert)

    def test_case2_elevated_risk(self):
        """Early sepsis in elderly patient — multiple signals → at least ORANGE."""
        alert, risk = self.agent.run(DEMO_PATIENTS[2])
        self.assertIn(risk, (RiskLevel.ORANGE, RiskLevel.RED, RiskLevel.CRITICAL))

    def test_case4_critical(self):
        """Septic shock → RED or CRITICAL."""
        alert, risk = self.agent.run(DEMO_PATIENTS[4])
        self.assertIn(risk, (RiskLevel.RED, RiskLevel.CRITICAL))

    def test_alert_contains_sepsis_bundle_for_orange_plus(self):
        """Alert for high-risk patients must include Sepsis-3 bundle."""
        alert, risk = self.agent.run(DEMO_PATIENTS[3])
        if risk in (RiskLevel.ORANGE, RiskLevel.RED, RiskLevel.CRITICAL):
            self.assertIn("HOUR-1 BUNDLE", alert.upper())

    def test_alert_contains_scores(self):
        """Alert must include qSOFA, SIRS, NEWS2 scores."""
        alert, _ = self.agent.run(DEMO_PATIENTS[2])
        for label in ("qSOFA", "SIRS", "NEWS2"):
            self.assertIn(label, alert)

    def test_alert_contains_disclaimer(self):
        """Safety disclaimer must always be present."""
        alert, _ = self.agent.run(DEMO_PATIENTS[1])
        self.assertIn("DISCLAIMER", alert)

    def test_alert_contains_agent_log(self):
        """Agent execution log must list all steps."""
        alert, _ = self.agent.run(DEMO_PATIENTS[1])
        for step in ("INTAKE", "qSOFA", "SIRS", "NEWS2", "TREND", "STRATIFY", "ALERT"):
            self.assertIn(step, alert)

    def test_no_vitals_raises_error(self):
        """Missing vital signs should raise ValueError."""
        empty_patient = PatientContext(
            patient_id="X", age=30, sex="M",
            chief_complaint="test",
            vitals_history=[]
        )
        with self.assertRaises(ValueError):
            self.agent.run(empty_patient)

    def test_case5_sirs_non_septic(self):
        """Burns patient — SIRS criteria met but should be YELLOW, not CRITICAL."""
        alert, risk = self.agent.run(DEMO_PATIENTS[5])
        self.assertNotEqual(risk, RiskLevel.CRITICAL)
        self.assertIn(risk, (RiskLevel.YELLOW, RiskLevel.ORANGE))

    def test_all_five_cases_complete(self):
        """All 5 demo cases must run to completion without exceptions."""
        for n, patient in DEMO_PATIENTS.items():
            with self.subTest(case=n):
                alert, risk = self.agent.run(patient)
                self.assertIsInstance(alert, str)
                self.assertIsInstance(risk, RiskLevel)
                self.assertGreater(len(alert), 100)


# ─────────────────────────────────────────────────────────────────────────────
class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.scorer = ClinicalScorer()
        self.agent  = VitalGuardianAgent(verbose=False)

    def test_extreme_bradycardia_news2(self):
        """HR ≤ 40 should score 3 on NEWS2."""
        v = _v(hr=35)
        result = self.scorer.calculate_news2(v)
        self.assertEqual(result.components["pulse"], 3)

    def test_very_low_temp_news2(self):
        """Temp ≤ 35°C should score 3 on NEWS2."""
        v = _v(temp=34.5)
        result = self.scorer.calculate_news2(v)
        self.assertEqual(result.components["temperature"], 3)

    def test_qsofa_sbp_exactly_100(self):
        """SBP exactly 100 is at threshold — should score 1."""
        v = _v(sbp=100)
        result = self.scorer.calculate_qsofa(v)
        self.assertEqual(result.components["sbp_le_100"], 1)

    def test_sofa_extreme_creatinine(self):
        """Very high creatinine → SOFA renal = 4."""
        v = _v()
        labs = LabValues(creatinine=5.5)
        sofa = self.scorer.estimate_sofa_components(v, labs)
        self.assertEqual(sofa.get("renal", -1), 4)

    def test_no_labs_still_works(self):
        """Agent should run correctly with no lab values."""
        patient = PatientContext(
            patient_id="NO-LABS", age=55, sex="F",
            chief_complaint="fever and confusion",
            vitals_history=[_v(temp=38.8, hr=108, rr=24, sbp=98, gcs=14)],
            labs=None,
        )
        alert, risk = self.agent.run(patient)
        self.assertIsInstance(alert, str)
        self.assertIsInstance(risk, RiskLevel)


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    loader  = unittest.TestLoader()
    suite   = unittest.TestSuite()

    for cls in [
        TestQSOFA, TestSIRS, TestNEWS2,
        TestTrendAnalyzer, TestRiskStratifier,
        TestFullAgentPipeline, TestEdgeCases,
    ]:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
