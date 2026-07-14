"""CrewAI healthcare crew using local HAPI via FHIR MCP tool calls."""

from __future__ import annotations

import base64
import json
import os
from typing import Any, Type

import httpx
from crewai import Agent, Crew, Process, Task
from langchain.tools import BaseTool
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

MCP_URL = os.environ.get("FHIR_MCP_URL", "http://fhir-mcp-server:8004").rstrip("/")


def call_mcp_tool(tool_name: str, arguments: dict[str, Any]) -> Any:
    """JSON-RPC tools/call against fhir-mcp-server (POST /)."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }
    # This server's MCP endpoint is POST / (not /mcp).
    with httpx.Client(timeout=60.0) as client:
        resp = client.post(
            f"{MCP_URL}/",
            json=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        resp.raise_for_status()
        body = resp.json()
    if "error" in body:
        raise RuntimeError(f"MCP error: {body['error']}")
    return body.get("result", body)


def _mcp_text(result: Any) -> str:
    if isinstance(result, dict):
        content = result.get("content")
        if isinstance(content, list) and content:
            texts = [c.get("text", "") for c in content if isinstance(c, dict)]
            if texts:
                return "\n".join(t for t in texts if t)
        return json.dumps(result, indent=2, default=str)
    return str(result)


def _as_dict(obj: Any) -> dict[str, Any] | None:
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "serialize"):
        try:
            return obj.serialize()
        except Exception:
            pass
    if hasattr(obj, "dict"):
        try:
            return obj.dict()
        except Exception:
            pass
    return None


def _bundle_entries(result: Any) -> list[dict[str, Any]]:
    """Normalize MCP search payloads (prefer format=fhir Bundles) into resource dicts."""
    if result is None:
        return []
    parsed: Any = result
    if isinstance(result, dict) and "content" in result and "entry" not in result:
        text = _mcp_text(result)
        if text.strip().startswith("{"):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                return []
    if not isinstance(parsed, dict):
        return []
    entries = parsed.get("entry")
    if isinstance(entries, list):
        out: list[dict[str, Any]] = []
        for e in entries:
            if not isinstance(e, dict):
                continue
            resource = e.get("resource", e)
            as_dict = _as_dict(resource)
            if as_dict and as_dict.get("resourceType"):
                out.append(as_dict)
        return out
    as_one = _as_dict(parsed)
    if as_one and as_one.get("resourceType") and as_one.get("resourceType") != "Bundle":
        return [as_one]
    return []


def _search_resources(resource_type: str, patient_id: str) -> list[dict[str, Any]]:
    # format=fhir returns a real Bundle; default MCP format is text-only IDs.
    params = {
        "AllergyIntolerance": ("patient",),
        "MedicationRequest": ("patient",),
        "Condition": ("patient", "subject"),
        "Observation": ("patient", "subject"),
        "DocumentReference": ("patient", "subject"),
    }.get(resource_type, ("patient", "subject"))
    for param_name in params:
        result = call_mcp_tool(
            "search",
            {
                "type": resource_type,
                "searchParam": {param_name: f"Patient/{patient_id}"},
                "format": "fhir",
            },
        )
        entries = _bundle_entries(result)
        if entries:
            return entries
    return []


def _decode_doc_text(doc: dict[str, Any]) -> str:
    for content in doc.get("content") or []:
        att = (content or {}).get("attachment") or {}
        data = att.get("data")
        if data:
            try:
                return base64.b64decode(data).decode("utf-8", errors="replace")
            except Exception:
                continue
        if att.get("title"):
            return str(att.get("title"))
    return doc.get("description") or ""


def fetch_fhir_chart(patient_id: str) -> dict[str, Any]:
    """Compose a chart-shaped payload via MCP tool calls."""
    overview = _mcp_text(
        call_mcp_tool("get_patient_comprehensive_data", {"patient_id": patient_id})
    )
    conditions = _search_resources("Condition", patient_id)
    meds = _search_resources("MedicationRequest", patient_id)
    allergies = _search_resources("AllergyIntolerance", patient_id)
    observations = _search_resources("Observation", patient_id)
    documents = _search_resources("DocumentReference", patient_id)

    history = []
    chief_complaint = ""
    for cond in conditions:
        code = (cond.get("code") or {}).get("text") or ""
        cats = cond.get("category") or []
        is_cc = any("chief" in json.dumps(c).lower() for c in cats) or cond.get("id", "").endswith("-cc")
        if is_cc and code:
            chief_complaint = code
        elif code:
            history.append(code)

    medications = []
    for med in meds:
        text = (med.get("medicationCodeableConcept") or {}).get("text")
        if not text:
            dosages = med.get("dosageInstruction") or []
            text = dosages[0].get("text") if dosages else None
        if text:
            medications.append(text)

    allergy_list = []
    for alg in allergies:
        text = (alg.get("code") or {}).get("text")
        if text:
            allergy_list.append(text)

    vitals: dict[str, Any] = {}
    for obs in observations:
        code_text = ((obs.get("code") or {}).get("text") or "").lower()
        coding = ((obs.get("code") or {}).get("coding") or [{}])[0]
        loinc = coding.get("code", "")
        if loinc == "85354-9" or "blood pressure" in code_text:
            comps = {((c.get("code") or {}).get("coding") or [{}])[0].get("code"): c for c in obs.get("component") or []}
            sys_v = (comps.get("8480-6") or {}).get("valueQuantity", {}).get("value")
            dia_v = (comps.get("8462-4") or {}).get("valueQuantity", {}).get("value")
            if sys_v is not None and dia_v is not None:
                vitals["bp"] = f"{int(sys_v)}/{int(dia_v)}"
            continue
        vq = obs.get("valueQuantity") or {}
        val = vq.get("value")
        if val is None:
            continue
        if loinc == "8867-4" or "heart rate" in code_text:
            vitals["hr"] = val
        elif loinc == "9279-1" or "respiratory" in code_text:
            vitals["rr"] = val
        elif loinc == "2708-6" or "oxygen" in code_text or "spo2" in code_text:
            vitals["spo2"] = val
        elif loinc == "8310-5" or "temperature" in code_text:
            vitals["temp_c"] = val

    narratives = [_decode_doc_text(d) for d in documents]
    narratives = [n for n in narratives if n]
    context = ""
    for n in narratives:
        if n.lower().startswith("chief complaint:"):
            # Prefer DocumentReference complaint if Condition missing
            if not chief_complaint:
                for line in n.splitlines():
                    if line.lower().startswith("chief complaint:"):
                        chief_complaint = line.split(":", 1)[1].strip()
        if "context:" in n.lower():
            for line in n.splitlines():
                if line.lower().startswith("context:"):
                    context = line.split(":", 1)[1].strip()

    return {
        "patient_id": patient_id,
        "mcp_overview": overview,
        "chief_complaint": chief_complaint,
        "history": history,
        "medications": medications,
        "vitals": vitals,
        "allergies": allergy_list,
        "context": context,
        "source": "fhir_mcp",
        "raw_counts": {
            "conditions": len(conditions),
            "medications": len(meds),
            "allergies": len(allergies),
            "observations": len(observations),
            "documents": len(documents),
        },
    }


class PatientIdInput(BaseModel):
    patient_id: str = Field(..., description="FHIR Patient.id (e.g. patient-uti)")


class FHIRPatientChartTool(BaseTool):
    name: str = "fhir_patient_chart"
    description: str = (
        "Retrieve the patient chart from the local FHIR server via MCP "
        "(demographics overview, conditions, medications, vitals, allergies, clinical notes)."
    )
    args_schema: Type[BaseModel] = PatientIdInput

    def _run(self, patient_id: str) -> str:
        try:
            chart = fetch_fhir_chart(patient_id)
            return json.dumps(chart, indent=2)
        except Exception as exc:
            return json.dumps({"error": str(exc), "patient_id": patient_id, "mcp_url": MCP_URL})


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
                    "recommendation": (
                        "Avoid NSAID if possible; gastroprotection; "
                        "urgent GI bleed workup if melena/hypotension"
                    ),
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
    """Sequential CrewAI crew: PCP → Cardiologist → Pharmacist → Nurse (FHIR MCP tools)."""

    def __init__(self) -> None:
        self.llm = build_llm()
        self.chart_tool = FHIRPatientChartTool()
        self.med_tool = MedicationSafetyTool()

        self.primary_care = Agent(
            role="Primary Care Physician",
            goal="Assess the patient comprehensively and identify urgency and red flags",
            backstory=(
                "Experienced primary care physician focused on triage, problem lists, "
                "and coordinating specialists. Always load the chart via fhir_patient_chart."
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
        patient_id = input_data.get("patient_id") or "unknown"
        # Bootstrap chart via MCP so tasks have grounded context even if an agent skips tools.
        try:
            case = fetch_fhir_chart(patient_id)
        except Exception as exc:
            case = {"patient_id": patient_id, "error": str(exc), "source": "fhir_mcp"}

        case_json = json.dumps(case, indent=2)

        pcp_task = Task(
            description=(
                f"Call fhir_patient_chart for patient_id '{patient_id}'. "
                f"Seeded chart snapshot (may be incomplete — prefer the tool):\n{case_json}\n"
                "Produce: problem list, red flags, urgency (routine|urgent|emergent|stat), "
                "and what cardiology/pharmacy should focus on. Do not invent findings."
            ),
            expected_output="Primary care assessment with urgency and red flags",
            agent=self.primary_care,
        )
        cardio_task = Task(
            description=(
                f"Given the PCP assessment and FHIR patient '{patient_id}', perform cardiovascular "
                "risk/ACS assessment. Use fhir_patient_chart if needed. State cardiac concerns and recommendations."
            ),
            expected_output="Cardiology assessment and recommendations",
            agent=self.cardiologist,
            context=[pcp_task],
        )
        pharm_task = Task(
            description=(
                f"Review medications for FHIR patient '{patient_id}'. Use fhir_patient_chart and "
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
            "tools": ["fhir_patient_chart", "medication_safety_check"],
            "fhir_mcp_url": MCP_URL,
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
