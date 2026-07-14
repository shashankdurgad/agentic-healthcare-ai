#!/usr/bin/env python3
"""Seed local HAPI FHIR from overmind_demo fixtures (idempotent PUT by fixed IDs)."""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

FIXTURES = Path(os.environ.get("FIXTURES_PATH", "/fixtures/patients.json"))
FHIR_BASE = os.environ.get("FHIR_BASE_URL", "http://hapi-fhir:8080/fhir").rstrip("/")
MAX_WAIT = int(os.environ.get("FHIR_SEED_WAIT_SECONDS", "180"))


def _request(method: str, url: str, body: dict | None = None) -> tuple[int, Any]:
    data = None
    headers = {"Accept": "application/fhir+json"}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/fhir+json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode() or "{}"
            return resp.status, json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode() if exc.fp else ""
        try:
            parsed = json.loads(raw) if raw.strip() else {"text": raw}
        except json.JSONDecodeError:
            parsed = {"text": raw}
        return exc.code, parsed


def wait_for_hapi() -> None:
    deadline = time.time() + MAX_WAIT
    url = f"{FHIR_BASE}/metadata"
    while time.time() < deadline:
        try:
            code, _ = _request("GET", url)
            if code == 200:
                print(f"HAPI ready at {FHIR_BASE}")
                return
        except Exception as exc:
            print(f"waiting for HAPI: {exc}")
        time.sleep(3)
    raise SystemExit(f"HAPI not ready after {MAX_WAIT}s: {url}")


def put_resource(resource_type: str, resource_id: str, resource: dict) -> None:
    resource = {**resource, "resourceType": resource_type, "id": resource_id}
    url = f"{FHIR_BASE}/{resource_type}/{resource_id}"
    code, body = _request("PUT", url, resource)
    if code not in (200, 201):
        raise RuntimeError(f"PUT {url} failed ({code}): {body}")
    print(f"  upserted {resource_type}/{resource_id}")


def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:48] or "item"


def birth_date_from_age(age: Any) -> str | None:
    try:
        years = int(age)
    except (TypeError, ValueError):
        return None
    today = date.today()
    try:
        return date(today.year - years, today.month, today.day).isoformat()
    except ValueError:
        return date(today.year - years, today.month, 28).isoformat()


def parse_bp(bp: str) -> tuple[float | None, float | None]:
    m = re.match(r"(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)", str(bp or ""))
    if not m:
        return None, None
    return float(m.group(1)), float(m.group(2))


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def patient_resource(pid: str, chart: dict) -> dict:
    sex = (chart.get("sex") or "unknown").lower()
    gender = {"male": "male", "female": "female", "other": "other"}.get(sex, "unknown")
    given = "Demo"
    family = pid.replace("patient-", "").replace("-", " ").title()
    resource: dict[str, Any] = {
        "active": True,
        "name": [{"use": "official", "family": family, "given": [given]}],
        "gender": gender,
        "identifier": [
            {
                "system": "urn:overmind-demo:patient-id",
                "value": pid,
            }
        ],
    }
    bd = birth_date_from_age(chart.get("age"))
    if bd:
        resource["birthDate"] = bd
    return resource


def condition_resources(pid: str, chart: dict) -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    for i, item in enumerate(chart.get("history") or []):
        rid = f"{pid}-hx-{i}-{slug(str(item))}"
        out.append(
            (
                rid,
                {
                    "clinicalStatus": {
                        "coding": [
                            {
                                "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                                "code": "active",
                            }
                        ]
                    },
                    "code": {"text": str(item)},
                    "subject": {"reference": f"Patient/{pid}"},
                    "recordedDate": now_iso(),
                },
            )
        )
    complaint = chart.get("chief_complaint")
    if complaint:
        rid = f"{pid}-cc"
        out.append(
            (
                rid,
                {
                    "clinicalStatus": {
                        "coding": [
                            {
                                "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                                "code": "active",
                            }
                        ]
                    },
                    "category": [
                        {
                            "coding": [
                                {
                                    "system": "http://terminology.hl7.org/CodeSystem/condition-category",
                                    "code": "encounter-diagnosis",
                                }
                            ],
                            "text": "chief complaint",
                        }
                    ],
                    "code": {"text": str(complaint)},
                    "subject": {"reference": f"Patient/{pid}"},
                    "recordedDate": now_iso(),
                    "note": [{"text": str(complaint)}],
                },
            )
        )
    return out


def medication_resources(pid: str, chart: dict) -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    for i, med in enumerate(chart.get("medications") or []):
        rid = f"{pid}-med-{i}-{slug(str(med))}"
        out.append(
            (
                rid,
                {
                    "status": "active",
                    "intent": "order",
                    "medicationCodeableConcept": {"text": str(med)},
                    "subject": {"reference": f"Patient/{pid}"},
                    "authoredOn": now_iso(),
                    "dosageInstruction": [{"text": str(med)}],
                },
            )
        )
    return out


def allergy_resources(pid: str, chart: dict) -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    for i, allergen in enumerate(chart.get("allergies") or []):
        rid = f"{pid}-alg-{i}-{slug(str(allergen))}"
        out.append(
            (
                rid,
                {
                    "clinicalStatus": {
                        "coding": [
                            {
                                "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical",
                                "code": "active",
                            }
                        ]
                    },
                    "verificationStatus": {
                        "coding": [
                            {
                                "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-verification",
                                "code": "confirmed",
                            }
                        ]
                    },
                    "code": {"text": str(allergen)},
                    "patient": {"reference": f"Patient/{pid}"},
                    "recordedDate": now_iso(),
                },
            )
        )
    return out


