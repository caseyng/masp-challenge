from __future__ import annotations

import asyncio

from agents.base import BaseSubAgent
from exceptions import LLMError, ToolError
from llm_client import LLMClient
from models import SubAgentResult, ToolOutput
from tools import probe_local_ports

PORTS_TO_PROBE = [22, 80, 443, 3000, 3306, 5432, 5672, 6379, 8080, 8443, 8888, 27017]

SYSTEM_PROMPT = """You are a security analyst reviewing open network ports on a local system.

You will receive a list of open TCP ports and their likely services.

Your task:
1. Assess the security risk: Critical, High, Medium, Low, or Info.
   - Critical: database ports (3306, 5432, 27017) exposed on localhost without expected service
   - High: remote access (22), message brokers (5672, 6379) open unexpectedly
   - Medium: web servers (80, 8080, 3000) or dev tools (8888) open
   - Low: HTTPS (443, 8443) open — expected but worth noting
   - Info: no open ports found
2. List findings as bullet points naming the port, service, and risk.
3. End with: SEVERITY: <label>

Be concise."""


def _parse_response(text: str) -> tuple[list[str], str]:
    lines = [l for l in text.strip().splitlines() if l.strip()]
    severity = "Low"
    findings = []
    for line in reversed(lines):
        if line.strip().upper().startswith("SEVERITY:"):
            parts = line.split(":", 1)
            if len(parts) == 2:
                candidate = parts[1].strip().capitalize()
                if candidate in ("Critical", "High", "Medium", "Low", "Info"):
                    severity = candidate
            break
    for line in lines:
        if line.strip().upper().startswith("SEVERITY:"):
            break
        if line.strip():
            findings.append(line.strip())
    return findings, severity


class PortsSubAgent(BaseSubAgent):
    async def run(self) -> SubAgentResult:
        await super().run()
        return await self._execute()

    async def _execute(self) -> SubAgentResult:
        tool_outputs: list[ToolOutput] = []
        port_results: list[dict] = []

        try:
            port_results = await asyncio.to_thread(probe_local_ports, PORTS_TO_PROBE)
            open_ports = [r for r in port_results if r["status"] == "open"]
            open_list = [str(r["port"]) for r in open_ports]
            tool_outputs.append(ToolOutput(
                tool_name="probe_local_ports",
                status="ok",
                summary=f"{len(open_ports)} open ports found: {open_list}",
            ))
        except ToolError as exc:
            tool_outputs.append(ToolOutput(
                tool_name="probe_local_ports",
                status="error",
                summary=str(exc),
            ))
            port_results = []

        open_ports = [r for r in port_results if r["status"] == "open"]

        if open_ports:
            lines = [f"- Port {r['port']} ({r['service_hint']})" for r in open_ports]
            user_msg = (
                f"Request: {self._audit_request}\n\n"
                f"Open ports found:\n" + "\n".join(lines)
            )
        else:
            user_msg = f"Request: {self._audit_request}\n\nNo open ports found on localhost."

        try:
            response = LLMClient().call(system=SYSTEM_PROMPT, user=user_msg)
            findings, severity = _parse_response(response)
            status = "complete"
        except LLMError:
            findings = [f"Port {r['port']} ({r['service_hint']}) is open" for r in open_ports] or ["No open ports found."]
            severity = "Low"
            status = "partial"

        return SubAgentResult(
            agent_id=self._agent_id,
            agent_type="ports",
            status=status,
            findings=findings,
            severity=severity,  # type: ignore[arg-type]
            tool_outputs=tool_outputs,
            error=None if status == "complete" else "LLM call failed",
        )
