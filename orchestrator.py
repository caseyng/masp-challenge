from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from datetime import datetime, timezone

from agents.config import ConfigSubAgent
from agents.env import EnvSubAgent
from agents.ports import PortsSubAgent
from agents.secrets import SecretsSubAgent
from exceptions import LLMError, OrchestratorError
from llm_client import LLMClient
from models import AuditTrailEntry, SubAgentResult, ToolOutput
from trail_writer import AuditTrailWriter

AGENT_REGISTRY = {
    "secrets": SecretsSubAgent,
    "ports": PortsSubAgent,
    "env": EnvSubAgent,
    "config": ConfigSubAgent,
}

VALID_TYPES = frozenset(AGENT_REGISTRY.keys())

DECOMPOSE_SYSTEM = """You are a security audit orchestrator. Given a security audit request,
select the most relevant specialist agents to run from this closed list:
- secrets: scan filesystem for committed secrets and API keys
- ports: probe localhost for exposed network services
- env: inspect environment variables for sensitive names
- config: scan configuration files for insecure settings

Respond with a JSON array of agent type strings, e.g.: ["secrets", "ports", "env"]
Select 2 to 4 agents. Only use types from the list above. No explanation needed."""

SYNTHESISE_SYSTEM = """You are a security audit lead synthesising findings from specialist agents.

You will receive structured findings from multiple security sub-agents. Each entry includes
the agent type, completion status, severity rating, and key findings.

Write an executive summary (2-3 paragraphs) that:
1. States the overall security posture and most critical concerns.
2. Highlights the top 3 actionable recommendations.
3. Notes any agents that did not complete and what that means for coverage.

Be direct and actionable. Address a technical security lead."""


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class Orchestrator:
    def __init__(self) -> None:
        self._executed = False

    async def run(self, audit_request: str) -> None:
        if self._executed:
            raise OrchestratorError("double_run")
        self._executed = True

        api_key_present = bool(
            os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY")
        )
        request_valid = bool(
            audit_request and audit_request.strip() and len(audit_request) <= 2000
        )

        if not api_key_present:
            raise OrchestratorError("No API key set (ANTHROPIC_API_KEY or OPENAI_API_KEY required)")
        if not request_valid:
            raise OrchestratorError("Invalid audit_request: must be 1-2000 non-whitespace characters")

        writer = AuditTrailWriter()
        try:
            writer.open("audit_trail.jsonl")
        except OrchestratorError:
            raise

        start_time = time.time()
        timeout_secs = float(os.environ.get("MASP_TIMEOUT_SECS", "45"))
        _exit_code = 0

        try:
            writer.append(AuditTrailEntry(
                ts=now_utc(),
                event_type="run_start",
                agent_id=None,
                agent_type=None,
                payload={"request": audit_request},
            ))

            # §17: LLM_CALL_FAILURE on decompose raises OrchestratorError
            selected_types = await self._decompose(audit_request, writer)

            writer.append(AuditTrailEntry(
                ts=now_utc(),
                event_type="decomposition",
                agent_id=None,
                agent_type=None,
                payload={"subtasks": selected_types},
            ))

            agents = []
            for agent_type in selected_types:
                agent_id = str(uuid.uuid4())
                agent = AGENT_REGISTRY[agent_type](agent_id, agent_type, audit_request)
                agents.append(agent)
                writer.append(AuditTrailEntry(
                    ts=now_utc(),
                    event_type="agent_start",
                    agent_id=agent_id,
                    agent_type=agent_type,
                    payload={},
                ))

            results: list[SubAgentResult] = await asyncio.gather(
                *[self._run_with_recovery(agent, writer, timeout_secs) for agent in agents]
            )

            for result in results:
                for tool_output in result.tool_outputs:
                    writer.append(AuditTrailEntry(
                        ts=now_utc(),
                        event_type="tool_call",
                        agent_id=result.agent_id,
                        agent_type=result.agent_type,
                        payload={
                            "tool_name": tool_output.tool_name,
                            "status": tool_output.status,
                            "summary": tool_output.summary,
                        },
                    ))

                # §4: llm_call per LLM call; purpose must be "reasoning"|"decompose"|"synthesise"
                writer.append(AuditTrailEntry(
                    ts=now_utc(),
                    event_type="llm_call",
                    agent_id=result.agent_id,
                    agent_type=result.agent_type,
                    payload={
                        "purpose": "reasoning",
                        "status": "ok" if result.status != "failed" else "error",
                    },
                ))

            executive_summary = await self._synthesise(audit_request, results, writer)

            report_lines = [
                "# Security Audit Report",
                "",
                f"**Request:** {audit_request}",
                "",
                "## Executive Summary",
                "",
                executive_summary,
                "",
            ]

            for result in results:
                report_lines.append(f"## {result.agent_type.capitalize()} Findings")
                report_lines.append("")
                report_lines.append(f"**Severity:** {result.severity}")
                report_lines.append(f"**Status:** {result.status}")
                report_lines.append("")
                for finding in result.findings:
                    report_lines.append(f"- {finding}")
                report_lines.append("")

            duration = time.time() - start_time
            n_failed = sum(1 for r in results if r.status == "failed")

            report_lines.extend([
                "## Audit Metadata",
                "",
                f"- **Total duration:** {duration:.1f}s",
                f"- **Sub-agents run:** {len(results)}",
                f"- **Sub-agents failed:** {n_failed}",
                f"- **Timestamp:** {now_utc()}",
            ])

            try:
                with open("report.md", "w", encoding="utf-8") as f:
                    f.write("\n".join(report_lines) + "\n")
            except OSError as exc:
                _exit_code = 1
                raise OrchestratorError(f"Cannot write report.md: {exc}") from exc

        except OrchestratorError:
            _exit_code = 1
            raise
        finally:
            writer.append(AuditTrailEntry(
                ts=now_utc(),
                event_type="run_end",
                agent_id=None,
                agent_type=None,
                payload={
                    "duration_seconds": round(time.time() - start_time, 2),
                    "exit_code": _exit_code,
                },
            ))
            writer.close()

    async def _decompose(self, audit_request: str, writer: AuditTrailWriter) -> list[str]:
        # §17: LLM_CALL_FAILURE on decompose → raise OrchestratorError
        try:
            response = LLMClient().call(system=DECOMPOSE_SYSTEM, user=audit_request)
        except LLMError as exc:
            writer.append(AuditTrailEntry(
                ts=now_utc(),
                event_type="llm_call",
                agent_id=None,
                agent_type=None,
                payload={"purpose": "decompose", "status": "error"},
            ))
            raise OrchestratorError(f"LLM decomposition failed: {exc}") from exc

        writer.append(AuditTrailEntry(
            ts=now_utc(),
            event_type="llm_call",
            agent_id=None,
            agent_type=None,
            payload={"purpose": "decompose", "status": "ok"},
        ))

        # §7 DECOMPOSITION_OUT_OF_BOUNDS: clamp silently; unknown types dropped
        try:
            raw = json.loads(response.strip())
            if not isinstance(raw, list):
                raise ValueError("not a list")
            selected = [t for t in raw if t in VALID_TYPES]
        except Exception:
            selected = []

        if len(selected) < 2:
            selected = list(VALID_TYPES)
        elif len(selected) > 4:
            selected = selected[:4]

        return selected

    async def _run_with_recovery(
        self, agent, writer: AuditTrailWriter, timeout_secs: float
    ) -> SubAgentResult:
        agent_type = agent._agent_type
        agent_id = agent._agent_id
        audit_request = agent._audit_request

        try:
            result = await asyncio.wait_for(agent.run(), timeout=timeout_secs)
            # §4: agent_end payload must include severity
            writer.append(AuditTrailEntry(
                ts=now_utc(),
                event_type="agent_end",
                agent_id=agent_id,
                agent_type=agent_type,
                payload={"status": result.status, "severity": result.severity},
            ))
            return result
        except Exception as first_exc:
            reason = str(first_exc)
            writer.append(AuditTrailEntry(
                ts=now_utc(),
                event_type="agent_retry",
                agent_id=agent_id,
                agent_type=agent_type,
                payload={"reason": reason},
            ))

            retry_agent = AGENT_REGISTRY[agent_type](agent_id, agent_type, audit_request)
            try:
                result = await asyncio.wait_for(retry_agent.run(), timeout=timeout_secs)
                writer.append(AuditTrailEntry(
                    ts=now_utc(),
                    event_type="agent_end",
                    agent_id=agent_id,
                    agent_type=agent_type,
                    payload={"status": result.status, "severity": result.severity},
                ))
                return result
            except Exception as second_exc:
                recovery_reason = str(second_exc)
                writer.append(AuditTrailEntry(
                    ts=now_utc(),
                    event_type="agent_recovery",
                    agent_id=agent_id,
                    agent_type=agent_type,
                    payload={"reason": recovery_reason},
                ))
                return agent._graceful_partial(recovery_reason)

    async def _synthesise(
        self, audit_request: str, results: list[SubAgentResult], writer: AuditTrailWriter
    ) -> str:
        agent_sections = []
        for r in results:
            bullets = "\n".join(f"  - {f}" for f in r.findings)
            agent_sections.append(
                f"## {r.agent_type} ({r.status}, severity={r.severity})\n{bullets}"
            )

        user_msg = (
            f"Audit request: {audit_request}\n\n"
            f"Agent findings:\n" + "\n\n".join(agent_sections)
        )

        try:
            summary = LLMClient().call(system=SYNTHESISE_SYSTEM, user=user_msg)
            # §4/§18: llm_call entry + synthesis entry for synthesis LLM call
            writer.append(AuditTrailEntry(
                ts=now_utc(),
                event_type="llm_call",
                agent_id=None,
                agent_type=None,
                payload={"purpose": "synthesise", "status": "ok"},
            ))
            writer.append(AuditTrailEntry(
                ts=now_utc(),
                event_type="synthesis",
                agent_id=None,
                agent_type=None,
                payload={"status": "ok"},
            ))
            return summary
        except LLMError:
            writer.append(AuditTrailEntry(
                ts=now_utc(),
                event_type="llm_call",
                agent_id=None,
                agent_type=None,
                payload={"purpose": "synthesise", "status": "error"},
            ))
            writer.append(AuditTrailEntry(
                ts=now_utc(),
                event_type="synthesis",
                agent_id=None,
                agent_type=None,
                payload={"status": "error"},
            ))
            return "Synthesis unavailable — LLM call failed. See individual agent sections for findings."
