#!/usr/bin/env python3
"""Invoke the CrewAI HTTP service (for Overmind eval / local smoke).

Prints response JSON to stdout. Optional --restart of healthcare-crewai.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

DEFAULT_URL = os.environ.get("AGENT_URL", "http://localhost:8090")


def main() -> int:
    parser = argparse.ArgumentParser(description="POST /crewai on healthcare-crewai")
    parser.add_argument("--url", default=DEFAULT_URL, help="CrewAI base URL")
    parser.add_argument("--patient-id", default="patient-uti")
    parser.add_argument("--payload", help="Raw JSON body (overrides --patient-id)")
    parser.add_argument(
        "--restart",
        action="store_true",
        help="docker restart healthcare-crewai before calling",
    )
    args = parser.parse_args()

    if args.restart:
        container = os.environ.get("AGENT_CONTAINER", "healthcare-crewai")
        subprocess.run(["docker", "restart", container], check=False)

    if args.payload:
        body = json.loads(args.payload)
    else:
        body = {"patient_id": args.patient_id}

    req = urllib.request.Request(
        f"{args.url.rstrip('/')}/crewai",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            print(resp.read().decode())
    except urllib.error.HTTPError as exc:
        print(exc.read().decode() or str(exc), file=sys.stderr)
        return 1
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
