# Overmind demo — CrewAI (fixtures only)

Local Docker loop for Overmind’s server-driven optimiser against a real CrewAI
crew (PCP → cardiologist → pharmacist → nurse) on chart fixtures. No lean
assessor, FHIR, UI, Postgres, or Redis.

## Loop

```text
Overmind console
        │
        ▼
healthcare-executioner   ← paste Jobs-tab `overmind optimize`
  git apply under OVERMIND_CWD=/workspace
  shell codegen → HTTP trigger
        │
        ▼
healthcare-crewai (:8090)
  POST /crewai  {"patient_id":"..."}
        │
        ▼
stdout / response["output"] scored (judge-only + must_mention)
```

## Start

```bash
cd overmind_demo
cp .env.example .env   # OPENROUTER_API_KEY or OPENAI_API_KEY
./scripts/up.sh
./scripts/smoke.sh
```

```bash
curl -sf http://localhost:8090/health | jq
curl -sf -X POST http://localhost:8090/crewai \
  -H 'Content-Type: application/json' \
  -d '{"patient_id":"patient-chest-pain"}' | jq
```

## Register in Overmind

| Field | Value |
|-------|--------|
| **entrypoint** | `POST /crewai` |
| **code_trigger** | `Long-running HTTP agent. Trigger with requests/curl to http://healthcare-crewai:8090/crewai (JSON body = datapoint input). Print the response body (or response["output"]) to stdout. Do NOT use Django manage.py shell.` |

Optimizable file: `overmind_demo/crewai_service/crew.py`  
Eval seeds: `.overmind/` (judge-only dataset, `policies.md`, `eval_spec.json`)

Regenerate dataset from fixtures:

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

Use `host.docker.internal` (not `localhost`) for `OVERMIND_API_URL` from inside the container.

## Layout

```text
overmind_demo/
├── crewai_service/     # CrewAI crew + HTTP API
├── fixtures/           # patient charts
├── query_agent.py      # thin POST /crewai helper
├── docker-compose.yml  # healthcare-crewai + executioner
├── scripts/
└── .overmind/          # dataset, policies, eval_spec
```
