from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class ToolOutput:
    tool_name: str
    status: Literal["ok", "error"]
    summary: str

    def __repr__(self) -> str:
        return f"ToolOutput(tool={self.tool_name!r}, status={self.status!r})"


@dataclass
class SubAgentResult:
    agent_id: str
    agent_type: Literal["secrets", "ports", "env", "config"]
    status: Literal["complete", "partial", "failed"]
    findings: list[str] = field(default_factory=list)
    severity: Literal["Critical", "High", "Medium", "Low", "Info"] = "Info"
    tool_outputs: list[ToolOutput] = field(default_factory=list)
    error: str | None = None

    def __repr__(self) -> str:
        return (
            f"SubAgentResult(agent_type={self.agent_type!r}, "
            f"status={self.status!r}, severity={self.severity!r}, "
            f"findings={len(self.findings)})"
        )


@dataclass
class AuditTrailEntry:
    ts: str
    event_type: str
    agent_id: str | None
    agent_type: str | None
    payload: dict


def to_jsonl_line(entry: AuditTrailEntry) -> str:
    return json.dumps(
        {
            "ts": entry.ts,
            "event_type": entry.event_type,
            "agent_id": entry.agent_id,
            "agent_type": entry.agent_type,
            "payload": entry.payload,
        },
        ensure_ascii=False,
    )
