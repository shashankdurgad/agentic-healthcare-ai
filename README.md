# Agentic Healthcare AI — Overmind demo

This repo is trimmed to the **Overmind optimizer demo** only.

## What’s here

| Path | Purpose |
|------|---------|
| [`overmind_demo/`](overmind_demo/) | CrewAI crew, Docker Compose, fixtures, eval dataset |
| [`fhir_mcp_server/`](fhir_mcp_server/) | FHIR MCP server used by the demo (HAPI-backed) |

## Quick start

```bash
cd overmind_demo
cp .env.example .env   # set OPENROUTER_API_KEY (and Overmind keys if tracing/optimize)
./scripts/up.sh
./scripts/smoke.sh
```

Full details: [`overmind_demo/README.md`](overmind_demo/README.md)

## License

See [LICENSE](LICENSE).
