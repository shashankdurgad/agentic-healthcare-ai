# Healthcare CrewAI Policy (Overmind demo) — judge-only

## Goal
Run a fixture-seeded FHIR-backed clinical crew (PCP → cardiologist → pharmacist → nurse).
Agents must ground assessments in chart data retrieved via FHIR MCP tool calls.
Do not invent findings.

## Expected deliverable
A grounded care plan (and intermediate specialist notes) that:
- Triages acuity from the chart
- Calls out red flags supported by vitals/complaint/history
- Flags medication safety issues when supported by the med/allergy lists
- Ends with concrete next steps for the care team

## Grounding rules (hard)
- Never invent labs, imaging, diagnoses, or history absent from the FHIR chart
- Call out abnormal vitals using clinical language when fixture thresholds are met:
  - systolic BP < 90 → hypotension (any age); adults also if systolic BP < 100 (e.g. 92/58)
  - HR >= 100 → tachycardia; HR < 50 → bradycardia
  - RR >= 24 → tachypnea
  - SpO2 <= 94 → hypoxia
  - temp_c >= 38 → fever
- Prefer clinical terms for chart phrases (e.g. black tarry stools → melena; radiating pain → radiation; wheeze; erythema)
- Mention listed allergies when clinically relevant to treatment
- If warfarin (or similar anticoagulant) appears with NSAID/aspirin, call out bleed risk
- Prefer escalation language when chart shows instability (shock vitals, airway threat, time-critical neuro deficits)
- Urgency labels should use: `routine` | `urgent` | `emergent` | `stat`

## Urgency guidance (for LLM-judge, not gold labels)
Use as a soft rubric only — this dataset has **no human-labeled urgency gold**:
- Unstable airway / anaphylaxis / shock / stroke-in-window / severe ACS picture → highest urgency bands
- Stable outpatient follow-ups and mild self-limited illness → routine
- Same-day but non-crash problems → urgent

## Scoring stance
This eval is **judge-only**:
1. Policy compliance / grounding (LLM-judge) — same clinical vocabulary as `must_mention`
2. Coverage of `must_mention` tokens (mechanical) — clinical tokens derived from fixture facts/thresholds, not bare vital numbers
3. No synthetic expected urgency/specialty labels
