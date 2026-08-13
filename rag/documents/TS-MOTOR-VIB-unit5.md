---
doc_id: TS-MOTOR-VIB
title: Unit 5 Motor Vibration Guide
doc_type: troubleshooting_guide
asset_tags: ["Induction Motor 601", "Induction Motor 602", "Synchronous Motor 603", "Motor Driven Pump 604"]
unit: Unit 5
site: EastRefinery
last_reviewed: 2026-03-05
version: "1.8"
---

# Unit 5 Motor Vibration Guide

## Baselines

| Machine | Commissioning baseline | Alert | Danger |
|---|---|---|---|
| Induction Motor 601 | 1.8 mm/s | 4.5 mm/s | 7.1 mm/s |
| Induction Motor 602 | 2.1 mm/s | 4.5 mm/s | 7.1 mm/s |
| Synchronous Motor 603 | 1.6 mm/s | 3.5 mm/s | 5.6 mm/s |
| Motor Driven Pump 604 | 2.4 mm/s | 4.5 mm/s | 7.1 mm/s |

## Diagnosis by spectrum

The overall level tells you something is wrong. The spectrum tells you what.

| Dominant frequency | Likely cause | Action |
|---|---|---|
| 1x running speed | Imbalance | Balance; check for fouling or a lost fan blade |
| 2x running speed | Misalignment | Check coupling alignment and soft foot |
| High frequency, non-synchronous | Bearing defect | Trend closely; plan replacement |
| 2x line frequency | Electrical - stator or rotor | Electrical testing required |

## Vibration with winding temperature high

The two together most often indicate a cooling problem rather than a mechanical one:
restricted airflow raises winding temperature, and a fouled or damaged cooling fan
raises vibration at the same time. Check the cooling path before pursuing a
mechanical diagnosis.

## Escalation

Escalate immediately at the danger level. Between alert and danger, increase the
survey frequency to weekly and trend - the rate of change matters more than the
absolute value.
