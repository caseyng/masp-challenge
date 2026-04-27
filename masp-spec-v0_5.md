# Multi-Agent Security Audit Pipeline — Specification Contract

**Version:** 0.4
**Status:** Implementation Readiness — READY
**Gap List:** 0 blocking, 7 non-blocking (GAP-03, GAP-04, GAP-06, GAP-07, GAP-11, GAP-12, GAP-13)
**Verification Currency:** CURRENT
**Date:** 2026-04-26
**Changes from v0.3:** Added Config and AgentConfig data contracts to §4. Added Configurator component contract to §5. Added Config and Configurator lifecycle to §6. Added `config_agent_keyset_mismatch` failure mode to §7. Added Config slicing and Configurator placement constraints to §2b. Explicit LLM reachability assumption and trade-off rationale added to §22.

---

## §1 Purpose and Scope

This system accepts a natural language security audit request from a human caller via CLI, decomposes it into typed subtasks, executes each subtask concurrently in a specialised sub-agent with its own tools, aggregates the results, and produces a structured audit report. Every operation is recorded in an append-only audit trail.

The system is the execution engine for security audit requests. It is not an analysis framework — it does not decide what constitutes a vulnerability. Each sub-agent makes that determination for its own domain.

**Out of scope:**

- Remediation. The system reports findings; it does not fix them.
- Authentication and access control. The CLI accepts any input without authentication.
- Persistent audit state across runs. Each invocation is independent.
- Streaming output. The report is produced once, after all agents complete.
- Recursive sub-agent spawning. Sub-agents do not spawn further agents.

**Design principles:**

- Fail closed. If a component cannot complete evaluation, the result is marked failed — not passed. The report always reflects what was and was not evaluated.
- Illegal states are unrepresentable. Every result dataclass enforces its own invariants at construction. A result that violates its invariant cannot be constructed.
- One job per component. Each agent, checker, and tool performs exactly one function. Collapsing responsibilities is a defect.
- Sufficiency is explicit. The orchestrator applies a declared sufficiency rule to determine whether a partial result is returnable. The rule is not implicit.
- Audit trail is append-only. No component may modify or delete prior audit records.

**System-level invariants:**

- The pipeline is a total function: every invocation produces exactly one terminal outcome — either a valid `AuditReport` or a `PipelineError`. No partial or undefined states are observable to the caller.

- Each `SubTask` produced by the `Decomposer` results in exactly one `AgentResult` in the final `AuditReport`, unless the pipeline terminates with `PipelineError` before agent execution begins.

- The audit trail is prefix-complete: at any point of failure or termination, all events that occurred before the failure are durably recorded and remain readable.

---

## §2 Concepts and Vocabulary

**Audit Request** — the raw natural language string supplied by the human caller describing what to audit.

**SubTask** — a typed unit of work produced by the Decomposer. Carries a task type and the context extracted from the Audit Request relevant to that type.

**Agent** — a specialised component that executes one SubTask. Each Agent type handles one SubTask type. An Agent owns its own tools.

**Tool** — a plain callable the Agent may invoke during execution. Tools are owned by the Agent class, not assigned at runtime.

**AgentResult** — the typed return value of one Agent execution. Carries success status, content or failure mode, and the originating task type.

**AuditReport** — the structured output of one pipeline run. Contains all AgentResults, a sufficiency verdict, and the run identifier.

**Orchestrator** — the component that owns the pipeline. Receives the Audit Request, drives the Decomposer, spawns and executes agents concurrently, aggregates results, determines sufficiency, and emits the AuditReport.

**Decomposer** — the component that reads the Audit Request and produces a list of SubTasks.

**Registry** — the mapping from SubTask type string to Agent class. Static at runtime.

**Sufficiency** — the property of an AuditReport that determines whether it can be returned to the caller. An AuditReport is sufficient if the number of successful AgentResults meets or exceeds the sufficiency threshold.

**Sufficiency threshold** — the minimum number of successful AgentResults required for the report to be marked sufficient. Configured at startup.

**Audit trail** — the append-only JSONL file recording every system event for a run, linked by run identifier.

**Run identifier** — a short opaque string generated per pipeline invocation. Links all audit records for that invocation.

**Failure mode** — a machine-readable string identifying why an AgentResult or pipeline operation failed. Every failure has exactly one failure mode.

**LLMBoundary** — the security boundary component that wraps every LLM call. Normalises input and checks for injection patterns before the LLM sees it. Checks output for compromise indicators before the result reaches the caller. Sits between the application and the LLM at both call sites: Decomposer and every Agent.

**BoundaryResult** — the typed return value of one LLMBoundary check. Carries a safe flag and, on failure, a failure mode string.

**Named exception types** — the following custom exception types are used throughout this spec. Python builtins (`ValueError`, `RuntimeError`) are not listed here; their standard semantics apply.

- `PipelineError` — raised by the Orchestrator when the pipeline cannot run (Decomposer failure, no agents spawned). Propagates to the CLI entry point.
- `DecomposerError` — raised by the Decomposer on LLM failure, unparseable output, or boundary violation on input. Caught by the Orchestrator.
- `RegistryKeyError` — raised by the Registry when a `task_type` is not registered. Caught by the Orchestrator.
- `AuditWriteError` — raised by the Auditor when a record cannot be written. Caught by the Orchestrator.
- `ConfigurationError` — raised during construction when required configuration is missing or invalid.
- `BoundaryError` — raised by LLMBoundary when input or output fails a safety check. Caught by the component that owns the LLM call (Decomposer or Agent).

---

## §2b Architectural Constraints

These constraints define structural decisions that, if violated, produce wrong implementation. They are not implementor choices.

**Class hierarchy:**