def vital_observations(pid: str, chart: dict) -> list[tuple[str, dict]]:
    vitals = chart.get("vitals") or {}
    out: list[tuple[str, dict]] = []
    effective = now_iso()

    def qty_obs(rid: str, loinc: str, display: str, value: float, unit: str, code: str) -> None:
        out.append(
            (
                rid,
                {
                    "status": "final",
                    "category": [
                        {
                            "coding": [
                                {
                                    "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                                    "code": "vital-signs",
                                }
                            ]
                        }
                    ],
                    "code": {
                        "coding": [{"system": "http://loinc.org", "code": loinc, "display": display}],
                        "text": display,
                    },
                    "subject": {"reference": f"Patient/{pid}"},
                    "effectiveDateTime": effective,
                    "valueQuantity": {
                        "value": value,
                        "unit": unit,
                        "system": "http://unitsofmeasure.org",
                        "code": code,
                    },
                },
            )
        )

    sys_bp, dia_bp = parse_bp(vitals.get("bp"))
    if sys_bp is not None and dia_bp is not None:
        out.append(
            (
                f"{pid}-vit-bp",
                {
                    "status": "final",
                    "category": [
                        {
                            "coding": [
                                {
                                    "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                                    "code": "vital-signs",
                                }
                            ]
                        }
                    ],
                    "code": {
                        "coding": [
                            {
                                "system": "http://loinc.org",
                                "code": "85354-9",
                                "display": "Blood pressure panel",
                            }
                        ],
                        "text": f"Blood pressure {sys_bp}/{dia_bp}",
                    },
                    "subject": {"reference": f"Patient/{pid}"},
                    "effectiveDateTime": effective,
                    "component": [
                        {
                            "code": {
                                "coding": [
                                    {
                                        "system": "http://loinc.org",
                                        "code": "8480-6",
                                        "display": "Systolic blood pressure",
                                    }
                                ]
                            },
                            "valueQuantity": {
                                "value": sys_bp,
                                "unit": "mmHg",
                                "system": "http://unitsofmeasure.org",
                                "code": "mm[Hg]",
                            },
                        },
                        {
                            "code": {
                                "coding": [
                                    {
                                        "system": "http://loinc.org",
                                        "code": "8462-4",
                                        "display": "Diastolic blood pressure",
                                    }
                                ]
                            },
                            "valueQuantity": {
                                "value": dia_bp,
                                "unit": "mmHg",
                                "system": "http://unitsofmeasure.org",
                                "code": "mm[Hg]",
                            },
                        },
                    ],
                },
            )
        )

    if vitals.get("hr") is not None:
        qty_obs(f"{pid}-vit-hr", "8867-4", "Heart rate", float(vitals["hr"]), "/min", "/min")
    if vitals.get("rr") is not None:
        qty_obs(
            f"{pid}-vit-rr",
            "9279-1",
            "Respiratory rate",
            float(vitals["rr"]),
            "/min",
            "/min",
        )
    if vitals.get("spo2") is not None:
        qty_obs(
            f"{pid}-vit-spo2",
            "2708-6",
            "Oxygen saturation",
            float(vitals["spo2"]),
            "%",
            "%",
        )
    if vitals.get("temp_c") is not None:
        qty_obs(
            f"{pid}-vit-temp",
            "8310-5",
            "Body temperature",
            float(vitals["temp_c"]),
            "Cel",
            "Cel",
        )
    return out


def document_resources(pid: str, chart: dict) -> list[tuple[str, dict]]:
    parts = []
    if chart.get("chief_complaint"):
        parts.append(f"Chief complaint: {chart['chief_complaint']}")
    if chart.get("context"):
        parts.append(f"Context: {chart['context']}")
    if not parts:
        return []
    text = "\n".join(parts)
    rid = f"{pid}-note"
    return [
        (
            rid,
            {
                "status": "current",
                "type": {"text": "clinical note"},
                "subject": {"reference": f"Patient/{pid}"},
                "date": now_iso(),
                "description": "Visit narrative from Overmind demo fixtures",
                "content": [
                    {
                        "attachment": {
                            "contentType": "text/plain",
                            "title": "clinical-note",
                            "data": __import__("base64").b64encode(text.encode()).decode(),
                        }
                    }
                ],
            },
        )
    ]


def seed_patient(pid: str, chart: dict) -> None:
    print(f"Seeding {pid}")
    put_resource("Patient", pid, patient_resource(pid, chart))
    for rid, res in condition_resources(pid, chart):
        put_resource("Condition", rid, res)
    for rid, res in medication_resources(pid, chart):
        put_resource("MedicationRequest", rid, res)
    for rid, res in allergy_resources(pid, chart):
        put_resource("AllergyIntolerance", rid, res)
    for rid, res in vital_observations(pid, chart):
        put_resource("Observation", rid, res)
    for rid, res in document_resources(pid, chart):
        put_resource("DocumentReference", rid, res)


def main() -> int:
    wait_for_hapi()
    if not FIXTURES.exists():
        print(f"fixtures not found: {FIXTURES}", file=sys.stderr)
        return 1
    charts = json.loads(FIXTURES.read_text())
    for pid, chart in charts.items():
        seed_patient(pid, chart)
    print(f"Seeded {len(charts)} patients into {FHIR_BASE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
