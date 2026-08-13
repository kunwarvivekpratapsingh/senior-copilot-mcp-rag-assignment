---
doc_id: TS-RECUR
title: Recurring High-Severity Alarm Troubleshooting
doc_type: troubleshooting_guide
asset_tags:
  - Boiler Feed Pump 101
  - Boiler Feed Pump 102
  - Condensate Pump 301
  - Charge Pump 305
unit: all
site: all
last_reviewed: 2026-02-28
version: "2.4"
---

# Recurring High-Severity Alarm Troubleshooting

## Purpose

How to investigate an alarm that keeps returning. A recurring high-severity alarm is
a different problem from a one-off: the equipment is telling you something systematic,
and acknowledging it repeatedly is not a response.

## Establishing that recurrence is real

Before investigating, confirm the pattern:

- **Count occurrences over a defined window.** Fewer than five in 90 days is usually
  noise. More than twenty suggests the setpoint is wrong rather than the equipment.
- **Check whether occurrences cluster.** Evenly spread occurrences point to a
  progressive condition such as fouling or wear. Clustered occurrences point to an
  operational trigger — a startup, a load change, a switchover.
- **Check the acknowledgement delay trend.** A rising delay means operators have begun
  to discount the alarm, which is itself a finding: the alarm has lost credibility and
  will be missed when it matters.

## Likely contributing factors, in order of frequency

### 1. Progressive fouling or blockage

The most common cause of a recurring process alarm. Characterised by a slow trend
between occurrences and a return to normal immediately after cleaning. Look for a
shortening interval between events — that is the signature.

### 2. Setpoint too tight for actual duty

If the alarm fires during normal operating excursions that cause no harm, the setpoint
is wrong. This is the second most common cause and the most commonly missed, because
the alarm is technically working. The evidence is that every occurrence clears without
intervention.

### 3. A second condition firing alongside

Two alarms that consistently occur within minutes of each other are usually one
physical event. Look at what else fired in the same window before concluding the
alarm is isolated. **Co-occurrence with a lift value above 1.0 indicates a genuine
relationship; a high count alone does not** — a common alarm will appear alongside
everything.

### 4. Instrument fault

A drifting or noisy transmitter produces alarms indistinguishable from a real process
condition. Suspect this when the alarm clears with no intervention and no
corresponding change in related measurements.

### 5. Mechanical degradation

Bearing wear, impeller erosion, and coupling misalignment produce alarms that recur
with increasing frequency and increasing severity. Distinguished from fouling by the
trend not resetting after cleaning.

## Investigation sequence

1. Quantify: how many occurrences, over what window, at what severity.
2. Correlate: what else fires alongside, and is the association stronger than chance.
3. Contextualise: what is the asset, its criticality, and when was it last maintained.
4. Decide: is this an equipment problem, a setpoint problem, or an instrument problem.
5. Act: repair, re-tune, or rationalize — and record which, so the next occurrence
   has history.

## When to raise a work order

Raise one when the investigation concludes the cause is physical and requires
intervention. Do **not** raise one for a setpoint problem — that is an alarm
rationalization action, and routing it to maintenance guarantees it will be closed
without change.

## Related documents

- STD-RATIONAL — Alarm Rationalization Standard
- PHIL-ALARM — Alarm Philosophy: Severity and Response
- OP-BFP-101 — Boiler Feed Pump 101 Operating Procedure