```
LLMCaller (mixin)
├── Decomposer(LLMCaller)     — plain class. decompose() only. NEVER extends BaseAgent.
└── BaseAgent(ABC, LLMCaller) — abstract. execute() contract. registered and spawned.
      ├── InjectionCheckAgent
      ├── AuthCheckAgent
      ├── XSSCheckAgent
      └── GenericAuditAgent   — catch-all. MUST be last in priority order.
```

**LLMCaller mixin** — owns the LLM provider reference and the `_call_llm()` method. Decomposer and BaseAgent both inherit it. LLMCaller is never registered, never spawned, never an agent. It exists to share LLM infrastructure without sharing the agent execution contract.

**Decomposer MUST NOT extend BaseAgent.** Their interfaces are incompatible: Decomposer accepts a raw string and returns `list[SubTask]`; BaseAgent accepts a SubTask and returns `AgentResult`. Forcing Decomposer into BaseAgent violates the BaseAgent contract.

**Registry priority order** — task types MUST be declared and evaluated in specificity order. `generic_audit` MUST be last. The Decomposer prompt MUST list types in this order. If the Decomposer returns `generic_audit` alongside a specific type for the same context, the specific type wins.

**Deduplication** — the Orchestrator MUST deduplicate SubTasks by `task_type` before spawning agents. One agent per unique `task_type` per run. Duplicate task types from the Decomposer are discarded after the first.

**LLMBoundary placement** — LLMBoundary MUST be called at exactly two points:
1. In Decomposer: `check_input(audit_request)` before the LLM call; `check_output(response)` after.
2. In every Agent `execute()`: `check_input(subtask.context)` before the LLM call; `check_output(response)` after.

LLMBoundary is not injected — it is constructed internally by the component that owns the LLM call. It is stateless. It is not registered. It is not an agent.

**Config slicing** — `Orchestrator` MUST NOT pass the full `Config` to any Agent or Decomposer. Each component receives only its slice: the typed `AgentConfig` subclass for Agents; `decomposer_temperature` and the `llm_*` fields for Decomposer. This is not a convenience — it is an encapsulation constraint. An Agent that holds a reference to the full `Config` has access to fields it does not own.

**Configurator is not injected** — `Configurator` is called once at the CLI entry point and discarded. It is never passed to `Orchestrator`, never stored, never registered. The `Config` it produces is the only artefact that persists.

**TODO — full carapex integration:** LLMBoundary is a simplified boundary. Full carapex adds entropy checking, language detection, translation, and a semantic LLM guard. The interface is stable — replacing LLMBoundary with carapex requires no changes to call sites. This is deferred; implement LLMBoundary first.

---

## §3 System Boundary

**Input:** A single non-empty UTF-8 string supplied by the human caller via CLI stdin or positional argument. The string is treated as untrusted natural language. Null input is rejected before Decomposer runs. Empty string is rejected before Decomposer runs.

**Output:** One of:

- *AuditReport* — produced when the pipeline completes. Marked sufficient or insufficient per the sufficiency rule. Always produced if the Decomposer succeeds, even if all agents fail.
- *PipelineError* — produced when the pipeline cannot run: Decomposer failed, Registry produced no agents, or a programming error was detected. Printed to stderr. Exit code non-zero.

**Side effects:**

- JSONL audit record appended for every pipeline event. Guaranteed for every event the system reaches — not best-effort.
- AuditReport printed to stdout on success.
- PipelineError printed to stderr on failure.

**Caller type:** Single caller — the human at the CLI. No multi-caller scenario is in scope.

**Idempotency:** The same Audit Request submitted twice MAY produce different AuditReports due to LLM non-determinism. The system does not guarantee idempotent outputs.

**Delivery semantics:** Not applicable. The system accepts one input per invocation and produces one output.

---

## §4 Data Contracts

### SubTask

| Field | Type | Required | Description |
|---|---|---|---|
| task_type | str | yes | Registry key identifying the Agent class to handle this task |
| context | str | yes | Relevant excerpt or restatement from the Audit Request for this task |

`task_type` MUST match a key in the Registry. An unrecognised `task_type` produces failure mode `unknown_task_type`.

### AgentResult

| Field | Type | Required | Description |
|---|---|---|---|
| task_type | str | yes | The SubTask type this result corresponds to |
| success | bool | yes | True if agent completed evaluation; False if it failed |
| content | str or None | conditional | Present if and only if success=True |
| failure_mode | str or None | conditional | Present if and only if success=False |
| reason | str or None | no | Human-readable explanation. Present when available |

Invariant: `success=True` requires `content` non-null and `failure_mode` null. `success=False` requires `failure_mode` non-null and `content` null. Enforced at construction — violation raises `ValueError`.

### AuditReport

| Field | Type | Required | Description |
|---|---|---|---|
| run_id | str | yes | Opaque run identifier linking audit records |
| audit_request | str | yes | The original Audit Request, unmodified |
| results | list[AgentResult] | yes | One entry per spawned agent, in completion order |
| sufficient | bool | yes | True if successful result count >= sufficiency threshold |
| successful_count | int | yes | Count of AgentResults with success=True |
| failed_count | int | yes | Count of AgentResults with success=False |
| sufficiency_threshold | int | yes | The threshold applied to determine sufficiency |

### AgentConfig

Base dataclass. Fields shared by all Agent types. Each subclass enforces its own invariants at construction — violation raises `ValueError` identifying the field.

| Field | Type | Required | Description |
|---|---|---|---|
| temperature | float | yes | LLM sampling temperature for this agent. Must be 0.0–1.0 inclusive. |
| max_tokens | int | yes | Maximum tokens in LLM response. Must be >= 1. |

Invariant: `temperature` must be in [0.0, 1.0]. `max_tokens` must be >= 1. Enforced at construction by each subclass.

