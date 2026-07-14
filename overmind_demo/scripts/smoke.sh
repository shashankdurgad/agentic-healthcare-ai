#!/usr/bin/env bash
set -euo pipefail

HOST="${CREWAI_URL:-http://localhost:8090}"
MCP="${FHIR_MCP_URL:-http://localhost:8004}"
HAPI="${FHIR_BASE_URL:-http://localhost:8085/fhir}"

echo "==> HAPI metadata"
curl -sf "${HAPI}/metadata" >/dev/null
echo "ok"

echo "==> MCP health"
curl -sf "${MCP}/health" | python3 -m json.tool

echo "==> MCP fhir chart tool (get_patient_comprehensive_data)"
python3 - <<'PY'
import json, os, urllib.request
mcp = os.environ.get("FHIR_MCP_URL", "http://localhost:8004").rstrip("/")
payload = {
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "get_patient_comprehensive_data",
    "arguments": {"patient_id": "patient-uti"},
  },
}
req = urllib.request.Request(
  f"{mcp}/",
  data=json.dumps(payload).encode(),
  headers={"Content-Type": "application/json"},
  method="POST",
)
with urllib.request.urlopen(req, timeout=60) as resp:
  body = json.load(resp)
print(json.dumps(body, indent=2)[:2000])
if "error" in body:
  raise SystemExit(1)
PY

echo "==> crewai health"
curl -sf "${HOST}/health" | python3 -m json.tool

run_one() {
  local id="$1"
  echo "==> /crewai ${id}"
  BODY_FILE="$(mktemp)"
  CODE="$(curl -sS -o "${BODY_FILE}" -w '%{http_code}' --max-time 600 -X POST "${HOST}/crewai" \
    -H 'Content-Type: application/json' \
    -d "{\"patient_id\":\"${id}\"}")"
  echo "HTTP ${CODE}"
  python3 -c '
import json, sys
path = sys.argv[1]
with open(path) as f:
    d = json.load(f)
o = d.get("output", d)
if d.get("error"):
    print("ERROR:", d["error"])
    raise SystemExit(1)
case = o.get("case") or {}
print(json.dumps({
    "patient_id": o.get("patient_id"),
    "framework": o.get("framework"),
    "tools": o.get("tools"),
    "case_source": case.get("source"),
    "raw_counts": case.get("raw_counts"),
    "medications": case.get("medications"),
    "vitals": case.get("vitals"),
    "task_count": len(o.get("task_outputs") or []),
    "summary": o.get("summary"),
}, indent=2))
care = o.get("care_plan") or o.get("result") or ""
print("--- care_plan (truncated) ---")
print(care[:2500] + ("..." if len(care) > 2500 else ""))
if case.get("source") != "fhir_mcp":
    raise SystemExit("expected case.source=fhir_mcp")
if case.get("error"):
    raise SystemExit(case["error"])
' "${BODY_FILE}"
  rm -f "${BODY_FILE}"
  [[ "${CODE}" == "200" ]]
}

run_one "patient-uti"

echo "==> ok"
