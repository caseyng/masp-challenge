class MASPError(Exception):
    """Base exception for all MASP errors."""


class OrchestratorError(MASPError):
    """Raised by Orchestrator for fatal run failures."""


class SubAgentError(MASPError):
    """Raised internally by sub-agents; never propagates past Orchestrator."""


class ToolError(MASPError):
    """Raised by tool functions; never propagates past sub-agents."""


class LLMError(MASPError):
    """Raised by LLMClient; never propagates past the calling component."""