**Subclasses** — each registered Agent type has a corresponding `AgentConfig` subclass. A subclass MAY add fields specific to that agent. A subclass MUST NOT remove or override base fields. If a subclass adds no fields, it still exists as a named type — it is never substituted with the base class directly. This ensures extension does not touch shared code.

Currently specified subclasses:

| Subclass | Agent type | Additional fields |
|---|---|---|
| `InjectionCheckAgentConfig` | `injection_check` | none currently |
| `AuthCheckAgentConfig` | `auth_check` | none currently |
| `XSSCheckAgentConfig` | `xss_check` | none currently |
| `GenericAuditAgentConfig` | `generic_audit` | none currently |

### Config

Top-level configuration dataclass. Constructed once at startup by the `Configurator`. Immutable after construction — no field may be modified after `Configurator.build()` returns.

| Field | Type | Required | Description |
|---|---|---|---|
| llm_base_url | str | yes | Base URL for the LLM provider. Must be a valid HTTP/HTTPS URL. Shared by Decomposer and all Agents. |
| llm_model | str | yes | Model identifier string. Non-empty. Shared by Decomposer and all Agents. |
| llm_api_key | str | yes | API key. Empty string is valid for local endpoints. Shared by Decomposer and all Agents. |
| audit_log_path | str | yes | Path to the JSONL audit file. Directory must exist and be writable. Default: `"audit.jsonl"`. |
| sufficiency_threshold | int | yes | Minimum successful AgentResults for a sufficient report. Must be >= 0. Default: `1`. |
| max_workers | int | yes | Thread pool size. Must be >= 1. Default: `4`. |
| decomposer_temperature | float | yes | LLM temperature for the Decomposer. Must be 0.0–1.0. Default: `0.0`. |
| agent_configs | dict[str, AgentConfig] | yes | Maps each registered `task_type` to its typed `AgentConfig` subclass instance. Keyset must exactly match the Registry keyset. |

Invariant: `agent_configs` keyset must match the Registry keyset exactly. A `Config` with a missing or extra key is invalid. This invariant is enforced by `Configurator` before returning — not by `Config.__post_init__`. Violation raises `ConfigurationError` identifying the mismatched key.

### JSONL Audit Record

Each record is one JSON object per line. UTF-8. Fields:

| Field | Type | Always present | Description |
|---|---|---|---|
| run_id | str | yes | Run identifier |
| event | str | yes | Event name (§18) |
| timestamp_utc | str | yes | ISO 8601 UTC timestamp |
| schema_version | str | yes | Spec version string |

Additional fields per event type are defined in §18.

---

## §5 Component Contracts

### Component Hierarchy

```
CLI Entry Point
  └── Orchestrator
        ├── Decomposer
        ├── Registry
        ├── ThreadPoolExecutor (concurrency mechanism — not a named component)
        ├── Agent (one instance per SubTask, per run)
        │     └── Tools (owned by Agent class)
        └── Auditor
```

---

### Orchestrator

**Purpose:** Drives the full pipeline for one Audit Request. Owns all component lifecycles within a run.

**Stateful.** Holds run state for the duration of one `run()` call. No state persists between calls.

**Invariants:**
- A run_id is generated before any audit record is written.
- The Auditor receives every event the Orchestrator reaches, regardless of pipeline outcome.
- AgentResults in AuditReport.results reflect actual agent outcomes — no result is synthesised.

**Preconditions for `run(audit_request)`:**
- `audit_request` is a non-empty string.
- Violation behaviour: raises `ValueError` identifying the violated precondition.

**Accepts:**
- `audit_request`: str — non-empty UTF-8 string

**Returns:**
- `AuditReport` — on Decomposer success, regardless of agent outcomes
- Raises `PipelineError` — on Decomposer failure or Registry returning empty agent list

**Postconditions:**
- After `run()`: at least one audit record exists for this run_id.
- `AuditReport.results` contains exactly one entry per agent spawned.
- `AuditReport.successful_count + AuditReport.failed_count == len(AuditReport.results)`

**Failure behaviour:**
- `decomposer_failed`: raises `PipelineError`. No AuditReport produced.
- `no_agents_spawned`: raises `PipelineError`. No AuditReport produced.
- `agent_execution_error`: AgentResult for that agent carries `success=False`, `failure_mode="agent_execution_error"`. Pipeline continues with remaining agents.

---

### Decomposer

**Purpose:** Reads the Audit Request and produces a list of SubTasks.

**Stateless** — holds no mutable state between calls.

**Invariants:** None — stateless.

**Preconditions for `decompose(audit_request)`:**
- `audit_request` is a non-empty string.
- Violation behaviour: raises `ValueError`.

**Accepts:**
- `audit_request`: str — non-empty string

**Returns:**
- `list[SubTask]` — non-empty list on success
- Raises `DecomposerError` on LLM failure or unparseable LLM output

**Postconditions:**
- Every returned SubTask has a non-empty `task_type` and non-empty `context`.

**Guarantees:**
- Never returns an empty list on success — raises `DecomposerError` instead.

**Failure behaviour:**
- `decomposer_llm_unavailable`: raises `DecomposerError`.
- `decomposer_output_unparseable`: raises `DecomposerError`.

---

### Registry

**Purpose:** Maps SubTask type strings to Agent classes.

**Stateless** — the mapping is static and fixed at startup.

**Invariants:**
- The mapping is read-only after construction. No registration after startup.
- Every registered Agent class implements the `BaseAgent` interface.

**Preconditions for `get(task_type)`:**
- `task_type` is a non-empty string.

**Accepts:**
- `task_type`: str

**Returns:**
- Agent class — if `task_type` is registered
- Raises `RegistryKeyError` — if `task_type` is not registered

**Failure behaviour:**
- `unknown_task_type`: raises `RegistryKeyError`. Orchestrator catches this and records AgentResult with `failure_mode="unknown_task_type"` for that SubTask.

