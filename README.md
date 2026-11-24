# 🛡️ vital-guardian

[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Tests: 45 passing](https://img.shields.io/badge/tests-45%20passing-brightgreen.svg)](#tests)
[![Zero Dependencies](https://img.shields.io/badge/dependencies-stdlib%20only-orange.svg)](#install)
[![Healthcare AI](https://img.shields.io/badge/domain-healthcare%20AI-red.svg)](#why-this-matters)

**Autonomous 7-step clinical agent that detects patient deterioration early by running four validated scoring systems simultaneously, analyzing vital-sign trends, and generating structured care bundle alerts — zero paid APIs, fully offline.**

---

## The Problem

Sepsis kills **350,000 Americans and 11 million people worldwide every year** (AHRQ, WHO 2024). It is the **#1 killer inside hospitals** — responsible for 1 in 3 hospital deaths. The U.S. alone spends $62 billion annually on sepsis care.

The tragedy: **early detection dramatically improves survival.** Studies show a 7% increase in mortality risk for every hour of treatment delay. AI detection tools have reduced mortality by up to **42%** at academic medical centers (CLPMag, 2024). Yet most hospitals still rely on nurses manually calculating a single early-warning score — when every guideline recommends combining multiple scoring systems.

**The gap no one has filled:** No open-source, agentic tool exists that runs qSOFA + SIRS + NEWS2 + SOFA together, analyzes trend velocity, integrates lab data, and produces a clinician-ready alert with the Sepsis-3 Hour-1 Bundle — in one unified autonomous pipeline.

This project fills that gap.

---

## How It Works — The 7-Step Agent Loop

```
PatientContext (vitals time-series + labs + clinical background)
       │
       ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 1: INTAKE    — parse & validate patient data              │
│  Step 2: qSOFA     — quick Sepsis Organ Failure Assessment      │
│  Step 3: SIRS      — Systemic Inflammatory Response Syndrome    │
│  Step 4: NEWS2     — National Early Warning Score 2             │
│  Step 5: TREND     — deterioration velocity over time series    │
│  Step 6: STRATIFY  — unified risk level from all signals        │
│  Step 7: ALERT     — structured clinical alert + care bundle    │
└─────────────────────────────────────────────────────────────────┘
       │
       ▼
Structured Alert: 🟢 GREEN / 🟡 YELLOW / 🟠 ORANGE / 🔴 RED / 🚨 CRITICAL
+ Sepsis-3 Hour-1 Bundle (for ORANGE and above)
```


### Why This Architecture Is Clever

Most clinical tools implement **one** scoring system in isolation. The literature shows that qSOFA and NEWS2 have different sensitivity/specificity profiles — combining them catches cases each misses. The trend analysis layer adds the **temporal dimension** that point-in-time scores miss: a patient whose vitals are still in the "normal" range but deteriorating at high velocity is far more dangerous than one with mildly abnormal but stable vitals.

The agent reasons like a senior clinician:
1. What do the numbers say right now? (qSOFA, SIRS, NEWS2)
2. Where are the numbers going? (trend velocity)
3. Are organs failing? (simplified SOFA from available data)
4. What amplifies the risk? (lactate, WBC, context factors)
5. What does the clinician need to do in the next 60 minutes? (Sepsis-3 bundle)

---

## Scoring Systems

| Score | Source | Threshold | What It Detects |
|-------|--------|-----------|-----------------|
| **qSOFA** | Singer et al., JAMA 2016 | ≥2/3 | High-risk sepsis probability |
| **SIRS** | Bone et al., Chest 1992 | ≥2/4 | Systemic inflammatory response |
| **NEWS2** | Royal College of Physicians 2017 | ≥5/20 | Clinical deterioration urgency |
| **SOFA** | Vincent et al., ICM 1996 | Δ≥2 | Organ dysfunction severity |

**Trend flags:**
- HR rising ≥20 bpm across readings
- SBP falling ≥15 mmHg
- RR worsening ≥5/min
- SpO2 dropping ≥3%
- GCS falling ≥2 points
- Temperature rising ≥1°C

**Lab amplifiers:**
- Lactate ≥4.0 mmol/L → +4 risk points (septic shock marker)
- Lactate ≥2.0 mmol/L → +2 risk points (tissue hypoperfusion)
- WBC extreme (<3 or >15 K/uL) → +1 risk point

---

## Demo Cases

The agent ships with 5 built-in demo patients:

| Case | Patient | Expected Risk |
|------|---------|--------------|
| 1 | Healthy, day-1 post-op | 🟢 GREEN |
| 2 | Elderly with UTI + altered mentation, deteriorating | 🔴 RED / 🚨 CRITICAL |
| 3 | Post-op pneumonia, rapid deterioration | 🔴 RED |
| 4 | Septic shock — abdominal source, immunocompromised | 🚨 CRITICAL |
| 5 | Burns (SIRS without infection) | 🟡 YELLOW |

---


## Install

```bash
git clone https://github.com/ai-summer2025/vital-guardian.git
cd vital-guardian
pip install pytest   # only needed for tests; agent itself uses stdlib only
```

**Requirements:** Python 3.9+. No external API calls. Runs fully offline.

---

## Usage

```bash
# Run all 5 demo patients
python vital_guardian.py --demo

# Run one specific case
python vital_guardian.py --demo-case 4

# See step-by-step agent reasoning
python vital_guardian.py --demo-case 2 --verbose

# Assess from your own JSON file
python vital_guardian.py --patient my_patient.json --verbose

# Save alert output
python vital_guardian.py --demo-case 3 --output alert.txt
```

### Patient JSON Format

```json
{
  "patient_id": "PT-9999",
  "age": 68,
  "sex": "M",
  "chief_complaint": "Fever, rigors, hypotension",
  "suspected_source": "urinary",
  "known_infection": true,
  "immunocompromised": false,
  "recent_surgery": false,
  "baseline_creatinine": 1.0,
  "vitals_history": [
    {
      "timestamp": "T-2h",
      "temp_c": 38.6, "heart_rate": 108, "resp_rate": 22,
      "systolic_bp": 110, "diastolic_bp": 68, "spo2": 95.0,
      "gcs": 15, "on_supplemental_o2": false
    },
    {
      "timestamp": "T-0h",
      "temp_c": 39.1, "heart_rate": 128, "resp_rate": 26,
      "systolic_bp": 92, "diastolic_bp": 58, "spo2": 92.0,
      "gcs": 14, "on_supplemental_o2": true
    }
  ],
  "labs": {
    "wbc": 18.4,
    "bands_pct": 14.0,
    "lactate": 2.8,
    "creatinine": 1.8,
    "bilirubin": null,
    "platelet_count": 142
  }
}
```


### Example Output (Case 4 — Septic Shock)

```
════════════════════════════════════════════════════════════════════════
  🛡️  VITAL GUARDIAN ALERT  |   RISK LEVEL: CRITICAL
  Generated : 2026-11-24 20:34:19
════════════════════════════════════════════════════════════════════════

  PATIENT   : PT-0004
  Complaint : Acute abdomen — post bowel perforation repair, unresponsive
  Source    : ABDOMINAL infection suspected

  qSOFA 3/3 — ⚠️ HIGH RISK: Sepsis workup indicated
  SIRS  4/4 — ⚠️ SIRS criteria met (inflammatory state)
  NEWS2 18/20 — 🚨 URGENT: Emergency clinical review

  Estimated SOFA: ~11 (5 organ systems)

  TREND: DETERIORATING (6 vital-sign alarms)
    ❗ HR rising rapidly: +34 bpm
    ❗ SBP falling: -24 mmHg
    ❗ SpO2 dropping: -9.0%
    ❗ GCS falling: -5 points

  KEY LABS:
    🚨 Lactate: 5.6 mmol/L (critical ≥4.0)
    ⚠️ WBC: 21.8 K/uL
    ⚠️ Creatinine: 3.2 mg/dL (baseline 1.0)

  Overall Risk: 🚨 CRITICAL
  Composite risk score: 19 | 9 contributing factors

  SEPTIC SHOCK PROTOCOL ACTIVATED. Emergency response team NOW.

  SEPSIS-3 HOUR-1 BUNDLE:
    1. Measure serum lactate (repeat if initial >2 mmol/L)
    2. Obtain blood cultures ×2 sets BEFORE antibiotics
    3. Administer broad-spectrum IV antibiotics
    4. Begin 30 mL/kg IV crystalloid if MAP <65 OR lactate ≥4
    5. Apply vasopressors (norepinephrine first-line) if MAP <65 mmHg
```

---

## Tests

```bash
python test_vital_guardian.py           # 45 tests via unittest
# or
python -m pytest test_vital_guardian.py -v
```

**Test coverage:**
- qSOFA: 7 tests (all threshold combinations, missing values)
- SIRS: 7 tests (all criteria including bands)
- NEWS2: 7 tests (all sub-scores, urgent threshold)
- Trend detection: 6 tests (deteriorating, stable, edge cases)
- Risk stratification: 3 tests (green, critical, lactate amplification)
- Full pipeline: 10 tests (all 5 cases, bundle presence, disclaimer, error handling)
- Edge cases: 5 tests (extreme values, missing labs, boundary BPs)

---


## Why This Matters

Sepsis is simultaneously the most preventable and most underfunded clinical problem in modern medicine:

- **350,000 Americans** die of sepsis annually (AHRQ)
- **$62 billion** in annual U.S. hospital costs
- **1 in 3** hospital deaths involve sepsis
- Early detection reduces mortality by **up to 42%** (academic medical center AI studies)
- Every **1-hour delay** in treatment increases mortality risk by ~7%
- Most hospitals still rely on a **single manual score** calculated by an overworked nurse

This agent demonstrates that a simple, interpretable, evidence-based multi-scoring pipeline — running four validated clinical tools simultaneously, analyzing trends, and surfacing actionable alerts — can be built in pure Python with zero external APIs. Imagine this connected to real healthcare data streams.

---

## Architecture for Real-World Extension

```
Real EHR / FHIR stream
       │
       ▼  (replace DEMO_PATIENTS with FHIR R4 parser)
VitalGuardianAgent.run(patient)
       │
       ├── Pager / SMART on FHIR alert
       ├── EHR notification (Healthcare Org API)
       └── Dashboard update (Streamlit / Grafana)
```

The core scoring and trend logic are FHIR-agnostic. Connect any structured data source.

---

## Project Structure

```
vital-guardian/
├── vital_guardian.py       # Main agent + all scoring logic (single-file, easy to study)
├── test_vital_guardian.py  # 45 unit tests
├── requirements.txt        # pytest only (agent itself: stdlib)
├── .gitignore
└── README.md
```

---

## Contributing

Pull requests welcome! Suggested extensions:

- FHIR R4 patient data parser
- Streamlit real-time dashboard
- Care bundle checklist tracker
- Multi-patient monitoring loop
- Benchmarking against MIMIC-III dataset
- ICU-specific SOFA calculator (requires ventilator data)

---

## Evidence & References

1. Singer M, et al. The Third International Consensus Definitions for Sepsis and Septic Shock (Sepsis-3). *JAMA* 2016; 315(8):801–810.
2. Bone RC, et al. Definitions for sepsis and organ failure. *Chest* 1992; 101(6):1644–1655.
3. Royal College of Physicians. National Early Warning Score (NEWS) 2. London: RCP, 2017.
4. Vincent JL, et al. The SOFA (Sepsis-related Organ Failure Assessment) score. *Intensive Care Med* 1996; 22(7):707–710.
5. Levy MM, et al. The Surviving Sepsis Campaign Bundle: 2018 Update. *Crit Care Med* 2018; 46(6):997–1006.
6. AHRQ. Sepsis: A Preventable Threat. Agency for Healthcare Research and Quality, 2024.
7. CLPMag. Rapid deterioration detection reduces mortality by 42% — academic medical center study, 2024.
8. ECRI Institute. Top 10 Patient Safety Concerns 2026. Healthcare system-wide report.

---

## License

MIT License — see [LICENSE](LICENSE). Free to use, fork, and adapt.

---

## Disclaimer

**FOR RESEARCH AND EDUCATION ONLY.** This tool is not validated for clinical use and must not be used for direct patient care decisions. All clinical decisions must be made by qualified, licensed healthcare professionals. This project demonstrates agentic AI architecture patterns using validated scoring algorithms in a research context.

---

*Built as an open-source contribution to healthcare AI tooling. If this helped you learn, please ⭐ the repo and share with your clinical informatics team.*
