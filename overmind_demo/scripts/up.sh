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
echo "Waiting for CrewAI health..."
for _ in $(seq 1 60); do
  if curl -sf http://localhost:8090/health >/dev/null; then
    curl -sf http://localhost:8090/health | python3 -m json.tool
    echo
    echo "CrewAI:       http://localhost:8090"
    echo "Executioner:  docker exec -it healthcare-executioner bash"
    echo "Smoke:        ./scripts/smoke.sh"
    echo "Then paste Jobs-tab: pip install 'overmind>=0.1.53' && OVERMIND_CWD=/workspace ... overmind optimize"
    exit 0
  fi
  sleep 2
done

echo "CrewAI failed to become healthy" >&2
docker compose logs --tail=80
exit 1