---

### BaseAgent (abstract)

**Purpose:** Abstract base for all specialised agents. Defines the contract every agent MUST satisfy.

**Stateless** — each agent instance is constructed per SubTask and discarded after `execute()` returns.

**Invariants:**
- `name` class attribute is unique across all registered agents.
- `execute()` MUST NOT raise — failures MUST be returned as `AgentResult(success=False, ...)`.
- `execute()` MUST NOT close injected dependencies.

**Preconditions for `execute(subtask)`:**
- `subtask` is a valid SubTask with non-empty `task_type` and `context`.
- Violation behaviour: returns `AgentResult(success=False, failure_mode="precondition_violated")`.

**Accepts:**
- `subtask`: SubTask

**Returns:**
- `AgentResult` — always. Never raises.

**Guarantees:**
- Never raises — all failures are returned as `AgentResult(success=False, ...)`.

**Failure behaviour:**
- `agent_tool_failed`: a tool call raised or returned an error. Agent returns `AgentResult(success=False, failure_mode="agent_tool_failed")`.
- `agent_llm_unavailable`: LLM call failed. Agent returns `AgentResult(success=False, failure_mode="agent_llm_unavailable")`.
- `agent_execution_error`: unexpected error during execution. Agent returns `AgentResult(success=False, failure_mode="agent_execution_error")`.

---

### Auditor

**Purpose:** Writes audit records to the JSONL audit trail. Thread-safe.

**Stateful.** Holds a file handle for the duration of the run.

**Invariants:**
- Records are append-only. No record is modified or deleted after writing.
- Every `log()` call either writes a complete record or raises — no partial writes.
- The file handle is not shared with any other component.

**Preconditions for `log(event, data)`:**
- `event` is a non-empty string.
- `data` is a dict.
- Violation behaviour: raises `ValueError`.

**Guarantees:**
- `log()` is safe to call from multiple threads simultaneously.
- A failed `log()` call does not corrupt previously written records.

**Failure behaviour:**
- `audit_write_failed`: `log()` raises `AuditWriteError`. Orchestrator catches this, logs to stderr, and continues — audit write failure does not halt the pipeline.

---

### LLMBoundary

**Purpose:** Security boundary between the application and any LLM call. Normalises input and checks for injection patterns before the LLM sees it. Checks output for compromise indicators before the result reaches the caller.

**Stateless** — constructed per call site (Decomposer, each Agent). Holds no mutable state.

**Invariants:** None — stateless.

**Preconditions for `check_input(text)` and `check_output(text)`:**
- `text` is a non-empty string.

**Accepts:**
- `text`: str

**Returns:**
- `BoundaryResult(safe=True)` — text passed all checks
- `BoundaryResult(safe=False, failure_mode=...)` — text failed a check. Caller MUST raise `BoundaryError`.

**Guarantees:**
- Never raises — all failures returned as `BoundaryResult(safe=False, ...)`.
- Normalisation is idempotent — running `check_input` twice on the same text produces the same result.

**Failure behaviour:**
- `boundary_injection_detected`: input matched a known injection pattern after normalisation.
- `boundary_output_unsafe`: output matched a known compromise indicator.

**What LLMBoundary does NOT do:** It does not make LLM calls. It does not log to the audit trail. It does not enforce authentication. It is a pattern-and-normalisation check only. Semantic guard (full carapex) is deferred — see §2b.

---

### Configurator

**Purpose:** Reads configuration from environment variables and defaults. Validates all fields. Constructs and returns a fully populated `Config`.

**Stateless** — holds no mutable state. `build()` MAY be called more than once; each call produces an independent `Config`. No shared state between calls.

**Invariants:** None — stateless.

**Preconditions for `build()`:** None. All validation is internal.

**Accepts:** Nothing. Reads directly from `os.environ`.

**Returns:**
- `Config` — fully populated and validated on success.
- Raises `ConfigurationError` — if any required field is absent, any value fails validation, or `agent_configs` keyset does not match the Registry keyset.

**Resolution order for each field:**
1. Environment variable (if set and non-empty)
2. Default value (if defined in §15)
3. `ConfigurationError` (if required and no default exists)

**Environment variable mapping:**

| Config field | Environment variable |
|---|---|
| `llm_base_url` | `LLM_BASE_URL` |
| `llm_model` | `LLM_MODEL` |
| `llm_api_key` | `LLM_API_KEY` |
| `audit_log_path` | `AUDIT_LOG_PATH` |
| `sufficiency_threshold` | `SUFFICIENCY_THRESHOLD` |
| `max_workers` | `MAX_WORKERS` |
| `decomposer_temperature` | `DECOMPOSER_TEMPERATURE` |

Agent-specific config fields resolve from environment variables named `<TASK_TYPE>_<FIELD>` in uppercase (e.g., `INJECTION_CHECK_TEMPERATURE`). If absent, the field resolves from the `agent_temperature` default (§15).

**Guarantees:**
- A `Config` returned by `build()` is fully valid. No further validation is required by the caller.
- `Configurator` never modifies `os.environ`.
- `Configurator` never writes to the audit trail.
- `Configurator` never opens files or verifies filesystem state. Filesystem writability of `audit_log_path` is verified by `Auditor` at construction.
- `Configurator` never verifies LLM reachability. See §22.
- The set of returned `SubTask` instances MUST collectively cover the intent of the Audit Request at the level of available Agent types. No SubTask may be semantically redundant with another after deduplication by `task_type`.

**Failure behaviour:**
- Missing required field: raises `ConfigurationError` identifying the field by name.
- Invalid value (out of range, wrong type): raises `ConfigurationError` identifying the field and the constraint violated.
- `agent_configs` keyset mismatch: raises `ConfigurationError` with failure mode `config_agent_keyset_mismatch`.

