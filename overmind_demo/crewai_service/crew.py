"""CrewAI healthcare crew using local patient fixtures (no FHIR/MCP)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional, Type

from crewai import Agent, Crew, Process, Task
from langchain.tools import BaseTool
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

FIXTURES_PATH = Path(
    os.environ.get(
        "FIXTURES_PATH",
        str(
            next(
                (
                    p
                    for p in (
                        Path(__file__).resolve().parent / "fixtures" / "patients.json",
                        Path(__file__).resolve().parent.parent / "fixtures" / "patients.json",
                    )
                    if p.exists()
                ),
                Path(__file__).resolve().parent.parent / "fixtures" / "patients.json",
            )
        ),
    )
)


def _load_fixtures() -> dict[str, Any]:
    if not FIXTURES_PATH.exists():
        return {}
    return json.loads(FIXTURES_PATH.read_text())


def resolve_case(input_data: dict[str, Any]) -> dict[str, Any]:
    fixtures = _load_fixtures()
    patient_id = input_data.get("patient_id")
    chart = fixtures.get(patient_id, {}) if patient_id else {}
    return {
        "patient_id": patient_id or chart.get("patient_id", "unknown"),
        "age": input_data.get("age", chart.get("age")),
        "sex": input_data.get("sex", chart.get("sex")),
        "chief_complaint": input_data.get("chief_complaint", chart.get("chief_complaint", "")),
        "history": input_data.get("history", chart.get("history", [])),
        "medications": input_data.get("medications", chart.get("medications", [])),
        "vitals": input_data.get("vitals", chart.get("vitals", {})),
        "allergies": input_data.get("allergies", chart.get("allergies", [])),
        "context": input_data.get("context", chart.get("context", "")),
    }


class PatientIdInput(BaseModel):
    patient_id: str = Field(..., description="Patient ID from the local fixture chart store")


class FixturePatientTool(BaseTool):
    name: str = "fixture_patient_chart"
    description: str = (
        "Retrieve the full patient chart (demographics, complaint, history, "
        "medications, vitals, allergies, context) from local fixtures by patient_id."
    )
    args_schema: Type[BaseModel] = PatientIdInput

    def _run(self, patient_id: str) -> str:
        fixtures = _load_fixtures()
        chart = fixtures.get(patient_id)
        if not chart:
            return json.dumps({"error": f"unknown patient_id: {patient_id}", "known": list(fixtures)})
        return json.dumps(chart, indent=2)


class MedicationListInput(BaseModel):
    medications: str = Field(..., description="Comma-separated or JSON list of medication names")


class MedicationSafetyTool(BaseTool):
    name: str = "medication_safety_check"
    description: str = (
        "Heuristic medication safety check for common interaction patterns "
        "(e.g. anticoagulant + NSAID/aspirin). Input a medication list string."
    )
    args_schema: Type[BaseModel] = MedicationListInput

    def _run(self, medications: str) -> str:
        text = medications.lower()
        findings = []
        blood_thinners = ["warfarin", "heparin", "aspirin", "clopidogrel", "apixaban", "rivaroxaban"]
        nsaids = ["ibuprofen", "naproxen", "diclofenac", "nsaid"]
        has_bt = any(x in text for x in blood_thinners)
        has_nsaid = any(x in text for x in nsaids)
        if has_bt and has_nsaid:
            findings.append(
                {
                    "severity": "major",
                    "issue": "Anticoagulant/antiplatelet + NSAID",
                    "risk": "Increased bleeding risk",
                    "recommendation": "Avoid NSAID if possible; gastroprotection; urgent GI bleed workup if melena/hypotension",
                }
            )
        if "warfarin" in text and "aspirin" in text:
            findings.append(
                {
                    "severity": "major",
                    "issue": "Warfarin + aspirin",
                    "risk": "Additive bleed risk",
                    "recommendation": "Reassess dual therapy indication; monitor closely",
                }
            )
        if not findings:
            findings.append({"severity": "none", "issue": "No high-yield heuristic interactions flagged"})
        return json.dumps({"medications": medications, "findings": findings}, indent=2)


def build_llm() -> ChatOpenAI:
    api_key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY or OPENAI_API_KEY is required")

    model = os.environ.get("OVERMIND_DEMO_MODEL", "openai/gpt-4o-mini")
    # ChatOpenAI expects bare OpenAI model names when talking to api.openai.com;
    # OpenRouter wants provider/model. Keep as configured.
    base_url = os.environ.get("OPENAI_BASE_URL") or os.environ.get("OPENROUTER_BASE_URL")
    if not base_url and os.environ.get("OPENROUTER_API_KEY"):
        base_url = "https://openrouter.ai/api/v1"

    kwargs: dict[str, Any] = {
        "model": model,
        "temperature": float(os.environ.get("OVERMIND_DEMO_TEMPERATURE", "0.2")),
        "openai_api_key": api_key,
    }
    if base_url:
        kwargs["openai_api_base"] = base_url
    return ChatOpenAI(**kwargs)


class FixtureHealthcareCrew:
    """Sequential CrewAI crew: PCP → Cardiologist → Pharmacist → Nurse."""

    def __init__(self) -> None:
        self.llm = build_llm()
        self.chart_tool = FixturePatientTool()
        self.med_tool = MedicationSafetyTool()

        self.primary_care = Agent(
            role="Primary Care Physician",
            goal="Assess the patient comprehensively and identify urgency and red flags",
            backstory=(
                "Experienced primary care physician focused on triage, problem lists, "
                "and coordinating specialists."
            ),
            verbose=True,
            allow_delegation=False,
            tools=[self.chart_tool],
            llm=self.llm,
        )
        self.cardiologist = Agent(
            role="Cardiologist",
            goal="Evaluate cardiovascular risk and acute cardiac concerns",
            backstory=(
                "Board-certified cardiologist specializing in ACS risk, hypertension, "
                "and evidence-based cardiac recommendations."
            ),
            verbose=True,
            allow_delegation=False,
            tools=[self.chart_tool],
            llm=self.llm,
        )
        self.pharmacist = Agent(
            role="Clinical Pharmacist",
            goal="Ensure medication safety and flag interaction or bleed risks",
            backstory=(
                "Clinical pharmacist focused on reconciliation, interactions, "
                "and high-risk drug combinations."
            ),
            verbose=True,
            allow_delegation=False,
            tools=[self.chart_tool, self.med_tool],
            llm=self.llm,
        )
        self.nurse = Agent(
            role="Nurse Care Coordinator",
            goal="Produce an actionable care coordination and follow-up plan",
            backstory=(
                "Nurse care coordinator who turns specialist input into clear next "
                "steps, education, and escalation plans."
            ),
            verbose=True,
            allow_delegation=False,
            tools=[self.chart_tool],
            llm=self.llm,
        )

    def run(self, input_data: dict[str, Any]) -> dict[str, Any]:
        case = resolve_case(input_data)
        patient_id = case["patient_id"]
        case_json = json.dumps(case, indent=2)

        pcp_task = Task(
            description=(
                f"Using fixture_patient_chart for patient_id '{patient_id}', review this case:\n{case_json}\n"
                "Produce: problem list, red flags, urgency (routine|urgent|emergent|stat), "
                "and what cardiology/pharmacy should focus on."
            ),
            expected_output="Primary care assessment with urgency and red flags",
            agent=self.primary_care,
        )
        cardio_task = Task(
            description=(
                f"Given the PCP assessment and patient '{patient_id}', perform cardiovascular "
                "risk/ACS assessment. Use the chart tool if needed. State cardiac concerns and recommendations."
            ),
            expected_output="Cardiology assessment and recommendations",
            agent=self.cardiologist,
            context=[pcp_task],
        )
        pharm_task = Task(
            description=(
                f"Review medications for patient '{patient_id}'. Use fixture_patient_chart and "
                "medication_safety_check. Flag interactions, bleed risk, allergy issues, and pharmacy actions."
            ),
            expected_output="Pharmacy safety review with concrete concerns",
            agent=self.pharmacist,
            context=[pcp_task, cardio_task],
        )
        nurse_task = Task(
            description=(
                "Integrate PCP, cardiology, and pharmacy findings into a care plan: "
                "ordered next actions, patient education, follow-up timing, and escalation destination. "
                "End with a JSON block containing keys: urgency, primary_specialty, red_flags, "
                "assessment_summary, recommended_actions, medication_concerns."
            ),
            expected_output="Care plan plus final JSON summary",
            agent=self.nurse,
            context=[pcp_task, cardio_task, pharm_task],
        )

        crew = Crew(
            agents=[self.primary_care, self.cardiologist, self.pharmacist, self.nurse],
            tasks=[pcp_task, cardio_task, pharm_task, nurse_task],
            process=Process.sequential,
            verbose=True,
        )
        result = crew.kickoff()

        task_outputs: list[dict[str, Any]] = []
        raw_chunks: list[str] = []
        tasks_output = getattr(result, "tasks_output", None) or []
        for task_out in tasks_output:
            agent_name = str(getattr(task_out, "agent", "") or "")
            raw = str(getattr(task_out, "raw", None) or getattr(task_out, "exported_output", None) or task_out)
            task_outputs.append({"agent": agent_name, "output": raw})
            raw_chunks.append(f"## {agent_name or 'agent'}\n{raw}")

        final_raw = str(getattr(result, "raw", None) or result)
        if not final_raw.strip() and raw_chunks:
            final_raw = raw_chunks[-1]
        care_plan_text = "\n\n".join(raw_chunks) if raw_chunks else final_raw

        # Prefer nurse JSON if present; otherwise best-effort parse of final raw.
        summary = _extract_summary_json(final_raw)
        if summary is None and raw_chunks:
            summary = _extract_summary_json(raw_chunks[-1])

        return {
            "patient_id": patient_id,
            "framework": "crewai",
            "case": case,
            "care_plan": care_plan_text,
            "result": final_raw,
            "summary": summary,
            "task_outputs": task_outputs,
            "agents": [
                "Primary Care Physician",
                "Cardiologist",
                "Clinical Pharmacist",
                "Nurse Care Coordinator",
            ],
        }


def _extract_summary_json(text: str) -> dict[str, Any] | None:
    """Pull the final JSON care-summary block from nurse output if present."""
    import re

    if not text:
        return None
    candidates = [text.strip()]
    if "```" in text:
        parts = text.split("```")
        for i, part in enumerate(parts):
            if i % 2 == 1:
                candidates.append(re.sub(r"^json\s*", "", part.strip(), flags=re.I))
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidates.append(text[start : end + 1])
    for chunk in candidates:
        try:
            parsed = json.loads(chunk)
            if isinstance(parsed, dict) and (
                "urgency" in parsed or "recommended_actions" in parsed or "assessment_summary" in parsed
            ):
                return parsed
        except json.JSONDecodeError:
            continue
    return None
