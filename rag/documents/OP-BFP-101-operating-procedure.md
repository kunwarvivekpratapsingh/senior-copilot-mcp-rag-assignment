---
doc_id: OP-BFP-101
title: Boiler Feed Pump 101 Operating Procedure
doc_type: operating_procedure
asset_tags:
  - Boiler Feed Pump 101
  - Boiler Feed Pump 102
  - Boiler Feed Pump 103
unit: Unit 2
site: NorthPlant
last_reviewed: 2026-03-14
version: "3.1"
---

# Boiler Feed Pump 101 — Operating Procedure

## Scope

Normal operation, monitoring, and abnormal-condition response for the Unit 2 boiler
feed pumps. Applies to BFP-101, BFP-102, and BFP-103.

## Normal operating envelope

| Parameter | Normal | Alarm setpoint | Trip |
|---|---|---|---|
| Discharge pressure | 82–88 barg | Low at 78 barg | 72 barg |
| Suction strainer differential | 0.1–0.3 bar | High at 0.5 bar | 0.8 bar |
| Bearing temperature | 45–65 °C | High at 80 °C | 95 °C |
| Vibration (velocity RMS) | < 2.8 mm/s | High at 4.5 mm/s | 7.1 mm/s |

Record discharge pressure and suction strainer differential once per shift. A rising
differential trend is the earliest available indicator of strainer fouling, and it
appears well before discharge pressure is affected.

## Abnormal condition: discharge pressure low

Discharge pressure low is the most frequent alarm on this equipment. **In the majority
of cases the cause is upstream of the pump, not within it.** Work the suction side
first; investigating the pump internals before confirming suction conditions wastes
time and, if the pump is left running while cavitating, causes avoidable damage.

1. **Check the suction strainer differential pressure** against the clean-filter
   baseline of 0.1–0.3 bar. A differential above 0.5 bar indicates progressive
   blockage and is the single most common root cause of this alarm.
2. **Check suction vessel level and temperature.** Low level or elevated temperature
   reduces net positive suction head available and produces the same symptom.
3. **Listen for cavitation** — a characteristic gravel-like noise, accompanied by
   erratic flow indication and elevated vibration. Cavitation erodes the impeller
   quickly. If confirmed, reduce flow and correct the suction condition before
   continuing to run.
4. **If suction conditions are normal**, the cause is internal. Arrange inspection of
   the impeller and wear rings for erosion or clearance loss.

## Abnormal condition: suction strainer differential high

1. Confirm the reading against the local gauge; a failed transmitter presents
   identically to a fouled strainer.
2. If genuine, switch to the standby strainer where fitted and clean the affected
   element.
3. **Verify that discharge pressure recovers after cleaning.** This step is what
   confirms the two conditions were related rather than coincidental.
4. Record the interval since the last clean. A shortening interval indicates a
   change in feedwater quality and should be raised with the water treatment group.

## The recurring pair: discharge pressure low with suction strainer differential high

When these two alarms occur together within a short interval — typically minutes —
they are almost always one event, not two. The strainer fouls, suction is restricted,
and discharge pressure falls in consequence.

Treating them as separate alarms leads to the strainer being cleaned and the
discharge pressure alarm being separately acknowledged without the connection being
made, so the underlying fouling rate is never addressed. **If this pairing recurs,
the correct response is to investigate feedwater quality and strainer sizing, not to
keep cleaning the strainer.**

Persistent recurrence of this pair is a rationalization candidate: either the
strainer differential setpoint is too tight for the actual duty, or the cleaning
interval is too long for the feedwater condition.

## Escalation

Escalate to the Unit 2 shift engineer when:

- Discharge pressure remains below 78 barg after suction conditions are confirmed normal
- The same alarm pair recurs more than five times in a rolling 30-day window
- Cavitation is confirmed and cannot be cleared by reducing flow

## Related documents

- MAINT-BFP — Boiler Feed Pump Maintenance Guide
- TS-RECUR — Recurring Alarm Troubleshooting
- SAFE-LOTO-PUMP — Lockout/Tagout for Pump Systems
