#!/usr/bin/env python3
"""
vital_guardian.py — Vital Guardian: Clinical Early-Warning & Response Agent

7-step autonomous clinical agent that:
  1. INTAKE    — Parses and validates patient vitals / labs
  2. qSOFA     — Quick Sequential Organ Failure Assessment (Singer et al., JAMA 2016)
  3. SIRS      — Systemic Inflammatory Response Syndrome (Bone et al., Chest 1992)
  4. NEWS2     — National Early Warning Score 2 (Royal College of Physicians 2017)
  5. TREND     — Deterioration velocity analysis over vital-sign time series
  6. STRATIFY  — Unified risk level from all scoring signals
  7. ALERT     — Structured clinical alert + care bundle recommendations

Evidence base:
  - Sepsis-3 consensus definitions (Singer et al., JAMA 2016; 315(8):801-810)
  - NHS NEWS2 (Royal College of Physicians, 2017)
  - SIRS criteria (Bone et al., Chest 1992; 101(6):1644-1655)
  - Sepsis Hour-1 Bundle (Levy et al., Crit Care Med 2018)
  - AHRQ Sepsis Burden: 1.7M cases/year, 350K deaths, $62B cost (2024)

Usage:
  python vital_guardian.py --demo               # Run all 5 demo patients
  python vital_guardian.py --demo-case 3        # Run specific case (1-5)
  python vital_guardian.py --patient data.json  # Run from JSON file
  python vital_guardian.py --verbose --demo     # Verbose step-by-step output
  python vital_guardian.py --output result.txt  # Save alert to file
"""

from __future__ import annotations

import json
import sys
import argparse
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum


# ═══════════════════════════════════════════════════════════════════════════════
#  DATA MODELS
# ═══════════════════════════════════════════════════════════════════════════════

class RiskLevel(Enum):
    GREEN    = "GREEN"
    YELLOW   = "YELLOW"
    ORANGE   = "ORANGE"
    RED      = "RED"
    CRITICAL = "CRITICAL"


@dataclass
class VitalReading:
    """A single set of vital-sign measurements at one point in time."""
    timestamp: str
    temp_c: Optional[float] = None          # °Celsius
    heart_rate: Optional[int] = None        # bpm
    resp_rate: Optional[int] = None         # breaths/min
    systolic_bp: Optional[int] = None       # mmHg
    diastolic_bp: Optional[int] = None      # mmHg
    spo2: Optional[float] = None            # %
    gcs: Optional[int] = None              # Glasgow Coma Scale (3–15)
    on_supplemental_o2: bool = False


@dataclass
class LabValues:
    """Relevant laboratory values."""
    wbc: Optional[float] = None             # K/uL  (normal 4–11)
    bands_pct: Optional[float] = None       # %  (normal <10)
    lactate: Optional[float] = None         # mmol/L  (normal <2)
    creatinine: Optional[float] = None      # mg/dL   (normal <1.2)
    bilirubin: Optional[float] = None       # mg/dL   (normal <1.2)
    platelet_count: Optional[int] = None    # K/uL   (normal 150–400)
    pf_ratio: Optional[float] = None        # PaO2/FiO2 (normal >400)


@dataclass
class PatientContext:
    """Full patient context for the agent."""
    patient_id: str
    age: int
    sex: str                                     # "M" / "F" / "X"
    chief_complaint: str
    suspected_source: Optional[str] = None       # e.g. "urinary", "pulmonary"
    immunocompromised: bool = False
    recent_surgery: bool = False
    known_infection: bool = False
    baseline_creatinine: Optional[float] = None
    vitals_history: List[VitalReading] = field(default_factory=list)
    labs: Optional[LabValues] = None


@dataclass
class ScoreResult:
    name: str
    score: int
    max_score: int
    components: Dict[str, int]
    interpretation: str
    threshold_met: bool


