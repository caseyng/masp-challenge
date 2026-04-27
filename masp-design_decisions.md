MASP — DESIGN DECISIONS CHEATSHEET

PHILOSOPHY
- KISS. No pydantic. Dataclasses only. Plain functions for tools.
- ABC for all agents. One job per class. No shared mutable state.
- Fail closed. Failed agent = explicit failure in report, never silent pass.

ARCHITECTURE
CLI → Orchestrator → Decomposer → [SubTask list]
                  → Registry.get(task_type) per subtask
                  → ThreadPoolExecutor: all agents concurrent (IO-bound = real concurrency)
                  → collect ALL futures → AuditReport → stdout
                  → JSONL audit trail → file (separate from report)

FILE STRUCTURE
main.py           # CLI entry point
orchestrator.py   # Orchestrator class
decomposer.py     # Decomposer class
registry.py       # Registry dict + registration
base_agent.py     # BaseAgent ABC
agents/
  injection.py    # InjectionCheckAgent
  auth.py         # AuthCheckAgent
  xss.py          # XSSCheckAgent
models.py         # SubTask, AgentResult, AuditReport dataclasses
auditor.py        # Auditor (JSONL writer, thread-safe)
config.py         # Config dataclass
tools/
  __init__.py     # plain callable tools, imported by agents

DATACLASSES (no pydantic, __post_init__ validates)
SubTask:      task_type: str, context: str
AgentResult:  task_type, success: bool, content: str|None, failure_mode: str|None, reason: str|None
  invariant: success=True → content set + failure_mode None
             success=False → failure_mode set + content None
             enforce in __post_init__ → raise ValueError on violation
AuditReport:  run_id, audit_request, results: list[AgentResult],
              sufficient: bool, successful_count, failed_count, sufficiency_threshold

BASE AGENT (ABC)
class BaseAgent(ABC):
    name: str                    # unique, class attribute
    _tools: list[callable] = []  # plain functions, defined on subclass
    _system_prompt: str = ""     # defined on subclass

    def execute(self, subtask: SubTask) -> AgentResult:
        # 1. call tools to gather context
        # 2. call LLM with system_prompt + tool results + subtask.context
        # 3. return AgentResult(success=True, content=response)
        # NEVER raises — all failures caught, returned as AgentResult(success=False)

    @abstractmethod
    def name(self) -> str: ...

CONCRETE AGENT (pattern — repeat per domain)
class InjectionCheckAgent(BaseAgent):
    name = "injection_check"
    _system_prompt = "You are a SQL/command injection specialist. Analyse the context and report findings."
    _tools = [check_parameterised_queries, scan_injection_patterns]

# Register at bottom of registry.py:
REGISTRY = {
    "injection_check": InjectionCheckAgent,
    "auth_check":      AuthCheckAgent,
    "xss_check":       XSSCheckAgent,
    "generic_audit":   GenericAuditAgent,  # catch-all for unknown domains
}

TOOLS (plain functions — no decoration)
def scan_injection_patterns(context: str) -> str: ...
def check_parameterised_queries(context: str) -> str: ...
def check_auth_headers(context: str) -> str: ...
# Agent calls these directly inside execute() before LLM call
# Tool failure → catch exception → return AgentResult(success=False, failure_mode="agent_tool_failed")

DECOMPOSER DESIGN DECISION
Option A (KISS — recommended): Fixed registry. Prompt lists valid task_types.
  Prompt: "Valid types: injection_check, auth_check, xss_check, generic_audit.
           Return JSON: [{task_type, context}]. Use generic_audit if unsure."
  → No unmatched types. GenericAuditAgent handles open-ended requests.

Option B (open): Decomposer outputs semantic descriptions. Second step matches to registry.
  → More flexible, more complex. Not worth it in 60 min.

DECISION: Option A. GenericAuditAgent as catch-all eliminates unknown_task_type in practice.

DOES DECOMPOSER NEED LLM?
Option A: Rule-based keyword match → task_type. Fast, no failure surface.
Option B: LLM call → JSON list of SubTasks. Flexible, adds DecomposerError failure mode.
DECISION: LLM-based decomposer. Challenge likely expects it. Prompt for JSON output only.
  On parse failure → DecomposerError → PipelineError → stderr, exit nonzero.

CONCURRENCY
ThreadPoolExecutor(max_workers=4). IO-bound agents (LLM calls) = real concurrent waiting.
Submit all agents before collecting any. Collect ALL futures — never discard.
Unexpected exception from future → catch at collection → AgentResult(success=False, failure_mode="agent_execution_error")