---

## §6 Lifecycle

### Orchestrator

Constructed once per process. If construction fails (e.g., Auditor raises `ConfigurationError` because the audit log path is not writable), the constructor raises — no Orchestrator instance is produced and `run()` cannot be called. `run()` MAY be called multiple times sequentially on a successfully constructed instance. Each call is independent — no state from a prior run is visible in a subsequent run. Concurrent calls to `run()` are not supported (§13). `close()` releases the Auditor file handle. `close()` is idempotent. Calling `run()` after `close()` raises `RuntimeError`.

### Decomposer

Stateless. No lifecycle.

### Registry

Constructed once at startup from a static mapping. Not closeable. No lifecycle beyond construction.

### BaseAgent

Constructed per SubTask by the Orchestrator immediately before submission to the thread pool. Discarded after `execute()` returns. No `close()` required.

### Auditor

Constructed at Orchestrator construction. File handle opened at construction. `close()` flushes and closes the file handle. `close()` is idempotent. Calling `log()` after `close()` is a no-op — no exception is raised, no record is written. This is deliberate: teardown order may vary, and a late `log()` call MUST NOT corrupt or halt the shutdown sequence.

### LLMBoundary

Stateless. Constructed inline at each call site. No lifecycle — no `close()`, no initialisation beyond construction.

### Configurator

Stateless. No lifecycle. Called once by the CLI entry point before `Orchestrator` construction. The returned `Config` is passed into `Orchestrator.__init__`. `Configurator` is not injected into `Orchestrator` — it is used once and discarded.

### Config

Immutable after construction. No `close()`. Held by `Orchestrator` for the duration of the process lifetime. `Orchestrator` MUST NOT pass the full `Config` to any component — each component receives only its slice: the typed `AgentConfig` subclass for Agents; `decomposer_temperature` and the `llm_*` fields for Decomposer.

---

## §7 Failure Taxonomy

The failure mode set is open. Callers receiving an unknown failure mode MUST treat it as `agent_execution_error` (most conservative known agent failure) or `decomposer_failed` (most conservative pipeline failure) depending on context.

| Failure mode | Meaning | Category | Recoverability |
|---|---|---|---|
| `decomposer_llm_unavailable` | LLM call in Decomposer returned no response | Operational | Retry after backoff |
| `decomposer_output_unparseable` | Decomposer LLM returned output that could not be parsed into SubTasks | Operational | Retry; may be permanent for this input |
| `unknown_task_type` | SubTask.task_type not found in Registry | Programming error | Permanent for this input |
| `agent_tool_failed` | A tool called by an Agent raised or returned an error | Operational | Retry after backoff |
| `agent_llm_unavailable` | LLM call in Agent returned no response | Operational | Retry after backoff |
| `agent_execution_error` | Unexpected error during agent execution | Internal invariant violation | Not retryable — file a bug |
| `precondition_violated` | Agent called with invalid SubTask | Programming error | Permanent |
| `audit_write_failed` | Auditor could not write a record | Operational | Pipeline continues |
| `no_agents_spawned` | Registry returned no valid agents for the decomposed SubTasks | Operational / Programming error | Check Registry registration |
| `decomposer_failed` | Pipeline-level wrapper: Decomposer raised `DecomposerError` (covers both `decomposer_llm_unavailable` and `decomposer_output_unparseable`). Used in audit events and pipeline error reporting to indicate the pipeline cannot proceed. | Operational | Retry after backoff |
| `boundary_injection_detected` | LLMBoundary detected an injection pattern in input (Decomposer or Agent). Decomposer raises `DecomposerError`; Agent returns `AgentResult(success=False)`. | Adversarial | Log as security event. Do not retry same input. |
| `boundary_output_unsafe` | LLMBoundary detected a compromise indicator in LLM output (Decomposer or Agent). Decomposer raises `DecomposerError`; Agent returns `AgentResult(success=False)`. | Internal / Adversarial | Log as security signal. Do not use output. |
| `config_agent_keyset_mismatch` | `agent_configs` keyset in `Config` does not match the Registry keyset. Raised by `Configurator` at startup. | Programming error | Permanent — fix Registry registration or Configurator build logic. |

---

## §8 Boundary Conditions

**`run("")`** — empty string. Raises `ValueError` before Decomposer is called.

**`run(None)`** — raises `ValueError` before Decomposer is called.

**Decomposer returns one SubTask** — valid. Orchestrator spawns one agent. AuditReport contains one result. Sufficiency is evaluated normally against threshold.

**All agents fail** — AuditReport is produced with `sufficient=False`. `failed_count == len(results)`. Returned to caller as an insufficient report, not as a PipelineError.

**One agent fails, others succeed** — AuditReport is produced. `sufficient` is evaluated against threshold. If `successful_count >= sufficiency_threshold`, report is sufficient despite partial failure.

**`sufficiency_threshold` greater than number of agents spawned** — report is always insufficient. This is valid configuration — not an error.

**`sufficiency_threshold` of zero** — report is always sufficient regardless of failures. This is valid configuration.

**Unknown `task_type` from Decomposer** — Orchestrator catches `RegistryKeyError`. Records `AgentResult(success=False, failure_mode="unknown_task_type")` for that SubTask. Pipeline continues with remaining SubTasks.

---

## §9 Sentinel Values and Encoding Conventions

**`AgentResult.content = None`** — means agent failed. A caller MUST NOT read `content` without first checking `success=True`.

**`AgentResult.failure_mode = None`** — means agent succeeded. A caller MUST NOT read `failure_mode` without first checking `success=False`.

**`AgentResult.reason = None`** — means no human-readable explanation is available. This is not a failure condition.

**`AuditReport.sufficient = False`** — means the caller SHOULD NOT act on the report as if it were complete. The report is still returned and is readable. The caller decides whether to act on an insufficient report.

