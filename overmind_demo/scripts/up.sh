#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"

if [[ ! -f .env && -f .env.example ]]; then
  cp .env.example .env
  echo "Created .env from .env.example — fill in keys before optimizing."
fi

if [[ -z "${OPENAI_API_KEY:-}${OPENROUTER_API_KEY:-}" ]]; then
  if [[ -f .env ]]; then
    set -a && source .env && set +a
  fi
fi

if [[ -z "${OPENAI_API_KEY:-}${OPENROUTER_API_KEY:-}" ]]; then
  echo "Set OPENROUTER_API_KEY (or OPENAI_API_KEY) in overmind_demo/.env" >&2
  exit 1
fi

docker compose up -d --build
echo "Waiting for HAPI / MCP / CrewAI..."
for _ in $(seq 1 90); do
  if curl -sf http://localhost:8085/fhir/metadata >/dev/null \
    && curl -sf http://localhost:8004/health >/dev/null \
    && curl -sf http://localhost:8090/health >/dev/null; then
    echo "==> HAPI metadata ok"
    echo "==> MCP health"
    curl -sf http://localhost:8004/health | python3 -m json.tool || true
    echo "==> CrewAI health"
    curl -sf http://localhost:8090/health | python3 -m json.tool
    echo
    echo "HAPI:         http://localhost:8085/fhir"
    echo "FHIR MCP:     http://localhost:8004"
    echo "CrewAI:       http://localhost:8090"
    echo "Executioner:  docker exec -it healthcare-executioner bash"
    echo "Smoke:        ./scripts/smoke.sh"
    exit 0
  fi
  sleep 3
done

echo "Services failed to become healthy" >&2
docker compose ps
docker compose logs --tail=80
exit 1
