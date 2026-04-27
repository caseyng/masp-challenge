from __future__ import annotations

from abc import ABC, abstractmethod

from exceptions import SubAgentError
from models import SubAgentResult, ToolOutput


class BaseSubAgent(ABC):
    def __init__(self, agent_id: str, agent_type: str, audit_request: str) -> None:
        self._agent_id = agent_id
        self._agent_type = agent_type
        self._audit_request = audit_request
        self._executed = False

    @abstractmethod
    async def run(self) -> SubAgentResult:
        """Specialist implementation. Subclasses MUST call await super().run() first."""
        if self._executed:
            raise SubAgentError("already_run")
        self._executed = True

    def _graceful_partial(self, reason: str) -> SubAgentResult:
        return SubAgentResult(
            agent_id=self._agent_id,
            agent_type=self._agent_type,  # type: ignore[arg-type]
            status="failed",
            findings=[f"Sub-agent did not complete: {reason}"],
            severity="Info",
            tool_outputs=[],
            error=reason,
        )

    def __repr__(self) -> str:
        return (
            f"BaseSubAgent(agent_id={self._agent_id!r}, "
            f"agent_type={self._agent_type!r}, executed={self._executed})"
        )