---

## §10 Atomicity and State on Failure

**Orchestrator `run()`** — not atomic. If the process is killed mid-run, the audit trail contains all records written up to that point. The AuditReport is not produced. The audit trail is not corrupt — records already written are intact. No recovery is performed on next startup. The partial audit trail is human-readable.

**Auditor `log()`** — each record write is atomic. A partial record is not written. If the write fails, `AuditWriteError` is raised and the file pointer is not advanced. Prior records are intact.

**Agent `execute()`** — each agent execution is independent. Failure of one agent does not affect the state of other agents executing concurrently.

**Ungraceful shutdown** — the JSONL audit file contains all records written before the crash. The file is not corrupt. No record is half-written. The AuditReport is not produced if the process is killed before it is printed.

---

## §11 Ordering and Sequencing

The pipeline executes in this fixed order:

```
Audit Request
  → Decomposer          (produces SubTask list)
  → Registry lookup     (maps each SubTask to an Agent class)
  → Concurrent execution (all agents run simultaneously)
  → Aggregation         (Orchestrator collects all AgentResults)
  → Sufficiency check   (Orchestrator applies threshold)
  → AuditReport         (produced and printed)
```

**Decomposer MUST precede Registry lookup** — the SubTask list does not exist before Decomposer completes.

**Registry lookup MUST precede concurrent execution** — agent classes must be resolved before threads are submitted.

**Concurrent execution MUST complete before aggregation** — all AgentResults must be present before sufficiency can be evaluated.

**Completion policy:**

The Orchestrator MUST wait for all agent executions to complete before proceeding to aggregation and sufficiency evaluation. Early termination based on partial results is not permitted.

This decision prioritises determinism and completeness of the `AuditReport` over latency. Cancellation and early-exit strategies are explicitly out of scope.

**Aggregation MUST precede sufficiency check** — `successful_count` is computed from results.

**Sufficiency check MUST precede AuditReport construction** — `sufficient` field requires the threshold evaluation result.

Order within concurrent execution is undefined — agents run simultaneously and complete in arrival order. `AuditReport.results` records completion order, not submission order.

---

## §12 Interaction Contracts

### Orchestrator → Decomposer

Orchestrator passes the raw Audit Request string unmodified. Decomposer MUST NOT receive a preprocessed or truncated version. Decomposer owns no resources. Orchestrator does not close Decomposer.

### Orchestrator → Registry

Orchestrator calls `Registry.get(task_type)` for each SubTask. Registry is read-only — Orchestrator MUST NOT attempt to register or modify entries. Registry owns no closeable resources.

### Orchestrator → Agent

Orchestrator constructs one Agent instance per SubTask. The Agent is submitted to the thread pool and discarded after `execute()` returns. The Orchestrator owns the thread pool — not the Agent. Agents MUST NOT hold references to the thread pool. The Agent MUST NOT close any injected LLM provider — the Orchestrator owns LLM lifecycle.

### Orchestrator → Auditor

Orchestrator calls `Auditor.log()` from multiple threads simultaneously (once per agent completion event). Auditor MUST be thread-safe (§13). Orchestrator owns the Auditor and calls `close()` at run end. Agents MUST NOT call `Auditor.log()` directly — they return `AgentResult` and the Orchestrator logs on their behalf.

---

## §13 Concurrency and Re-entrancy

**Concurrent agent execution** — agents execute concurrently in a `ThreadPoolExecutor`. Each agent runs in its own thread. Agents MUST NOT share mutable state. Agents MUST NOT call each other.

**Concurrency bound and queueing:**

Concurrency is bounded by `max_workers`. If the number of spawned agents exceeds this bound, excess tasks are queued internally by the executor and executed as worker threads become available.

No explicit backpressure, rate limiting, or load shedding mechanisms are implemented. The executor's internal queue provides implicit task buffering.

**Auditor thread safety** — `Auditor.log()` MUST be safe to call from multiple threads simultaneously. Internal synchronisation is the Auditor's responsibility. Callers MUST NOT coordinate externally.

**Orchestrator `run()`** — MUST NOT be called concurrently. Sequential calls are safe. A caller who calls `run()` from multiple threads simultaneously produces undefined behaviour.

**Re-entrancy** — no component is re-entrant. No callback mechanism exists that could cause re-entrant calls.

---

## §14 External Dependencies

**LLM provider** — required. Used by Decomposer and each Agent. If unavailable at call time, the dependent component returns the appropriate failure mode (`decomposer_llm_unavailable`, `agent_llm_unavailable`). Not verified at startup — verified on first use. A startup that succeeds does not guarantee the LLM is reachable.

**Filesystem** — required for audit trail. The path specified in configuration MUST be writable. If not writable at startup, `Auditor` construction raises `ConfigurationError`. Verified at startup by attempting to open the file for append.

**Python standard library** — required: `concurrent.futures`, `dataclasses`, `json`, `threading`, `datetime`, `uuid`, `sys`. No third-party dependencies beyond the LLM client library.

---

## §15 Configuration

| Field | Type | Default | Valid values | Notes |
|---|---|---|---|---|
| `llm_base_url` | str | none | Valid HTTP/HTTPS URL | Required. No default. Missing raises `ConfigurationError`. |
| `llm_model` | str | none | Non-empty string | Required. No default. Missing raises `ConfigurationError`. |
| `llm_api_key` | str | `""` | Any string | Empty string is valid — some local endpoints require no key. |
| `audit_log_path` | str | `"audit.jsonl"` | Writable file path | File is created if absent. Directory MUST exist. |
| `sufficiency_threshold` | int | `1` | >= 0 | Zero means always sufficient. Values exceeding agent count produce always-insufficient reports. |
| `max_workers` | int | `4` | >= 1 | Thread pool size. Does not bound agent count — more agents than workers queue. |
| `decomposer_temperature` | float | `0.0` | 0.0–1.0 inclusive | 0.0 for deterministic decomposition. |
| `agent_temperature` | float | `0.1` | 0.0–1.0 inclusive | Default temperature applied to all AgentConfig subclasses unless overridden by agent-specific env var. |

