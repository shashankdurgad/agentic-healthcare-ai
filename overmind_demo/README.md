# Overmind demo — CrewAI + local HAPI (seeded) + FHIR MCP

Local Docker loop for Overmind’s optimiser against a CrewAI crew
(PCP → cardiologist → pharmacist → nurse). Charts are seeded into HAPI from
`fixtures/patients.json`; agents load them via FHIR MCP tool calls.

## Loop

```text
fixtures/patients.json
        │ seed (PUT fixed IDs)
        ▼
hapi-fhir (:8085→8080)
        ▲
fhir-mcp-server (:8004)
        ▲
healthcare-crewai (:8090)  POST /crewai {"patient_id":"patient-uti"}
        ▲
healthcare-executioner  ← paste Jobs-tab `overmind optimize`
```

## Start

```bash
cd overmind_demo
cp .env.example .env   # OPENROUTER_API_KEY; default model qwen/qwen3.6-35b-a3b
./scripts/up.sh
./scripts/smoke.sh
```

```bash
curl -sf http://localhost:8004/health | jq
curl -sf http://localhost:8090/health | jq
curl -sf -X POST http://localhost:8090/crewai \
  -H 'Content-Type: application/json' \
  -d '{"patient_id":"patient-chest-pain"}' | jq
```

Re-seed only:

```bash
docker compose run --rm fhir-seed
```

## Register in Overmind

| Field | Value |
|-------|--------|
| **entrypoint** | `POST /crewai` |
| **code_trigger** | `Long-running HTTP agent. Trigger with requests/curl to http://healthcare-crewai:8090/crewai (JSON body = datapoint input). Print the response body (or response["output"]) to stdout. Do NOT use Django manage.py shell.` |

Optimizable file: `overmind_demo/crewai_service/crew.py`  
Eval seeds: `eval/` (judge-only; `must_mention` still derived from fixtures)

```bash
python scripts/generate_eval_dataset.py
```

## Executioner

```bash
docker exec -it healthcare-executioner bash
cd /workspace

pip install "overmind>=0.1.53" && \
OVERMIND_CWD=/workspace \
OVERMIND_API_URL=http://host.docker.internal:8000 \
OVERMIND_API_KEY=<project_api_key> \
OVERMIND_PROJECT_ID=<project_id> \
overmind optimize
```

## Layout

```text
overmind_demo/
├── crewai_service/     # CrewAI + FHIR MCP tools
├── fixtures/           # seed source (same patient_* IDs as FHIR)
├── scripts/seed_fhir.py
├── docker-compose.yml  # hapi + mcp + seed + crewai + executioner
└── eval/               # dataset, policies, eval_spec
```

Ports: HAPI `8085` (container `8080`), MCP `8004`, CrewAI `8090`.
