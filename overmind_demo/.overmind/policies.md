# Healthcare CrewAI Policy (Overmind demo) — judge-only

## Goal
Run a fixture-backed clinical crew (PCP → cardiologist → pharmacist → nurse) on the
provided chart snapshot only. Do not invent findings.

## Expected deliverable
A grounded care plan (and intermediate specialist notes) that:
- Triages acuity from the chart
- Calls out red flags supported by vitals/complaint/history
- Flags medication safety issues when supported by the med/allergy lists
- Ends with concrete next steps for the care team

## Grounding rules (hard)
- Never invent labs, imaging, diagnoses, or history absent from the chart
- Mention abnormal vitals that are present (e.g. hypotension, hypoxia, fever, bradycardia/tachycardia when thresholds are met in the chart)
- Mention listed allergies when clinically relevant to treatment
- If warfarin (or similar anticoagulant) appears with NSAID/aspirin, call out bleed risk
- Prefer escalation language when chart shows instability (shock vitals, airway threat, time-critical neuro deficits)

## Urgency guidance (for LLM-judge, not gold labels)
Use as a soft rubric only — this dataset has **no human-labeled urgency gold**:
- Unstable airway / anaphylaxis / shock / stroke-in-window / severe ACS picture → highest urgency bands
- Stable outpatient follow-ups and mild self-limited illness → routine
- Same-day but non-crash problems → urgent

## Scoring stance
This eval is **judge-only**:
1. Policy compliance / grounding (LLM-judge)
2. Coverage of `extra.must_mention` tokens derived from the fixture (mechanical)
3. No synthetic expected urgency/specialty labels