All fields are read at startup. None are mutable after construction. Invalid values raise `ConfigurationError` identifying the field by name.

**Execution time constraint:**

The system does not enforce a global pipeline timeout. Individual agent execution MAY be bounded by a per-agent timeout applied at the concurrency layer. If a timeout occurs, the agent MUST return `AgentResult(success=False, failure_mode="agent_execution_error")`.

Timeout configuration is optional and may be implemented as a constant or derived from configuration. Advanced timeout strategies (cascading deadlines, adaptive timeouts) are out of scope.

---

## §16 Extension Contracts

### Adding a new Agent type

**MUST implement:**
- `name: str` — unique class attribute. Collision with existing name raises `RuntimeError` at registration.
- `execute(subtask: SubTask) -> AgentResult` — MUST NOT raise. MUST return `AgentResult`. MUST handle all internal failures by returning `AgentResult(success=False, failure_mode=...)`.
- `_tools: list[callable]` — list of tool functions the agent may call. MAY be empty.
- `_system_prompt: str` — domain-specific system prompt for the LLM call.

**MUST define a paired `AgentConfig` subclass:**
- Name convention: `<AgentClassName>Config` (e.g., `XSSCheckAgentConfig`).
- MUST subclass `AgentConfig`. MUST NOT remove or override base fields.
- MUST enforce its own invariants at construction — violation raises `ValueError`.
- MUST be registered in `Configurator` alongside the Agent class — `agent_configs` keyset must include the new `task_type`.

**MUST call LLMBoundary:**
- `LLMBoundary().check_input(subtask.context)` before the LLM call. If `safe=False` → return `AgentResult(success=False, failure_mode=boundary_result.failure_mode)`.
- `LLMBoundary().check_output(response)` after the LLM call. If `safe=False` → return `AgentResult(success=False, failure_mode=boundary_result.failure_mode)`.

**MUST NEVER do:**
- Raise from `execute()` — this bypasses the Orchestrator's result collection and leaves a thread pool slot unreturned.
- Close injected LLM providers — Orchestrator owns LLM lifecycle.
- Share mutable state with other agent instances — agents run concurrently.
- Call `Auditor.log()` directly — return `AgentResult` and let Orchestrator log.
- Skip LLMBoundary checks — boundary is mandatory, not optional.

**Registration:** Add the Agent class to the Registry mapping at the bottom of `registry.py`. No other file changes required. Duplicate names raise `RuntimeError` at import time.

---

## §17 Error Propagation

**`DecomposerError`** — originates in Decomposer. Propagates to Orchestrator. Orchestrator logs `decomposer_failed` event, then raises `PipelineError` to the CLI entry point. CLI prints to stderr and exits non-zero.

**`RegistryKeyError`** — originates in Registry. Caught by Orchestrator. Converted to `AgentResult(success=False, failure_mode="unknown_task_type")`. Does not propagate beyond Orchestrator.

**`AgentResult(success=False)`** — originates in Agent. Returned to thread pool future. Collected by Orchestrator in aggregation. Appears in `AuditReport.results`. Does not raise.

**Unexpected exception in Agent `execute()`** — caught by Orchestrator at future collection. Converted to `AgentResult(success=False, failure_mode="agent_execution_error")`. Logged as security signal. Does not propagate.

**`AuditWriteError`** — originates in Auditor. Caught by Orchestrator. Logged to stderr. Pipeline continues. Does not propagate.

**`BoundaryError` in Decomposer** — originates in LLMBoundary. Caught by Decomposer. Decomposer raises `DecomposerError(failure_mode=boundary_result.failure_mode)`. Propagates to Orchestrator → `PipelineError` → stderr, exit non-zero. Logged as security event.

**`BoundaryError` in Agent** — originates in LLMBoundary. Caught by Agent inside `execute()`. Agent returns `AgentResult(success=False, failure_mode=boundary_result.failure_mode)`. Does not propagate. Logged as security signal in audit trail via `agent_complete` event.

**`ValueError` from precondition violation** — originates in Orchestrator or Decomposer. Propagates to CLI entry point. CLI prints to stderr and exits non-zero.

**`no_agents_spawned`** — detected by Orchestrator after Registry lookup produces zero valid agents (all SubTasks produced `RegistryKeyError`). Orchestrator logs `pipeline_error` event with `failure_mode="no_agents_spawned"`, then raises `PipelineError`. Propagates to CLI entry point. CLI prints to stderr and exits non-zero. No AuditReport is produced.

---

## §18 Observability Contract

All events are written to the JSONL audit trail. Emission is guaranteed for every event the system reaches — not best-effort. Events are written before the operation they describe completes, except `run_complete` which is written after AuditReport is produced.

| Event | When emitted | Guaranteed fields | Conditional fields |
|---|---|---|---|
| `run_started` | Before Decomposer is called | `run_id`, `audit_request_length` | — |
| `decompose_complete` | After Decomposer returns | `run_id`, `subtask_count` | — |
| `agent_started` | Before each agent is submitted to thread pool | `run_id`, `task_type` | — |
| `agent_complete` | After each agent future resolves | `run_id`, `task_type`, `success` | `failure_mode` (if success=False) |
| `run_complete` | After AuditReport is produced | `run_id`, `successful_count`, `failed_count`, `sufficient` | — |
| `pipeline_error` | When Orchestrator raises PipelineError | `run_id`, `failure_mode` | `reason` |
| `audit_write_failed` | When Auditor.log() fails | — (written to stderr only) | — |
| `boundary_violation` | When LLMBoundary returns safe=False at any call site | `run_id`, `failure_mode`, `call_site` (`decomposer` or `agent`) | `task_type` (if call_site=agent) |

