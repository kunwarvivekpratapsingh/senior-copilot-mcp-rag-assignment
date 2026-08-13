---
doc_id: PHIL-ALARM
title: "Alarm Philosophy: Severity and Response"
doc_type: alarm_philosophy
asset_tags: []
unit: all
site: all
last_reviewed: 2026-02-10
version: "4.2"
---

# Alarm Philosophy: Severity and Response

## Principle

Every alarm must require a response, and every alarm must allow time for that
response. An alarm that requires no action is not an alarm; it is a nuisance, and it
erodes the credibility of the ones that matter.

## Severity definitions

| Severity | Meaning | Expected response time | Escalation |
|---|---|---|---|
| Critical | Immediate threat to safety, environment, or major equipment | Immediate | Shift engineer at once |
| High | Significant process deviation; damage likely if unaddressed | Within 5 minutes | Shift engineer within 30 minutes |
| Medium | Process deviation requiring attention this shift | Within 30 minutes | Log for the next shift |
| Low | Informational; action at next opportunity | This shift | None |

## Acknowledgement expectations

Acknowledgement is not a response. It records that the alarm has been seen.
An alarm acknowledged and not acted upon should be treated as unaddressed.

The target is 90% of high and critical alarms acknowledged within 300 seconds.
Sustained performance below that figure indicates either an alarm loading problem or
a staffing problem, and the distinction matters: adding operators will not fix a
console presenting more alarms than any operator can process.

## Alarm flooding

More than ten alarms in ten minutes on a single console constitutes a flood. During a
flood the operator cannot reliably read, prioritise, or act, so alarms occurring
inside one are effectively unpresented regardless of severity.

Floods are a design problem, not an operator problem. The response is rationalization
and suppression of the contributing alarms, not additional training.

## Stale alarms

An alarm active for more than three hours without acknowledgement indicates a
workflow failure rather than an equipment failure. Investigate routing and operator
loading before assuming the alarm was ignored.

## Related documents

- STD-RATIONAL - Alarm Rationalization Standard
- STD-OPRESP - Operator Response Standards