SUFFICIENCY
sufficient = successful_count >= sufficiency_threshold (default: 1)
Evaluated AFTER all futures collected. Never before.
All fail → AuditReport(sufficient=False) — still returned, not PipelineError.
threshold=0 → always sufficient. threshold > agent count → always insufficient. Both valid.

AUDITOR
Thread-safe JSONL writer. Internal threading.Lock(). Append-only.
close() idempotent. log() after close() = no-op (teardown safety).
NOT logged: audit_request content, AgentResult.content, LLM responses — security decision.

FAILURE MODES
decomposer_llm_unavailable    → DecomposerError → PipelineError → stderr + exit nonzero
decomposer_output_unparseable → DecomposerError → PipelineError → stderr + exit nonzero
unknown_task_type             → AgentResult(success=False) — pipeline continues
agent_tool_failed             → AgentResult(success=False) — pipeline continues
agent_llm_unavailable         → AgentResult(success=False) — pipeline continues
agent_execution_error         → AgentResult(success=False) — pipeline continues
audit_write_failed            → log to stderr — pipeline continues
no_agents_spawned             → PipelineError → stderr + exit nonzero

NO RETRY in base implementation. Log failure mode. Orchestrator decides sufficiency.

AUDIT EVENTS (JSONL, always: run_id + event + timestamp_utc + schema_version)
run_started | decompose_complete | agent_started | agent_complete | run_complete | pipeline_error

TEST CASES (minimum 3)
1. Happy path: all agents succeed → AuditReport(sufficient=True)
2. One agent fails, threshold=1, others succeed → AuditReport(sufficient=True), failed agent in results
3. All agents fail → AuditReport(sufficient=False) — NOT PipelineError
4. Decomposer fails → PipelineError, stderr, exit nonzero
5. Unknown task_type → AgentResult(failure_mode="unknown_task_type"), pipeline continues

NON-NEGOTIABLES
- execute() NEVER raises
- All futures collected before sufficiency evaluated
- Agents never share mutable state (each instance per SubTask, discarded after)
- Auditor thread-safe with internal lock
- Audit Request = untrusted string, never eval'd or executed
- AuditReport.results has exactly one entry per spawned agent
- open() with encoding="utf-8" everywhere
- No secrets in logs or audit trail

DECOMPOSER PRIORITY (fixed registry, catch-all last)
TASK_TYPE_PRIORITY = [
    "injection_check",
    "auth_check",
    "xss_check",
    "generic_audit",   # ALWAYS last — catch-all
]
- Decomposer prompt lists types in this order
- If LLM returns generic_audit alongside a specific type for same context → specific wins
- Orchestrator deduplicates by task_type before spawning agents
- GenericAuditAgent fires only when no specific type matched

LLM BOUNDARY (simplified carapex — input/output guard)
Sits between application and every LLM call. Two check points:
  CLI input → [LLMBoundary.check_input] → Decomposer LLM
  SubTask context → [LLMBoundary.check_input] → Agent LLM
  Agent LLM response → [LLMBoundary.check_output] → AgentResult.content

@dataclass
class BoundaryResult:
    safe: bool
    failure_mode: str | None = None  # None if safe=True

class LLMBoundary:
    _INJECTION_PATTERNS = [
        r'\[INST\]', r'<s>', r'### System', r'### Instruction',
        r'ignore previous', r'disregard.*instructions',
    ]
    _OUTPUT_PATTERNS = [
        r'jailbreak', r'DAN mode', r'system prompt:',
    ]

    def check_input(self, text: str) -> BoundaryResult:
        normalised = self._normalise(text)        # strip unicode escapes, HTML entities
        if self._matches(normalised, self._INJECTION_PATTERNS):
            return BoundaryResult(safe=False, failure_mode="boundary_injection_detected")
        return BoundaryResult(safe=True)

    def check_output(self, text: str) -> BoundaryResult:
        if self._matches(text, self._OUTPUT_PATTERNS):
            return BoundaryResult(safe=False, failure_mode="boundary_output_unsafe")
        return BoundaryResult(safe=True)

    def _normalise(self, text: str) -> str: ...   # decode HTML entities, unicode escapes
    def _matches(self, text: str, patterns: list) -> bool: ...  # any re.search match

# On boundary failure → AgentResult(success=False, failure_mode=boundary_result.failure_mode)
# Decomposer boundary failure → DecomposerError → PipelineError

# TODO(carapex): replace LLMBoundary with full carapex if time permits
# Interface is stable — swap is one line per call site
# Full carapex adds: entropy check, language detection, translation, semantic LLM guard
