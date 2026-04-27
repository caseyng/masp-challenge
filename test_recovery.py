#!/usr/bin/env python3
"""
Verifies error recovery per challenge.md requirement:
  "simulate or trigger at least one sub-agent failure, prove in the audit trail
   that the orchestrator caught it, logged it, retried or substituted a partial
   result, and the run completed successfully."

Runs without a live API key by patching LLMClient and one tool.
"""
import asyncio
import json
import os
import sys
import tempfile
import unittest.mock as mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from exceptions import ToolError
from orchestrator import Orchestrator


FAKE_DECOMPOSE = '["secrets", "ports"]'
FAKE_REASONING = "Findings look risky.\nSEVERITY: High"
FAKE_SYNTHESIS = "Executive summary: critical findings detected. Recommend immediate remediation."

_llm_call_count = 0


def fake_llm_call(self, system: str, user: str) -> str:
    global _llm_call_count
    _llm_call_count += 1
    if "orchestrator" in system.lower() or "decompose" in system.lower() or "closed list" in system:
        return FAKE_DECOMPOSE
    if "synthesising" in system.lower() or "synthesise" in system.lower() or "audit lead" in system.lower():
        return FAKE_SYNTHESIS
    return FAKE_REASONING


_scan_secrets_call_count = 0


def flaky_scan_filesystem_for_secrets(path: str):
    """Raises an unhandled RuntimeError on first call so the Orchestrator triggers retry.
    Sub-agents only catch ToolError/LLMError; a bare RuntimeError propagates up to _run_with_recovery.
    """
    global _scan_secrets_call_count
    _scan_secrets_call_count += 1
    if _scan_secrets_call_count == 1:
        raise RuntimeError("simulated unexpected failure (first attempt) — not a ToolError")
    return [{"file": "fixtures/.env.example", "line_number": 3, "pattern_category": "api_key_assignment"}]


def run_test():
    global _llm_call_count, _scan_secrets_call_count
    _llm_call_count = 0
    _scan_secrets_call_count = 0

    with tempfile.TemporaryDirectory() as tmpdir:
        orig_dir = os.getcwd()
        os.chdir(tmpdir)
        try:
            os.environ["ANTHROPIC_API_KEY"] = "sk-test-fake-key-for-recovery-test"

            with (
                mock.patch("llm_client.LLMClient.call", fake_llm_call),
                mock.patch("agents.secrets.scan_filesystem_for_secrets", flaky_scan_filesystem_for_secrets),
            ):
                orchestrator = Orchestrator()
                asyncio.run(orchestrator.run("audit this project for secrets and open ports"))

            assert Path("report.md").exists(), "report.md not written"
            assert Path("audit_trail.jsonl").exists(), "audit_trail.jsonl not written"

            trail = [json.loads(line) for line in Path("audit_trail.jsonl").read_text(encoding="utf-8").splitlines()]
            event_types = [e["event_type"] for e in trail]

            print("\nAudit trail events:")
            for entry in trail:
                print(f"  {entry['ts']}  {entry['event_type']:<18}  {entry.get('agent_type') or '':<10}  {entry['payload']}")

            assert "run_start" in event_types, "missing run_start"
            assert "decomposition" in event_types, "missing decomposition"
            assert "agent_retry" in event_types, "FAIL: no agent_retry — recovery not triggered"
            assert "agent_end" in event_types, "missing agent_end"
            assert "synthesis" in event_types, "missing synthesis"
            assert "run_end" in event_types, "missing run_end"

            run_end = next(e for e in trail if e["event_type"] == "run_end")
            assert run_end["payload"]["exit_code"] == 0, f"exit_code should be 0, got {run_end['payload']['exit_code']}"

            retry_entries = [e for e in trail if e["event_type"] == "agent_retry"]
            print(f"\nRecovery events captured: {len(retry_entries)} agent_retry")
            for r in retry_entries:
                print(f"  agent_type={r['agent_type']}  reason={r['payload']['reason']!r}")

            assert _scan_secrets_call_count == 2, f"Expected 2 scan calls (fail+retry), got {_scan_secrets_call_count}"

            report = Path("report.md").read_text(encoding="utf-8")
            assert "# Security Audit Report" in report
            assert "## Executive Summary" in report
            assert "## Audit Metadata" in report

            print("\n✓ All assertions passed")
            print(f"  LLM calls made:        {_llm_call_count}")
            print(f"  Tool retry triggered:  yes (scan_secrets called {_scan_secrets_call_count}×)")
            print(f"  run completed:         exit_code=0")
            print(f"  report.md sections:    present")
            print(f"  audit_trail entries:   {len(trail)}")

        finally:
            os.chdir(orig_dir)
            os.environ.pop("ANTHROPIC_API_KEY", None)


if __name__ == "__main__":
    run_test()
