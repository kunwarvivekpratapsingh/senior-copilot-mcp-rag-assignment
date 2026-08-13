---
doc_id: STD-RATIONAL
title: Alarm Rationalization Standard
doc_type: engineering_standard
asset_tags: []
unit: all
site: all
last_reviewed: 2026-02-22
version: "3.3"
---

# Alarm Rationalization Standard

## Purpose

Rationalization decides, for each alarm, whether it should exist, at what setpoint,
and at what severity. It is the mechanism by which an alarm system stays useful.

## Triggers for review

An alarm enters the rationalization backlog when any of the following hold:

- **Recurrence.** Five or more occurrences of the same alarm on the same asset within
  the review window.
- **Staleness.** Any occurrence active beyond 180 minutes without acknowledgement.
- **Chattering.** More than three occurrences within one hour.
- **Flood contribution.** Appears in more than one flood window in the period.

Recurrence and staleness call for different remedies and must not be conflated.
Recurrence is usually a setpoint or deadband problem. Staleness is a workflow problem
and will not be fixed by changing the setpoint.

## Decision options

| Finding | Action |
|---|---|
| Alarm fires during normal excursions that cause no harm | Widen the setpoint or add deadband |
| Alarm always accompanies another alarm | Suppress the subordinate one |
| Alarm requires no operator action | Reclassify as an event, not an alarm |
| Alarm is valid but the condition recurs | Raise a work order against the equipment |
| Alarm is valid and the response is slow | Address loading or routing, not the alarm |

## Suppression

Suppression is legitimate when an alarm is genuinely subordinate to another that is
already presented. It is not legitimate as a way to reduce alarm counts. Every
suppression must record the alarm it is subordinate to and be reviewed annually.

## Evidence required

A rationalization decision must record: occurrence count and window, co-occurring
alarms with their association strength, acknowledgement delay distribution, and the
operating procedure section that defines the expected response. A decision without
this evidence will be reversed the first time the alarm is missed.

## Related documents

- PHIL-ALARM - Alarm Philosophy: Severity and Response
- TS-RECUR - Recurring High-Severity Alarm Troubleshooting
