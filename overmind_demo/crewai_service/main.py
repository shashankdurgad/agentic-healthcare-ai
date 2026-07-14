#!/usr/bin/env python3
"""HTTP API for CrewAI healthcare crew (FHIR via MCP).

  GET  /health
  POST /crewai   {"patient_id": "..."} -> crew result
"""

from __future__ import annotations

import json
import logging
import os
import sys
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEMO_ROOT = ROOT.parent
for path in (str(ROOT), str(DEMO_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

PORT = int(os.getenv("CREWAI_PORT", os.getenv("AGENT_PORT", "8090")))

_crew = None


def get_crew():
    global _crew
    if _crew is None:
        from crew import FixtureHealthcareCrew

        _crew = FixtureHealthcareCrew()
    return _crew


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        log.info("%s - %s", self.address_string(), fmt % args)

    def _send_json(self, code: int, body: dict) -> None:
        data = json.dumps(body, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.split("?", 1)[0] == "/health":
            self._send_json(
                200,
                {
                    "status": "ok",
                    "service": "healthcare-crewai",
                    "framework": "crewai",
                    "fhir_mcp": True,
                    "fhir_mcp_url": os.environ.get("FHIR_MCP_URL", ""),
                    "openai_key_set": bool(
                        os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY")
                    ),
                    "model": os.environ.get("OVERMIND_DEMO_MODEL", "openai/gpt-4o-mini"),
                },
            )
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path.split("?", 1)[0] != "/crewai":
            self._send_json(404, {"error": "not found"})
            return

        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            self._send_json(400, {"error": "invalid JSON"})
            return

        if not isinstance(payload, dict) or not (
            payload.get("patient_id") or payload.get("chief_complaint")
        ):
            self._send_json(400, {"error": "patient_id or chief_complaint required"})
            return

        log.info("CrewAI run: %s", payload.get("patient_id") or payload.get("chief_complaint"))
        try:
            output = get_crew().run(payload)
            self._send_json(200, {"output": output})
        except Exception as exc:
            log.error("CrewAI error: %s", traceback.format_exc())
            self._send_json(500, {"error": str(exc)})


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    log.info("CrewAI service on port %d (POST /crewai, GET /health)", PORT)
    server.serve_forever()
