#!/usr/bin/env bash
set -euo pipefail

HOST="${CREWAI_URL:-http://localhost:8090}"

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
print(json.dumps({
    "patient_id": o.get("patient_id"),
    "framework": o.get("framework"),
    "agents": o.get("agents"),
    "summary": o.get("summary"),
    "task_count": len(o.get("task_outputs") or []),
}, indent=2))
care = o.get("care_plan") or o.get("result") or ""
print("--- care_plan (truncated) ---")
print(care[:2500] + ("..." if len(care) > 2500 else ""))
' "${BODY_FILE}"
  rm -f "${BODY_FILE}"
  [[ "${CODE}" == "200" ]]
}

run_one "patient-uti"

echo "==> ok"
