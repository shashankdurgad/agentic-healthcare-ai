#!/usr/bin/env python3
"""Regenerate judge-only Overmind dataset from fixtures.

must_mention is derived deterministically from vitals/meds/literal chart text.
expected_output is always null (no synthetic clinical gold).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "patients.json"
OUT_JSONL = ROOT / ".overmind" / "dataset.jsonl"
OUT_JSON = ROOT / ".overmind" / "dataset.json"


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
    allergies = [a.lower() for a in (chart.get("allergies") or [])]
    complaint = (chart.get("chief_complaint") or "").lower()
    context = (chart.get("context") or "").lower()
    history = " ".join(chart.get("history") or []).lower()
    blob = f"{complaint} {context} {history} {meds}"

    if sys is not None and sys < 90:
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

    literals = [
        ("chest pain", "chest pain"),
        ("diaphoresis", "diaphoresis"),
        ("radiating", "radiation"),
        ("melena", "melena"),
        ("tarry", "melena"),
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
        ("red swollen", "leg erythema"),
        ("sertraline", "sertraline"),
        ("no si", "no suicidal ideation"),
        ("accessory muscle", "accessory muscle use"),
        ("mottled", "mottled skin"),
    ]
    for needle, label in literals:
        if needle in blob and label not in must:
            must.append(label)

    nsaid = any(x in meds for x in ["ibuprofen", "naproxen", "diclofenac", "nsaid"])
    if "warfarin" in meds and (nsaid or "aspirin" in meds):
        must.append("anticoagulant bleed risk")
    if "insulin" in meds and ("42" in context or "glucose" in context):
        must.append("insulin")
    if "digoxin" in meds and "digoxin" not in must:
        must.append("digoxin")
    for a in allergies:
        if a:
            must.append(f"allergy:{a}")
    if chart.get("age") is not None and chart["age"] < 18:
        must.append(f"age:{chart['age']}")

    seen: set[str] = set()
    out: list[str] = []
    for item in must:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def main() -> None:
    fixtures = json.loads(FIXTURES.read_text())
    rows = []
    for pid, chart in fixtures.items():
        rows.append(
            {
                "input": {"patient_id": pid},
                "expected_output": None,
                "extra": {
                    "id": pid,
                    "label_source": "fixture_derived_must_mention_only",
                    "must_mention": derive_must_mention(chart),
                    "judge_only": True,
                },
            }
        )

    OUT_JSONL.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")
    bundle = {
        "intent": "eval",
        "agent": "healthcare-crewai",
        "description": "Judge-only dataset. expected_output is null. extra.must_mention is fixture-derived.",
        "labeling": {
            "expected_output": None,
            "must_mention_rules": [
                "systolic BP < 90 → hypotension",
                "HR >= 100 → tachycardia; HR < 50 → bradycardia",
                "RR >= 24 → tachypnea",
                "SpO2 <= 94 → hypoxia",
                "temp_c >= 38 → fever",
                "warfarin + NSAID/aspirin → anticoagulant bleed risk",
                "literal complaint/context phrases and listed allergies must be reflected",
            ],
        },
        "datapoints": rows,
    }
    OUT_JSON.write_text(json.dumps(bundle, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {len(rows)} datapoints -> {OUT_JSONL}")


if __name__ == "__main__":
    main()
