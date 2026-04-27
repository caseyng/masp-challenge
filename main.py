#!/usr/bin/env python3
import asyncio
import sys

from exceptions import OrchestratorError
from orchestrator import Orchestrator


def main() -> None:
    if len(sys.argv) < 2:
        print(
            'Usage: python main.py "<audit request>"\n'
            'Example: python main.py "audit this project for secrets and open ports"',
            file=sys.stderr,
        )
        sys.exit(1)

    audit_request = sys.argv[1]
    orchestrator = Orchestrator()

    try:
        asyncio.run(orchestrator.run(audit_request))
    except OrchestratorError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    print("Audit complete. See report.md and audit_trail.jsonl.")
    sys.exit(0)


if __name__ == "__main__":
    main()
