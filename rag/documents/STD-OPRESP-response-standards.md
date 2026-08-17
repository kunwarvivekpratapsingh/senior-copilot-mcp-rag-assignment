---
doc_id: STD-OPRESP
title: Operator Response Standards
doc_type: engineering_standard
asset_tags: []
unit: all
site: all
last_reviewed: 2026-01-08
version: "2.0"
---

# Operator Response Standards

## Measured expectations

| Metric | Target | Rationale |
|---|---|---|
| High/critical acknowledged within 300 s | >= 90% | Beyond five minutes a high-severity deviation is usually no longer recoverable by operator action alone |
| Median acknowledgement delay | < 120 s | Median rather than mean, because a small number of very slow acknowledgements distorts the mean |
| Alarms per operator per hour | < 12 | Above this figure response quality degrades measurably regardless of experience |
| Standing alarms at shift handover | < 5 | Each standing alarm is context the incoming operator must absorb before doing anything else |

## Interpreting response efficiency

Response efficiency is the share of acknowledged alarms answered within the 300-second
threshold. It measures the console and the workload, not individual diligence.

A figure below target usually indicates one of:

- **Alarm loading.** Too many alarms presented; the operator is triaging. Confirm by
  checking alarms per hour and flood frequency over the same period.
- **Low credibility.** A high nuisance rate teaches operators that alarms can wait.
  Confirm by checking whether slow acknowledgements concentrate on a small number of
  recurring alarm names.
- **Genuine staffing shortfall.** Confirm only after excluding the first two, because
  adding operators to a flooded console does not fix a flooded console.

## Handover

Standing alarms must be reviewed individually at handover, with the reason each
remains active stated explicitly. An alarm that cannot be explained at handover
should be escalated rather than carried forward.

## Related documents

- PHIL-ALARM - Alarm Philosophy: Severity and Response
- STD-RATIONAL - Alarm Rationalization Standard