@dataclass
class AgentStep:
    step_num: int
    name: str
    result: str
    details: Dict
    flags: List[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════════
#  CLINICAL SCORING ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

class ClinicalScorer:
    """Implements qSOFA, SIRS, NEWS2 and simplified SOFA."""

    # ── qSOFA ──────────────────────────────────────────────────────────────────
    def calculate_qsofa(self, vitals: VitalReading) -> ScoreResult:
        """
        qSOFA — quick Sequential Organ Failure Assessment.
        Source: Singer et al., JAMA 2016; 315(8):801-810.
        Score ≥2 identifies patients at high risk of poor outcomes with infection.
        Components:
          • Respiratory rate ≥22 /min
          • Altered mentation (GCS <15)
          • Systolic BP ≤100 mmHg
        """
        c: Dict[str, int] = {}

        c["rr_ge_22"]          = 1 if (vitals.resp_rate is not None and vitals.resp_rate >= 22) else 0
        c["altered_mentation"] = 1 if (vitals.gcs is not None and vitals.gcs < 15) else 0
        c["sbp_le_100"]        = 1 if (vitals.systolic_bp is not None and vitals.systolic_bp <= 100) else 0

        score = sum(c.values())
        threshold_met = score >= 2

        if threshold_met:
            interp = f"qSOFA {score}/3 — ⚠️ HIGH RISK: Sepsis workup indicated"
        elif score == 1:
            interp = f"qSOFA {score}/3 — Monitor closely; re-assess in 1h"
        else:
            interp = f"qSOFA {score}/3 — Low risk (no threshold met)"

        return ScoreResult("qSOFA", score, 3, c, interp, threshold_met)

    # ── SIRS ───────────────────────────────────────────────────────────────────
    def calculate_sirs(self, vitals: VitalReading, labs: Optional[LabValues]) -> ScoreResult:
        """
        SIRS — Systemic Inflammatory Response Syndrome criteria.
        Source: Bone et al., Chest 1992; 101(6):1644-1655.
        ≥2 criteria = SIRS; combined with suspected infection → sepsis.
        Components:
          • Temp >38.0°C or <36.0°C
          • HR >90 bpm
          • RR >20 /min
          • WBC >12 or <4 K/uL, or bands >10%
        """
        c: Dict[str, int] = {}

        c["temp_abnormal"] = (
            1 if (vitals.temp_c is not None and (vitals.temp_c > 38.0 or vitals.temp_c < 36.0)) else 0
        )
        c["hr_gt_90"]     = 1 if (vitals.heart_rate is not None and vitals.heart_rate > 90) else 0
        c["rr_gt_20"]     = 1 if (vitals.resp_rate is not None and vitals.resp_rate > 20) else 0

        wbc_ab   = labs is not None and labs.wbc is not None and (labs.wbc > 12.0 or labs.wbc < 4.0)
        bands_ab = labs is not None and labs.bands_pct is not None and labs.bands_pct > 10.0
        c["wbc_abnormal"] = 1 if (wbc_ab or bands_ab) else 0

        score = sum(c.values())
        threshold_met = score >= 2
        interp = (
            f"SIRS {score}/4 — ⚠️ SIRS criteria met (inflammatory state)"
            if threshold_met
            else f"SIRS {score}/4 — Not met"
        )
        return ScoreResult("SIRS", score, 4, c, interp, threshold_met)

    # ── NEWS2 ──────────────────────────────────────────────────────────────────
    def calculate_news2(self, vitals: VitalReading) -> ScoreResult:
        """
        NEWS2 — National Early Warning Score 2.
        Source: Royal College of Physicians, London, 2017.
        Score ≥7: Urgent/emergency response needed.
        Parameters scored: RR, SpO2, O2 supplement, SBP, pulse, consciousness, temp.
        """
        c: Dict[str, int] = {}

        # Respiration rate
        rr = vitals.resp_rate
        if rr is not None:
            if rr <= 8:          c["resp_rate"] = 3
            elif rr <= 11:       c["resp_rate"] = 1
            elif rr <= 20:       c["resp_rate"] = 0
            elif rr <= 24:       c["resp_rate"] = 2
            else:                c["resp_rate"] = 3
        else:
            c["resp_rate"] = 0

        # SpO2 (Scale 1 — no supplemental O2)
        spo2 = vitals.spo2
        if spo2 is not None:
            if not vitals.on_supplemental_o2:
                if spo2 <= 91:   c["spo2"] = 3
                elif spo2 <= 93: c["spo2"] = 2
                elif spo2 <= 95: c["spo2"] = 1
                else:            c["spo2"] = 0
            else:
                # Scale 2 simplified (on supplemental O2, hypercapnic risk patients)
                if spo2 <= 83:   c["spo2"] = 3
                elif spo2 <= 85: c["spo2"] = 2
                elif spo2 <= 87: c["spo2"] = 1
                else:            c["spo2"] = 0
        else:
            c["spo2"] = 0

        c["o2_supplement"] = 2 if vitals.on_supplemental_o2 else 0

        # Systolic BP
        sbp = vitals.systolic_bp
        if sbp is not None:
            if sbp <= 90:        c["systolic_bp"] = 3
            elif sbp <= 100:     c["systolic_bp"] = 2
            elif sbp <= 110:     c["systolic_bp"] = 1
            elif sbp <= 219:     c["systolic_bp"] = 0
            else:                c["systolic_bp"] = 3   # hypertensive crisis
        else:
            c["systolic_bp"] = 0

        # Pulse rate
        hr = vitals.heart_rate
        if hr is not None:
            if hr <= 40:         c["pulse"] = 3
            elif hr <= 50:       c["pulse"] = 1
            elif hr <= 90:       c["pulse"] = 0
            elif hr <= 110:      c["pulse"] = 1
            elif hr <= 130:      c["pulse"] = 2
            else:                c["pulse"] = 3
        else:
            c["pulse"] = 0

        # Consciousness
        gcs = vitals.gcs
        c["consciousness"] = 0 if (gcs is None or gcs >= 15) else 3

        # Temperature
        temp = vitals.temp_c
        if temp is not None:
            if temp <= 35.0:     c["temperature"] = 3
            elif temp <= 36.0:   c["temperature"] = 1
            elif temp <= 38.0:   c["temperature"] = 0
            elif temp <= 39.0:   c["temperature"] = 1
            else:                c["temperature"] = 2
        else:
            c["temperature"] = 0

        score = sum(c.values())

        if score >= 7:
            interp = f"NEWS2 {score}/20 — 🚨 URGENT: Emergency clinical review"
        elif score >= 5:
            interp = f"NEWS2 {score}/20 — ⚠️ HIGH: Urgent clinical review within 1h"
        elif score >= 1:
            interp = f"NEWS2 {score}/20 — ⚡ LOW-MEDIUM: Monitor q4-6h"
        else:
            interp = f"NEWS2 {score}/20 — ✅ NORMAL: Routine monitoring"

        return ScoreResult("NEWS2", score, 20, c, interp, score >= 5)

    # ── Simplified SOFA ────────────────────────────────────────────────────────
    def estimate_sofa_components(
        self, vitals: VitalReading, labs: Optional[LabValues]
    ) -> Dict[str, int]:
        """
        Simplified SOFA (Sequential Organ Failure Assessment) components.
        Source: Vincent et al., Intensive Care Med 1996; 22(7):707-710.
        Full SOFA requires ICU-level data; this estimates from common ward data.
        Sepsis-3 definition: suspected infection + SOFA increase ≥2 → sepsis.
        """
        sofa: Dict[str, int] = {}

        # Cardiovascular — MAP approximation (SBP + 2×DBP) / 3
        if vitals.systolic_bp and vitals.diastolic_bp:
            map_val = (vitals.systolic_bp + 2 * vitals.diastolic_bp) / 3
            sofa["cardiovascular"] = 0 if map_val >= 70 else (1 if map_val >= 65 else 3)

        # Renal — Creatinine
        if labs and labs.creatinine is not None:
            cr = labs.creatinine
            if cr < 1.2:    sofa["renal"] = 0
            elif cr < 2.0:  sofa["renal"] = 1
            elif cr < 3.5:  sofa["renal"] = 2
            elif cr < 5.0:  sofa["renal"] = 3
            else:           sofa["renal"] = 4

        # Hepatic — Bilirubin
        if labs and labs.bilirubin is not None:
            bili = labs.bilirubin
            if bili < 1.2:   sofa["liver"] = 0
            elif bili < 2.0: sofa["liver"] = 1
            elif bili < 6.0: sofa["liver"] = 2
            else:            sofa["liver"] = 3

        # Coagulation — Platelet count
        if labs and labs.platelet_count is not None:
            plt = labs.platelet_count
            if plt >= 150:  sofa["coagulation"] = 0
            elif plt >= 100: sofa["coagulation"] = 1
            elif plt >= 50:  sofa["coagulation"] = 2
            else:            sofa["coagulation"] = 4

        # CNS — GCS
        if vitals.gcs is not None:
            gcs = vitals.gcs
            if gcs >= 15:   sofa["cns"] = 0
            elif gcs >= 13: sofa["cns"] = 1
            elif gcs >= 10: sofa["cns"] = 2
            elif gcs >= 6:  sofa["cns"] = 3
            else:           sofa["cns"] = 4

        return sofa


# ═══════════════════════════════════════════════════════════════════════════════
#  TREND ANALYZER
# ═══════════════════════════════════════════════════════════════════════════════

class TrendAnalyzer:
    """Detects deterioration velocity across a vital-sign time series."""

    # Thresholds for flagging deterioration
    HR_DELTA_THRESHOLD    = 20   # bpm rise across series
    SBP_DELTA_THRESHOLD   = -15  # mmHg drop
    RR_DELTA_THRESHOLD    = 5    # /min rise
    TEMP_DELTA_THRESHOLD  = 1.0  # °C rise
    SPO2_DELTA_THRESHOLD  = -3.0 # % drop
    GCS_DELTA_THRESHOLD   = -2   # points drop

    def analyze_deterioration(self, vitals_history: List[VitalReading]) -> Dict:
        if len(vitals_history) < 2:
            return {"status": "INSUFFICIENT_DATA", "flags": [], "readings_analyzed": len(vitals_history)}

        first = vitals_history[0]
        last  = vitals_history[-1]
        flags: List[str] = []

        if first.heart_rate and last.heart_rate:
            d = last.heart_rate - first.heart_rate
            if d >= self.HR_DELTA_THRESHOLD:
                flags.append(f"HR rising rapidly: +{d} bpm across {len(vitals_history)} readings")

        if first.systolic_bp and last.systolic_bp:
            d = last.systolic_bp - first.systolic_bp
            if d <= self.SBP_DELTA_THRESHOLD:
                flags.append(f"SBP falling: {d:+d} mmHg (hypoperfusion risk)")

        if first.resp_rate and last.resp_rate:
            d = last.resp_rate - first.resp_rate
            if d >= self.RR_DELTA_THRESHOLD:
                flags.append(f"RR worsening: +{d}/min (respiratory drive deteriorating)")

        if first.temp_c and last.temp_c:
            d = last.temp_c - first.temp_c
            if d >= self.TEMP_DELTA_THRESHOLD:
                flags.append(f"Temperature rising: +{d:.1f}°C (developing fever / inflammatory surge)")

        if first.spo2 and last.spo2:
            d = last.spo2 - first.spo2
            if d <= self.SPO2_DELTA_THRESHOLD:
                flags.append(f"SpO2 dropping: {d:+.1f}% (oxygenation deteriorating)")

        if first.gcs and last.gcs:
            d = last.gcs - first.gcs
            if d <= self.GCS_DELTA_THRESHOLD:
                flags.append(f"GCS falling: {d:+d} (neurological deterioration)")

        return {
            "status": "DETERIORATING" if flags else "STABLE",
            "flags": flags,
            "readings_analyzed": len(vitals_history),
        }


# ═══════════════════════════════════════════════════════════════════════════════
#  RISK STRATIFIER
# ═══════════════════════════════════════════════════════════════════════════════

class RiskStratifier:
    """Combines all scoring signals into a single unified risk level."""

    def stratify(
        self,
        qsofa: ScoreResult,
        sirs: ScoreResult,
        news2: ScoreResult,
        sofa_components: Dict[str, int],
        trend: Dict,
        context: PatientContext,
        labs: Optional[LabValues],
    ) -> Tuple[RiskLevel, str, List[str]]:

        points = 0
        factors: List[str] = []

        # qSOFA
        if qsofa.score >= 2:
            points += 3
            factors.append(f"qSOFA ≥2 ({qsofa.score}/3) — high-risk sepsis threshold met")
        elif qsofa.score == 1:
            points += 1

        # NEWS2
        if news2.score >= 7:
            points += 3
            factors.append(f"NEWS2 ≥7 ({news2.score}) — urgent response threshold met")
        elif news2.score >= 5:
            points += 2
            factors.append(f"NEWS2 ≥5 ({news2.score}) — high alert")
        elif news2.score >= 3:
            points += 1

        # SIRS
        if sirs.score >= 2:
            points += 1
            factors.append(f"SIRS criteria met ({sirs.score}/4) — systemic inflammatory response")

        # Lab amplifiers
        if labs:
            if labs.lactate is not None and labs.lactate >= 4.0:
                points += 4
                factors.append(f"Lactate ≥4.0 mmol/L ({labs.lactate}) — septic shock marker")
            elif labs.lactate is not None and labs.lactate >= 2.0:
                points += 2
                factors.append(f"Lactate ≥2.0 mmol/L ({labs.lactate}) — tissue hypoperfusion")
            if labs.wbc is not None and (labs.wbc > 15 or labs.wbc < 3):
                points += 1
                factors.append(f"Extreme WBC ({labs.wbc} K/uL) — severe immune response")

        # SOFA organ dysfunction
        sofa_total = sum(sofa_components.values())
        if sofa_total >= 6:
            points += 3
            factors.append(f"Multiple organ dysfunction (estimated SOFA ≥{sofa_total})")
        elif sofa_total >= 2:
            points += 1
            factors.append(f"Organ dysfunction signals (estimated SOFA ~{sofa_total})")

        # Trend
        if trend["status"] == "DETERIORATING":
            points += 2
            factors.append(f"Active deterioration trend ({len(trend['flags'])} vital-sign alarm(s))")

        # Context amplifiers
        if context.immunocompromised:
            points += 1
            factors.append("Immunocompromised — attenuated inflammatory response may mask severity")
        if context.known_infection and qsofa.score >= 1:
            points += 1
            factors.append("Known infection source + early organ dysfunction signals")

        # Map to risk level
        if points >= 10:
            level = RiskLevel.CRITICAL
        elif points >= 7:
            level = RiskLevel.RED
        elif points >= 4:
            level = RiskLevel.ORANGE
        elif points >= 2:
            level = RiskLevel.YELLOW
        else:
            level = RiskLevel.GREEN

        reason = f"Composite risk score: {points} | {len(factors)} contributing factor(s)"
        return level, reason, factors


# ═══════════════════════════════════════════════════════════════════════════════
#  ALERT GENERATOR
# ═══════════════════════════════════════════════════════════════════════════════

# Sepsis Hour-1 Bundle  (Levy et al., Crit Care Med 2018; 46(6):997-1006)
HOUR_1_BUNDLE = [
    "1. Measure serum lactate (repeat if initial >2 mmol/L)",
    "2. Obtain blood cultures ×2 sets BEFORE antibiotics",
    "3. Administer broad-spectrum IV antibiotics",
    "4. Begin 30 mL/kg IV crystalloid if MAP <65 OR lactate ≥4",
    "5. Apply vasopressors (norepinephrine first-line) if MAP <65 mmHg refractory to fluids",
]
HOUR_3_BUNDLE = [
    "6. Reassess volume status and tissue perfusion",
    "7. Remeasure lactate if initial was elevated",
    "8. Document clinical response — escalate if no improvement",
]
ONGOING_BUNDLE = [
    "• Culture results review — target de-escalation at 48–72h",
    "• Source control assessment (drainage, debridement as needed)",
    "• Organ function trend monitoring (Cr, bili, platelets)",
    "• Reassess antibiotic spectrum based on microbiology",
]

RISK_ICON = {
    RiskLevel.GREEN:    "🟢",
    RiskLevel.YELLOW:   "🟡",
    RiskLevel.ORANGE:   "🟠",
    RiskLevel.RED:      "🔴",
    RiskLevel.CRITICAL: "🚨",
}

RISK_ACTION = {
    RiskLevel.GREEN:    "Routine monitoring. Reassess in 4–6 hours.",
    RiskLevel.YELLOW:   "Increase monitoring to q1–2h. Notify covering physician.",
    RiskLevel.ORANGE:   "Urgent physician bedside evaluation within 30 min. Initiate sepsis workup.",
    RiskLevel.RED:      "IMMEDIATE physician response required. Activate sepsis alert protocol.",
    RiskLevel.CRITICAL: "SEPTIC SHOCK PROTOCOL ACTIVATED. Emergency response team NOW.",
}


class AlertGenerator:

    def generate(
        self,
        patient: PatientContext,
        risk_level: RiskLevel,
        risk_reason: str,
        factors: List[str],
        qsofa: ScoreResult,
        sirs: ScoreResult,
        news2: ScoreResult,
        sofa_components: Dict[str, int],
        trend: Dict,
        labs: Optional[LabValues],
        agent_steps: List[AgentStep],
    ) -> str:

        icon   = RISK_ICON[risk_level]
        action = RISK_ACTION[risk_level]
        ts     = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        W      = 72
        div    = "─" * W

        def h(text: str) -> str:
            return f"\n{div}\n  {text}\n{div}"

        lines: List[str] = []
        lines.append("=" * W)
        lines.append(f"  {icon}  VITAL GUARDIAN ALERT   |   RISK LEVEL: {risk_level.value}")
        lines.append(f"  Generated : {ts}")
        lines.append("=" * W)

        lines.append(f"\n  PATIENT   : {patient.patient_id}")
        lines.append(f"  Age / Sex : {patient.age}y / {patient.sex.upper()}")
        lines.append(f"  Complaint : {patient.chief_complaint}")
        if patient.suspected_source:
            lines.append(f"  Source    : {patient.suspected_source.upper()} infection suspected")

        lines.append(h("CLINICAL SCORES"))
        lines.append(f"  {qsofa.interpretation}")
        lines.append(f"    Components: RR≥22={qsofa.components.get('rr_ge_22',0)}  "
                     f"AltMen={qsofa.components.get('altered_mentation',0)}  "
                     f"SBP≤100={qsofa.components.get('sbp_le_100',0)}")

        lines.append(f"\n  {sirs.interpretation}")
        lines.append(f"    Components: Temp={sirs.components.get('temp_abnormal',0)}  "
                     f"HR={sirs.components.get('hr_gt_90',0)}  "
                     f"RR={sirs.components.get('rr_gt_20',0)}  "
                     f"WBC={sirs.components.get('wbc_abnormal',0)}")

        lines.append(f"\n  {news2.interpretation}")
        lines.append(f"    Sub-scores: RR={news2.components.get('resp_rate',0)}  "
                     f"SpO2={news2.components.get('spo2',0)}  "
                     f"O2supp={news2.components.get('o2_supplement',0)}  "
                     f"SBP={news2.components.get('systolic_bp',0)}  "
                     f"Pulse={news2.components.get('pulse',0)}  "
                     f"Consc={news2.components.get('consciousness',0)}  "
                     f"Temp={news2.components.get('temperature',0)}")

        sofa_total = sum(sofa_components.values())
        if sofa_components:
            lines.append(f"\n  Estimated SOFA: ~{sofa_total}  "
                         f"(organ systems assessed: {', '.join(sofa_components.keys())})")

        lines.append(h("TREND ANALYSIS"))
        lines.append(f"  Status  : {trend['status']}  "
                     f"({trend.get('readings_analyzed', 0)} readings analyzed)")
        for flag in trend.get("flags", []):
            lines.append(f"  ❗ {flag}")
        if not trend.get("flags"):
            lines.append("  ✅ No deterioration trends detected in time series.")

        if labs:
            lines.append(h("KEY LAB VALUES"))
            if labs.lactate is not None:
                flag = "🚨" if labs.lactate >= 4 else ("⚠️" if labs.lactate >= 2 else "✅")
                lines.append(f"  {flag} Lactate     : {labs.lactate} mmol/L  (critical ≥4.0  |  elevated ≥2.0)")
            if labs.wbc is not None:
                flag = "⚠️" if labs.wbc > 12 or labs.wbc < 4 else "✅"
                lines.append(f"  {flag} WBC         : {labs.wbc} K/uL  (normal 4–12)")
            if labs.creatinine is not None:
                baseline_str = f"baseline {patient.baseline_creatinine}" if patient.baseline_creatinine else "baseline unknown"
                flag = "⚠️" if labs.creatinine > 1.2 else "✅"
                lines.append(f"  {flag} Creatinine  : {labs.creatinine} mg/dL  ({baseline_str})")
            if labs.platelet_count is not None:
                flag = "⚠️" if labs.platelet_count < 100 else "✅"
                lines.append(f"  {flag} Platelets   : {labs.platelet_count} K/uL  (normal 150–400)")
            if labs.bilirubin is not None:
                flag = "⚠️" if labs.bilirubin > 1.2 else "✅"
                lines.append(f"  {flag} Bilirubin   : {labs.bilirubin} mg/dL  (normal <1.2)")

        lines.append(h("RISK ASSESSMENT"))
        lines.append(f"  Overall Risk: {icon}  {risk_level.value}")
        lines.append(f"  {risk_reason}")
        if factors:
            lines.append(f"\n  Contributing factors:")
            for f in factors:
                lines.append(f"    • {f}")

        lines.append(h("RECOMMENDED ACTION"))
        lines.append(f"  {action}")

        if risk_level in (RiskLevel.ORANGE, RiskLevel.RED, RiskLevel.CRITICAL):
            lines.append(h("SEPSIS-3 HOUR-1 BUNDLE  (CMS SEP-1 / SCCM Guidelines)"))
            lines.append("  ⏱️  WITHIN 1 HOUR:")
            for item in HOUR_1_BUNDLE:
                lines.append(f"       {item}")
            lines.append("\n  ⏱️  WITHIN 3 HOURS:")
            for item in HOUR_3_BUNDLE:
                lines.append(f"       {item}")
            lines.append("\n  ♻️  ONGOING REASSESSMENT:")
            for item in ONGOING_BUNDLE:
                lines.append(f"       {item}")

        lines.append(h("AGENT EXECUTION LOG"))
        for step in agent_steps:
            flag_str = f" [{', '.join(step.flags)}]" if step.flags else ""
            lines.append(f"  Step {step.step_num}: [{step.name}] → {step.result}{flag_str}")

        lines.append(h("DISCLAIMER"))
        lines.append("  FOR RESEARCH AND EDUCATION ONLY. All clinical decisions must be")
        lines.append("  made by qualified, licensed healthcare professionals. Not validated")
        lines.append("  for clinical use. Do not use for direct patient care decisions.")
        lines.append("\n" + "=" * W)

        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
#  7-STEP AGENT ORCHESTRATOR
# ═══════════════════════════════════════════════════════════════════════════════

class VitalGuardianAgent:
    """
    Autonomous 7-step clinical early-warning agent.

    Takes a PatientContext (vitals time-series + labs + clinical background)
    and returns a fully rendered clinical alert document.
    """

    def __init__(self, verbose: bool = False):
        self.verbose     = verbose
        self.scorer      = ClinicalScorer()
        self.trend_an    = TrendAnalyzer()
        self.stratifier  = RiskStratifier()
        self.alerter     = AlertGenerator()

    def _log(self, step: int, name: str, msg: str):
        if self.verbose:
            print(f"  [{step}] {name:12s} ➜  {msg}")

    def run(self, patient: PatientContext) -> Tuple[str, RiskLevel]:
        """Execute all 7 steps. Returns (alert_text, risk_level)."""
        steps: List[AgentStep] = []

        # ── 1. INTAKE ──────────────────────────────────────────────────────────
        vitals = patient.vitals_history[-1] if patient.vitals_history else None
        if not vitals:
            raise ValueError("PatientContext must contain at least one VitalReading.")
        self._log(1, "INTAKE", f"{len(patient.vitals_history)} vitals reading(s), labs={'yes' if patient.labs else 'no'}")
        steps.append(AgentStep(1, "INTAKE",
            f"Validated {len(patient.vitals_history)} reading(s)",
            {"has_labs": patient.labs is not None}))

        # ── 2. qSOFA ───────────────────────────────────────────────────────────
        qsofa = self.scorer.calculate_qsofa(vitals)
        self._log(2, "qSOFA", f"score={qsofa.score}/3  threshold_met={qsofa.threshold_met}")
        s2 = AgentStep(2, "qSOFA", f"Score {qsofa.score}/3", qsofa.components)
        if qsofa.threshold_met:
            s2.flags.append("qSOFA ≥2 → sepsis probability HIGH")
        steps.append(s2)

        # ── 3. SIRS ────────────────────────────────────────────────────────────
        sirs = self.scorer.calculate_sirs(vitals, patient.labs)
        self._log(3, "SIRS", f"score={sirs.score}/4  threshold_met={sirs.threshold_met}")
        s3 = AgentStep(3, "SIRS", f"Score {sirs.score}/4", sirs.components)
        if sirs.threshold_met:
            s3.flags.append("SIRS criteria met")
        steps.append(s3)

        # ── 4. NEWS2 ───────────────────────────────────────────────────────────
        news2 = self.scorer.calculate_news2(vitals)
        self._log(4, "NEWS2", f"score={news2.score}/20  threshold_met={news2.threshold_met}")
        s4 = AgentStep(4, "NEWS2", f"Score {news2.score}/20", news2.components)
        if news2.score >= 7:
            s4.flags.append("NEWS2 ≥7 → urgent response required")
        steps.append(s4)

        # ── 5. TREND ───────────────────────────────────────────────────────────
        trend = self.trend_an.analyze_deterioration(patient.vitals_history)
        self._log(5, "TREND", f"status={trend['status']}  flags={len(trend.get('flags', []))}")
        steps.append(AgentStep(5, "TREND", trend["status"],
            {"readings": trend.get("readings_analyzed", 0)}))

        # ── 6. STRATIFY ────────────────────────────────────────────────────────
        sofa_c = self.scorer.estimate_sofa_components(vitals, patient.labs)
        risk_level, risk_reason, factors = self.stratifier.stratify(
            qsofa, sirs, news2, sofa_c, trend, patient, patient.labs
        )
        self._log(6, "STRATIFY", f"risk_level={risk_level.value}  factors={len(factors)}")
        steps.append(AgentStep(6, "STRATIFY", f"Risk: {risk_level.value}", {"factors": len(factors)}))

        # ── 7. ALERT ───────────────────────────────────────────────────────────
        self._log(7, "ALERT", f"Generating {risk_level.value} alert document")
        alert = self.alerter.generate(
            patient, risk_level, risk_reason, factors,
            qsofa, sirs, news2, sofa_c, trend, patient.labs, steps
        )
        steps.append(AgentStep(7, "ALERT", f"{risk_level.value} alert generated", {}))

        return alert, risk_level


# ═══════════════════════════════════════════════════════════════════════════════
#  DEMO PATIENT DATA
# ═══════════════════════════════════════════════════════════════════════════════

def _v(ts, temp, hr, rr, sbp, dbp, spo2, gcs=15, o2=False) -> VitalReading:
    return VitalReading(
        timestamp=ts, temp_c=temp, heart_rate=hr, resp_rate=rr,
        systolic_bp=sbp, diastolic_bp=dbp, spo2=spo2, gcs=gcs,
        on_supplemental_o2=o2
    )


DEMO_PATIENTS: Dict[int, PatientContext] = {

    # ── Case 1: Healthy — baseline ─────────────────────────────────────────────
    1: PatientContext(
        patient_id="PT-0001",
        age=45, sex="F",
        chief_complaint="Routine post-op check, day 1 after laparoscopic appendectomy",
        suspected_source=None,
        vitals_history=[
            _v("T-2h", 37.1, 78, 16, 122, 78, 98.5),
            _v("T-1h", 37.0, 76, 15, 124, 80, 99.0),
            _v("T-0h", 37.2, 74, 14, 126, 82, 98.8),
        ],
        labs=LabValues(wbc=9.1, lactate=1.1, creatinine=0.9, platelet_count=210),
        baseline_creatinine=0.9,
    ),

    # ── Case 2: Early sepsis — UTI progressing ────────────────────────────────
    2: PatientContext(
        patient_id="PT-0002",
        age=72, sex="F",
        chief_complaint="Dysuria, confusion, low-grade fever for 2 days",
        suspected_source="urinary",
        known_infection=True,
        vitals_history=[
            _v("T-6h", 37.8, 92,  18, 118, 72, 97.0),
            _v("T-3h", 38.4, 102, 21, 108, 66, 95.5),
            _v("T-0h", 38.9, 118, 24, 98,  60, 93.0, gcs=14),
        ],
        labs=LabValues(wbc=16.2, bands_pct=12.0, lactate=2.4, creatinine=1.6, platelet_count=145),
        baseline_creatinine=0.9,
    ),

    # ── Case 3: HIGH-RISK — post-op pneumonia, rapid deterioration ──────────
    3: PatientContext(
        patient_id="PT-0003",
        age=68, sex="M",
        chief_complaint="Fever, productive cough, hypoxia — post-op day 3 (hip replacement)",
        suspected_source="pulmonary",
        recent_surgery=True,
        vitals_history=[
            _v("T-4h", 38.2, 95,  22, 110, 68, 95.0),
            _v("T-2h", 38.9, 110, 26, 100, 62, 91.0, o2=True),
            _v("T-0h", 39.4, 126, 30, 90,  58, 88.0, gcs=13, o2=True),
        ],
        labs=LabValues(wbc=18.5, bands_pct=18.0, lactate=3.1, creatinine=1.9,
                       bilirubin=1.6, platelet_count=112),
        baseline_creatinine=1.1,
    ),

    # ── Case 4: CRITICAL — septic shock presentation ──────────────────────────
    4: PatientContext(
        patient_id="PT-0004",
        age=59, sex="M",
        chief_complaint="Acute abdomen — 12h post bowel perforation repair, now unresponsive",
        suspected_source="abdominal",
        recent_surgery=True,
        immunocompromised=True,
        known_infection=True,
        vitals_history=[
            _v("T-6h", 38.5, 108, 24, 100, 62, 93.0),
            _v("T-3h", 39.2, 128, 28,  88, 55, 89.0, gcs=12, o2=True),
            _v("T-0h", 40.1, 142, 34,  76, 48, 84.0, gcs=10, o2=True),
        ],
        labs=LabValues(wbc=21.8, bands_pct=25.0, lactate=5.6, creatinine=3.2,
                       bilirubin=3.8, platelet_count=68),
        baseline_creatinine=1.0,
    ),

    # ── Case 5: SIRS only (non-septic — burns) ────────────────────────────────
    5: PatientContext(
        patient_id="PT-0005",
        age=34, sex="M",
        chief_complaint="30% BSA thermal burns — 48h post admission, stable hemodynamics",
        suspected_source=None,
        vitals_history=[
            _v("T-2h", 38.6, 102, 22, 118, 72, 97.5),
            _v("T-1h", 38.4, 98,  21, 120, 74, 97.0),
            _v("T-0h", 38.5, 100, 22, 118, 73, 97.2),
        ],
        labs=LabValues(wbc=13.0, lactate=1.5, creatinine=1.1, platelet_count=180),
    ),
}


# ═══════════════════════════════════════════════════════════════════════════════
#  DEMO RUNNER
# ═══════════════════════════════════════════════════════════════════════════════

CASE_LABELS = {
    1: "Case 1 — Healthy baseline (expected: 🟢 GREEN)",
    2: "Case 2 — Early UTI-related sepsis, elderly (expected: 🟠 ORANGE)",
    3: "Case 3 — Post-op pneumonia, rapid deterioration (expected: 🔴 RED)",
    4: "Case 4 — Septic shock, abdominal source (expected: 🚨 CRITICAL)",
    5: "Case 5 — SIRS without sepsis (burns) (expected: 🟡 YELLOW)",
}


def run_demo(case_num: Optional[int], verbose: bool, output_file: Optional[str]):
    agent = VitalGuardianAgent(verbose=verbose)
    cases = [case_num] if case_num else list(DEMO_PATIENTS.keys())

    all_output: List[str] = []

    for n in cases:
        patient = DEMO_PATIENTS[n]
        print(f"\n{'═'*72}")
        print(f"  {CASE_LABELS[n]}")
        print(f"{'═'*72}")
        if verbose:
            print("  Agent steps:")

        try:
            alert, risk = agent.run(patient)
        except Exception as e:
            print(f"  ERROR: {e}")
            continue

        print(alert)
        all_output.append(alert)

    if output_file:
        with open(output_file, "w") as fh:
            fh.write("\n\n".join(all_output))
        print(f"\n[Saved to {output_file}]")


def run_from_file(path: str, verbose: bool, output_file: Optional[str]):
    with open(path) as fh:
        data = json.load(fh)

    # Build PatientContext from JSON
    vitals_history = [
        VitalReading(**v) for v in data.get("vitals_history", [])
    ]
    labs_data = data.get("labs")
    labs = LabValues(**labs_data) if labs_data else None

    patient = PatientContext(
        patient_id=data.get("patient_id", "UNKNOWN"),
        age=data.get("age", 0),
        sex=data.get("sex", "X"),
        chief_complaint=data.get("chief_complaint", ""),
        suspected_source=data.get("suspected_source"),
        immunocompromised=data.get("immunocompromised", False),
        recent_surgery=data.get("recent_surgery", False),
        known_infection=data.get("known_infection", False),
        baseline_creatinine=data.get("baseline_creatinine"),
        vitals_history=vitals_history,
        labs=labs,
    )

    agent = VitalGuardianAgent(verbose=verbose)
    alert, risk = agent.run(patient)
    print(alert)

    if output_file:
        with open(output_file, "w") as fh:
            fh.write(alert)
        print(f"\n[Saved to {output_file}]")


# ═══════════════════════════════════════════════════════════════════════════════
#  CLI ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        prog="vital_guardian",
        description="Clinical Early-Warning & Response Agent — 7-step autonomous pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python vital_guardian.py --demo               Run all 5 demo patients
  python vital_guardian.py --demo-case 4        Run only case 4 (critical septic shock)
  python vital_guardian.py --demo --verbose     Show step-by-step agent reasoning
  python vital_guardian.py --patient pt.json    Assess from JSON patient file
  python vital_guardian.py --demo --output r.txt  Save output to file

Evidence:
  Sepsis kills 350,000 Americans/year (AHRQ). AI detection reduces mortality by
  up to 42% (academic medical center study, CLPMag 2024). Yet no open-source
  multi-scoring agent exists. This tool combines qSOFA + SIRS + NEWS2 + SOFA
  + trend analysis into one unified autonomous agent loop.
        """,
    )
    parser.add_argument("--demo",       action="store_true",    help="Run all 5 demo patients")
    parser.add_argument("--demo-case",  type=int, metavar="N",  help="Run one demo case (1–5)")
    parser.add_argument("--patient",    type=str, metavar="FILE", help="Patient JSON file path")
    parser.add_argument("--verbose",    action="store_true",    help="Show step-by-step agent execution")
    parser.add_argument("--output",     type=str, metavar="FILE", help="Save alert output to file")

    args = parser.parse_args()

    if args.demo or args.demo_case:
        run_demo(args.demo_case, args.verbose, args.output)
    elif args.patient:
        run_from_file(args.patient, args.verbose, args.output)
    else:
        print("Vital Guardian — 7-step Autonomous Clinical Early-Warning Agent")
        print("Run with --demo or --help to get started.\n")
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
