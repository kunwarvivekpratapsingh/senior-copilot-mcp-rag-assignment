---
doc_id: TS-COMP-SURGE
title: Compressor Surge Troubleshooting
doc_type: troubleshooting_guide
asset_tags: ["Air Compressor 501", "Gas Compressor 502", "Recycle Compressor 503", "Instrument Air Compressor 504"]
unit: Unit 3
site: SouthPlant
last_reviewed: 2026-02-15
version: "3.0"
---

# Compressor Surge Troubleshooting

## What surge is

Flow reversal through the compressor when operating point crosses the surge line.
Each surge cycle imposes a severe axial load on the rotor. Repeated surging destroys
thrust bearings and can wreck a machine in minutes.

## Immediate response to a surge alarm

1. **Verify anti-surge valve position and controller response.** A surge alarm with
   the anti-surge valve closed means the protection has failed to act, and that is
   the immediate concern regardless of the surge itself.
2. **Check suction pressure and flow against the surge line.** Establish how close
   the machine is operating to the limit and move the operating point away from it.
3. **Check discharge temperature.** A rising discharge temperature alongside surge
   indicates recirculation and confirms the machine is genuinely surging rather than
   the instrument being at fault.

## Common causes

- Anti-surge controller tuned for a different gas composition or molecular weight
- Fouled suction filter reducing inlet flow
- Downstream valve closing faster than the anti-surge loop can respond
- Loss of lube oil pressure causing an emergency trip that leaves the machine on the
  surge line during coast-down

## What not to do

Do not repeatedly reset and restart a machine that has surged more than twice without
establishing the cause. The thrust bearing may already be damaged, and the next start
can convert a repairable condition into a rotor replacement.

## Related documents

- PHIL-ALARM - Alarm Philosophy: Severity and Response
