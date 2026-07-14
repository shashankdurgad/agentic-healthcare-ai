#!/usr/bin/env python3
"""Regenerate judge-only Overmind dataset from fixtures.

must_mention is fixture-grounded but uses clinical phrasing agents are expected
to write (aligned with eval/policies.md):
- abnormal vitals → hypotension / tachycardia / etc. (from fixture thresholds)
- chart phrases → standard clinical tokens (e.g. tarry stools → melena)
- meds / allergies / key history as written in the fixture

expected_output is always null. Rows are flat (no nested extra).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "patients.json"
OUT_JSONL = ROOT / "eval" / "dataset.jsonl"
OUT_JSON = ROOT / "eval" / "dataset.json"


def parse_bp(bp: str):
    m = re.match(r"(\d+)\s*/\s*(\d+)", str(bp or ""))
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


def derive_must_mention(chart: dict) -> list[str]:
    must: list[str] = []
    vitals = chart.get("vitals") or {}
    sys, _ = parse_bp(vitals.get("bp"))
    hr = vitals.get("hr")
    rr = vitals.get("rr")
    spo2 = vitals.get("spo2")
    temp = vitals.get("temp_c")
    meds = " ".join(chart.get("medications") or []).lower()
    allergies = [str(a).lower() for a in (chart.get("allergies") or []) if a]
    history = [
        str(h).lower()
        for h in (chart.get("history") or [])
        if h and str(h).lower() != "none"
    ]
    complaint = (chart.get("chief_complaint") or "").lower()
    context = (chart.get("context") or "").lower()
    blob = f"{complaint} {context} {' '.join(history)} {meds}"

    # Clinical vital labels (match policies.md). Thresholds applied to fixture numbers.
    # Adults: sys < 100 → hypotension (catches warfarin 92/58). Classic shock: sys < 90 any age.
    age = chart.get("age")
    adult = age is None or int(age) >= 18
    if sys is not None and (sys < 90 or (adult and sys < 100)):
        must.append("hypotension")
    if hr is not None and hr >= 100:
        must.append("tachycardia")
    if hr is not None and hr < 50:
        must.append("bradycardia")
    if rr is not None and rr >= 24:
        must.append("tachypnea")
    if spo2 is not None and spo2 <= 94:
        must.append("hypoxia")
    if temp is not None and temp >= 38.0:
        must.append("fever")

    # Fixture evidence → clinical token the model is expected to use in prose.
    phrase_to_clinical = [
        ("chest pain", "chest pain"),
        ("diaphoresis", "diaphoresis"),
        ("radiating", "radiation"),
        ("tarry", "melena"),
        ("melena", "melena"),
        ("wheez", "wheeze"),
        ("lip swelling", "lip swelling"),
        ("hives", "hives"),
        ("peanut", "peanut"),
        ("dysuria", "dysuria"),
        ("slurred speech", "slurred speech"),
        ("weakness", "weakness"),
        ("facial droop", "facial droop"),
        ("confusion", "confusion"),
        ("glucose 42", "hypoglycemia"),
        ("42 mg/dl", "hypoglycemia"),
        ("visual halo", "visual changes"),
        ("digoxin", "digoxin"),
        ("pregnant", "pregnancy"),
        ("migraine", "migraine"),
        ("red swollen", "erythema"),
        ("sertraline", "sertraline"),
        ("no si", "no suicidal ideation"),
        ("suicidal ideation", "no suicidal ideation"),
        ("accessory muscle", "accessory muscle use"),
        ("mottled", "mottled skin"),
        ("blood pressure", "blood pressure"),
        ("hypertension", "hypertension"),
        ("warfarin", "warfarin"),
        ("ibuprofen", "ibuprofen"),
        ("aspirin", "aspirin"),
        ("insulin", "insulin"),
        ("amlodipine", "amlodipine"),
    ]
    for needle, label in phrase_to_clinical:
        if needle in blob and label not in must:
            must.append(label)

    nsaid = any(x in meds for x in ["ibuprofen", "naproxen", "diclofenac", "nsaid"])
    if "warfarin" in meds and (nsaid or "aspirin" in meds):
        if "bleed risk" not in must:
            must.append("bleed risk")

    # High-signal history only (skip dumping every chronic item).
    history_keep = {
        "atrial fibrillation",
        "prior gi bleed",
        "ckd stage 3",
        "ckd stage 4",
        "heart failure",
        "type 2 diabetes",
        "asthma",
        "known peanut allergy",
        "major depressive disorder",
        "g1p0 intrauterine pregnancy",
        "recurrent uti",
        "recent uti",
    }
    for item in history:
        if item in history_keep and item not in must:
            must.append(item)

    for allergy in allergies:
        # Prefer a single peanut token if both peanut/peanuts appear.
        if allergy in {"peanut", "peanuts"}:
            if "peanut" not in must:
                must.append("peanut")
            continue
        if allergy not in must:
            must.append(allergy)

    if chart.get("age") is not None and int(chart["age"]) < 18:
        must.append(f"age {chart['age']}")

    seen: set[str] = set()
    out: list[str] = []
    for item in must:
        key = item.lower().strip()
        if key and key not in seen:
            seen.add(key)
            out.append(key)
    return out


def main() -> None:
    fixtures = json.loads(FIXTURES.read_text())
    rows = []
    for pid, chart in fixtures.items():
        mentions = derive_must_mention(chart)
        if not mentions:
            raise SystemExit(f"empty must_mention for {pid}")
        rows.append(
            {
                "input": {"patient_id": pid},
                "expected_output": None,
                "id": pid,
                "judge_only": True,
                "must_mention": mentions,
            }
        )

    OUT_JSONL.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSONL.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")
    bundle = {
        "intent": "eval",
        "agent": "healthcare-crewai",
        "description": (
            "Judge-only dataset. expected_output is null. "
            "must_mention uses clinical tokens grounded in fixture facts/thresholds."
        ),
        "labeling": {
            "expected_output": None,
            "must_mention_rules": [
                "systolic BP < 90 → hypotension (any age); adults also if BP < 100 (e.g. 92/58)",
                "HR >= 100 → tachycardia; HR < 50 → bradycardia",
                "RR >= 24 → tachypnea; SpO2 <= 94 → hypoxia; temp >= 38 → fever",
                "Fixture phrases map to clinical tokens (tarry→melena, radiating→radiation, etc.)",
                "warfarin + NSAID/aspirin → bleed risk",
                "No bare vital numbers; no nested extra",
            ],
        },
        "datapoints": rows,
    }
    OUT_JSON.write_text(json.dumps(bundle, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {len(rows)} datapoints -> {OUT_JSONL}")
    for r in rows:
        print(f"  {r['id']}: {r['must_mention']}")


if __name__ == "__main__":
    main()