**What is not logged:** Audit Request content is not included in any event field. `AgentResult.content` is not logged. LLM responses are not logged. Only structural metadata is recorded. This is a deliberate security decision — audit records MUST NOT contain the content being evaluated.

**Schema versioning:** Every record carries `schema_version` set to the spec version. Consumers receiving an unknown `schema_version` MUST treat unknown fields as absent and known fields as specified.

---

## §19 Security Properties

**Audit Request is untrusted input.** The Decomposer MUST NOT execute, evaluate, or interpret the Audit Request as code or system instructions. It is a natural language string to be decomposed — not a command. LLMBoundary MUST check it before the LLM sees it.

**SubTask context is untrusted.** Every Agent MUST pass `subtask.context` through `LLMBoundary.check_input()` before the LLM call. A SubTask context that fails boundary check produces `AgentResult(success=False, failure_mode="boundary_injection_detected")`.

**LLM output is untrusted.** Every LLM response — in Decomposer and in every Agent — MUST pass through `LLMBoundary.check_output()` before reaching the caller. An output that fails boundary check is discarded.

**Fail closed on agent failure.** A failed agent produces `AgentResult(success=False)`. It does not produce a passing result. No agent failure is silently treated as success.

**Agent side-effect constraint:**

All Agents MUST be side-effect free with respect to external systems. An Agent MUST NOT perform writes, mutations, or irreversible operations outside its local execution context.

This constraint ensures that repeated execution of an Agent on the same `SubTask` is safe. Retry mechanisms are not implemented in this system; however, this property guarantees that retries could be introduced without risking duplicate side effects.

**Audit trail integrity.** Records are append-only. No component has write access to prior records. A component that modifies prior records violates this property and invalidates the audit trail.

**What the system does not guarantee:** The system does not guarantee that a sufficient AuditReport correctly identifies all vulnerabilities. Agent coverage is bounded by the registered agent types. Human review of the AuditReport is the sole mechanism for completeness verification.

---

## §20 Versioning and Evolution

**Spec version:** 0.4

| Interface | Stability |
|---|---|
| `AgentResult` schema | Evolving — fields may be added |
| `AuditReport` schema | Evolving — fields may be added |
| `SubTask` schema | Evolving — fields may be added |
| Failure mode set | Evolving — new modes may be added; existing modes stable |
| Observability event schema | Evolving — new events may be added; existing events stable |
| `BaseAgent` interface | Evolving — new methods may be added with defaults |
| Configuration fields | Evolving — new fields may be added with defaults; existing fields stable |

**Breaking change:** any change that causes a caller relying on a previously-specified contract to receive a different result than the prior spec guaranteed.

---

## §21 What Is Not Specified

- The LLM provider implementation. Any provider implementing `complete(prompt) -> str | None` is conformant.
- The specific prompts used by the Decomposer or any Agent.
- The specific tools each Agent class provides — only that tools are plain callables.
- The internal data structures used by the Auditor for synchronisation.
- The retry strategy for LLM calls within agents or the Decomposer.
- The format of `AuditReport` output printed to stdout — JSON, plain text, or structured table are all conformant.
- The number and types of registered Agent classes beyond the minimum of one.
- Output determinism and reproducibility guarantees. LLM responses are inherently non-deterministic. The system does not enforce output stabilization, caching, or replay mechanisms. Consumers MUST treat repeated executions of the same Audit Request as potentially producing different results.

---

## §22 Assumptions

**Environmental:**
- Python >= 3.10. `dataclasses`, `concurrent.futures`, `json`, `threading` are available.
- The filesystem does not silently corrupt JSONL records after writing.
- The LLM provider is reachable over the network. Transient unavailability produces the appropriate failure mode; persistent unavailability is not handled by the system.

**LLM reachability is assumed, not verified.** No health check is performed at startup. A provider that is unreachable or returns errors produces the appropriate failure mode per component (`decomposer_llm_unavailable`, `agent_llm_unavailable`) — but the system makes no attempt to detect or recover from persistent unavailability. This is a deliberate scope trade-off. Retry logic, circuit breaking, and provider fallback are valid production concerns and are deferred. The failure modes are already specified; handling is left to the implementor.

**Caller:**
- The human caller acts in good faith. The system does not defend against a caller who crafts an Audit Request designed to produce a harmful report.
- The caller calls `run()` sequentially, not concurrently. Concurrent calls produce undefined behaviour (§13).
- The caller calls `close()` after use.

**Operational:**
- The audit log directory exists and is writable before startup.
- Configuration is valid and present at startup.
- The LLM API key, if required, is correct. An incorrect key produces `agent_llm_unavailable` or `decomposer_llm_unavailable` — indistinguishable from unavailability at this spec level.

---

## §23 Performance Contracts

**Thread pool does not bound agent count** — a correctness contract. If more SubTasks exist than `max_workers`, excess agents queue. All agents MUST eventually execute. The Orchestrator MUST NOT discard queued agents.

**All agent futures MUST be collected** — a correctness contract. An Orchestrator that does not collect all futures produces an incomplete AuditReport. `AuditReport.results` MUST contain one entry per spawned agent.

**Sufficiency threshold is evaluated after all agents complete** — a correctness contract. Evaluating sufficiency before all futures resolve produces a verdict based on incomplete results.

Throughput, latency, and LLM response times are implementation characteristics. Not specified here.

---

*End of specification v0.4*

*Verification status: COMPLETE. Implementation Readiness: READY. 0 blocking gaps, 7 non-blocking. Safe to hand to implementation.*
