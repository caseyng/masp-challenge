# Multi-Agent Security Pipeline — Specification

**Version:** 1.0.0  
**Status:** Implementation Readiness: READY  
**Verification Currency:** CURRENT  

---

## §1 Purpose and Scope

The Multi-Agent Security Pipeline (MASP) accepts a free-text security audit request from the CLI, decomposes it into specialist subtasks via an LLM, executes those subtasks concurrently using real local tools, and produces a structured audit report and machine-readable audit trail. It is a single-run CLI tool: one invocation, two output files, clean exit.

**In scope:** inspecting the local filesystem, network surfaces, environment variables, and configuration files of the directory in which it is invoked.

**Out of scope:** remote host scanning, authenticated API auditing, continuous monitoring, remediation actions, or any modification of the scanned environment.

**Design principles:**
- Correctness over completeness: a partial report that correctly describes what ran is better than a complete report with fabricated findings.
- Fail-visible: every failure MUST appear in the audit trail and in the report; silent omission is a defect.
- No crash guarantee: the overall run MUST exit 0 regardless of sub-agent failures, provided at least the orchestration layer completes.

---

## §2 Concepts and Vocabulary

**Audit Request:** the free-text string supplied by the CLI caller describing the security concern to investigate. Treated as untrusted user input.

**Orchestrator:** the top-level component that calls an LLM to decompose the Audit Request into subtasks, dispatches Sub-Agents, aggregates their results, calls the LLM a second time to synthesise a final report, and writes output files.

**Sub-Agent:** a stateful, single-use component that executes one specialist subtask. Each Sub-Agent owns one or more Tool invocations and one LLM reasoning call, then returns a SubAgentResult.

**Tool:** a stateless function that performs a real local operation (filesystem scan, port probe, env inspection, config parse). Tools do not call LLMs.

**SubAgentResult:** the structured JSON value a Sub-Agent returns to the Orchestrator upon completion or failure. Defined in §4.

**AuditTrailEntry:** a single JSON-lines record appended to `audit_trail.jsonl` when a named event occurs. Defined in §4.

**Severity:** one of five ordered labels applied to findings: `Critical`, `High`, `Medium`, `Low`, `Info`. `Info` is the least severe. The ordering is total and closed.

**Recovery:** the orchestrator's response to a sub-agent failure: re-run the entire Sub-Agent once (retry), then, if it fails again, substitute a graceful partial result.

**Graceful partial result:** a SubAgentResult with `status: "failed"` and a findings array containing exactly one entry describing the failure reason. Severity MUST be `"Info"`.

**Subtask count bounds:** the valid number of subtasks is [2, 4] inclusive.

**Exception types** (named before use in §5 and §7):
- `OrchestratorError`: raised when the orchestrator itself cannot proceed (e.g. output file unwritable).
- `SubAgentError`: raised internally by a Sub-Agent to signal unrecoverable failure. Never propagates past the Orchestrator's sub-agent boundary.
- `ToolError`: raised by a Tool to signal a local operation failure. Never propagates past the Sub-Agent.
- `LLMError`: raised when an LLM API call fails (timeout, rate limit, malformed response). Never propagates past the component that issued the call.

---

## §2b Architectural Constraints

**BaseSubAgent:** abstract base class. All specialist Sub-Agents MUST extend `BaseSubAgent`. `BaseSubAgent` MUST NOT be instantiated directly. Specialists MUST override the abstract method `run() -> SubAgentResult`.

**Sub-Agent registry:** the Orchestrator MUST dispatch only from a closed registry of four specialist types: `SecretsSubAgent`, `PortsSubAgent`, `EnvSubAgent`, `ConfigSubAgent`. The LLM decomposition step selects a subset of these types; it does not name arbitrary types. Unknown type names from the LLM MUST be dropped before dispatch.

**Tool functions:** MUST be implemented as stateless standalone functions, not as methods on Sub-Agent instances. Sub-Agents call Tools; Tools do not call Sub-Agents.

**Audit trail ownership:** the Orchestrator owns the `audit_trail.jsonl` file handle. Sub-Agents MUST NOT write directly to the file. Sub-Agents return structured results; the Orchestrator appends trail entries.

**LLM call ownership:** each component owns its own LLM calls. Sub-Agents call the LLM once to reason about tool output. The Orchestrator calls the LLM once to decompose and once to synthesise. Components MUST NOT delegate LLM calls to other components.

---

## §3 System Boundary

**Inputs:**

| Input | Type | Valid range | Invalid input behaviour |
|---|---|---|---|
| CLI argument 0 | string | 1–2000 characters, non-whitespace-only | If absent, whitespace-only, or >2000 chars: print usage to stderr, exit 1 |
| `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` env var | string | non-empty | If absent: print error to stderr, exit 1 before any LLM call |
| Local filesystem | - | read access to CWD | Permission errors are ToolErrors handled per §7 |

**Outputs:**

| Output | Type | Guarantee |
|---|---|---|
| `report.md` | UTF-8 markdown file | Always written if orchestration completes, even on all sub-agent failures |
| `audit_trail.jsonl` | UTF-8 JSONL file | Incrementally written; each entry appended immediately on event occurrence |
| Exit code | int | 0 on clean run or recoverable failure; 1 only on OrchestratorError |

**Idempotency:** not idempotent. Two runs on the same directory with the same request MAY produce different output (LLM non-determinism, changed filesystem state, port availability).

**Delivery semantics for `audit_trail.jsonl`:** at-least-once per event. Under normal operation, exactly one entry per event. On process kill mid-append, the last entry MAY be truncated; earlier entries are intact.

---

## §4 Data Contracts

### SubAgentResult

JSON object returned from each Sub-Agent to the Orchestrator.

| Field | Type | Required | Valid values | Absent means |
|---|---|---|---|---|
| `agent_id` | string | yes | UUID v4 | — |
| `agent_type` | string | yes | one of: `secrets`, `ports`, `env`, `config` | — |
| `status` | string | yes | `"complete"`, `"partial"`, `"failed"` | — |
| `findings` | array of string | yes | 0 or more entries; each non-empty string | — |
| `severity` | string | yes | `"Critical"`, `"High"`, `"Medium"`, `"Low"`, `"Info"` | — |
| `tool_outputs` | array of object | yes | 0 or more ToolOutput objects (see below) | — |
| `error` | string or null | yes | failure description, or null if status is `"complete"` | — |

**ToolOutput object:**

| Field | Type | Required | Notes |
|---|---|---|---|
| `tool_name` | string | yes | name of the tool function called |
| `status` | string | yes | `"ok"` or `"error"` |
| `summary` | string | yes | brief description of what was found or the error message |

Unknown fields in SubAgentResult MUST be ignored by the Orchestrator.

### AuditTrailEntry

One JSON object per line in `audit_trail.jsonl`. All entries share a common envelope; the `payload` field varies by `event_type`.

| Field | Type | Required | Notes |
|---|---|---|---|
| `ts` | string | yes | ISO 8601 UTC timestamp, e.g. `"2026-04-27T10:00:00.123Z"` |
| `event_type` | string | yes | one of the closed set below |
| `agent_id` | string or null | yes | UUID of the Sub-Agent, or null for Orchestrator events |
| `agent_type` | string or null | yes | sub-agent type string, or null for Orchestrator events |
| `payload` | object | yes | event-specific fields (see below) |

**Closed set of `event_type` values:**

| event_type | When appended | Key payload fields |
|---|---|---|
| `run_start` | before first LLM call | `{"request": <audit_request_string>}` |
| `decomposition` | after LLM returns subtask list | `{"subtasks": [<type_string>, ...]}` |
| `agent_start` | when Sub-Agent begins execution | `{}` |
| `tool_call` | after each Tool invocation completes | `{"tool_name": str, "status": "ok"\|"error", "summary": str}` |
| `llm_call` | after each LLM call completes | `{"purpose": "reasoning"\|"decompose"\|"synthesise", "status": "ok"\|"error"}` |
| `agent_end` | when Sub-Agent returns a result | `{"status": "complete"\|"partial"\|"failed", "severity": str}` |
| `agent_retry` | when Orchestrator retries a failed Sub-Agent | `{"reason": str}` |
| `agent_recovery` | when Orchestrator substitutes graceful partial result | `{"reason": str}` |
| `synthesis` | after final LLM synthesis call completes | `{"status": "ok"\|"error"}` |
| `run_end` | after both output files are written | `{"duration_seconds": float, "exit_code": int}` |

Unknown `event_type` values encountered by a reader MUST be treated as informational and not cause a parse failure.

### report.md structure

The report MUST contain the following sections in order:

1. `# Security Audit Report` — heading with the original audit request quoted verbatim
2. `## Executive Summary` — synthesised by the Orchestrator's final LLM call; 1–3 paragraphs
3. One `## [AgentType] Findings` section per Sub-Agent that ran, containing:
   - `**Severity:** [label]`
   - `**Status:** [complete | partial | failed]`
   - A bulleted list of findings strings (or a single bullet `"Sub-agent did not complete: [reason]"` if status is `"failed"`)
4. `## Audit Metadata` — total duration, number of sub-agents run, number that failed

---

## §5 Component Contracts

### Component hierarchy

```
Orchestrator
  ├── LLM Client (stateless, shared)
  ├── AuditTrailWriter (stateful, owned by Orchestrator)
  └── Sub-Agents (1 per subtask, concurrent)
       ├── SecretsSubAgent  extends BaseSubAgent
       ├── PortsSubAgent    extends BaseSubAgent
       ├── EnvSubAgent      extends BaseSubAgent
       └── ConfigSubAgent   extends BaseSubAgent
            └── Tools (stateless functions, called by Sub-Agents)
```

---

**Component: Orchestrator**  
Purpose: decompose the audit request, manage Sub-Agent lifecycle, aggregate results, produce outputs.

Stateful: yes — holds subtask list, list of SubAgentResults, AuditTrailWriter reference, run start time.

Invariants:
- The `audit_trail.jsonl` file handle MUST be open for the entire duration of a run.
- SubAgentResults list length MUST equal the number of Sub-Agents dispatched (including those that returned graceful partial results).

Preconditions for `run(audit_request)`:
- `audit_request` is a non-empty, non-whitespace-only string of ≤ 2000 characters.
- At least one of `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` is set in the environment.
- Violation behaviour: raises `OrchestratorError` immediately before any LLM call or file creation.

Accepts:
- `audit_request`: string — 1–2000 characters, non-whitespace-only.

Returns:
- On success: exits process with code 0; `report.md` and `audit_trail.jsonl` written to CWD.
- On `OrchestratorError`: exits process with code 1; no output files guaranteed.

Postconditions:
- After `run()` completes with exit 0: `report.md` exists and contains all required sections. `audit_trail.jsonl` exists and contains at least `run_start` and `run_end` entries.
- `audit_trail.jsonl` MUST contain one `agent_retry` entry for every Sub-Agent that was retried.
- `audit_trail.jsonl` MUST contain one `agent_recovery` entry for every Sub-Agent that was substituted.

Guarantees:
- Never raises `SubAgentError`, `ToolError`, or `LLMError` to the process top level.
- Always writes `run_end` entry to audit trail before exiting, even when all sub-agents failed.

Failure behaviour:
- `OUTPUT_WRITE_FAILURE` (§7): raises `OrchestratorError`, exits 1.
- `ALL_SUBAGENTS_FAILED` (§7): exits 0; report documents all failures.

---

**Component: BaseSubAgent (abstract)**  
Purpose: abstract base defining the Sub-Agent contract. Not instantiated directly.

Stateful: yes — holds `agent_id` (UUID), `agent_type` string, and execution result after `run()` returns.

Invariants:
- `agent_id` MUST NOT change after construction.
- `run()` MUST be called at most once per instance.

Preconditions for `run()`:
- Component has been constructed with a valid `agent_type`.
- Violation behaviour: raises `SubAgentError("already_run")` if called a second time.

Returns:
- Always returns a `SubAgentResult`. Never raises past the Sub-Agent boundary.

Postconditions:
- After `run()` returns: `SubAgentResult.agent_id` equals this instance's `agent_id`.
- `SubAgentResult.status` is one of `"complete"`, `"partial"`, `"failed"`.
- If `status` is `"failed"`: `findings` contains exactly one entry; `severity` is `"Info"`; `error` is non-null.
- If `status` is `"complete"`: `error` is null.

Guarantees:
- Never propagates `ToolError` or `LLMError` to the caller; catches and records them.

Failure behaviour:
- `TOOL_EXECUTION_FAILURE` (§7): recorded in `tool_outputs`; Sub-Agent continues with remaining tools, then calls LLM to reason about partial tool output.
- `LLM_CALL_FAILURE` (§7): `status` set to `"partial"`; findings set to tool output summaries; no LLM reasoning incorporated.
- `UNRECOVERABLE_SUBAGENT_FAILURE` (§7): `status` set to `"failed"`; graceful partial result returned.

---

**Component: SecretsSubAgent**  
Purpose: scan the filesystem for patterns indicative of committed secrets (API keys, private keys, tokens, passwords in config files).

Stateful: inherits from BaseSubAgent.

Tools used: `scan_filesystem_for_secrets(path: str) -> list[dict]`

LLM reasoning input: list of matched file paths and pattern categories (MUST NOT include matched secret values).

---

**Component: PortsSubAgent**  
Purpose: probe a defined set of common ports on localhost to identify exposed network surfaces.

Stateful: inherits from BaseSubAgent.

Tools used: `probe_local_ports(ports: list[int]) -> list[dict]`

Ports probed (closed set): 22, 80, 443, 3000, 3306, 5432, 5672, 6379, 8080, 8443, 8888, 27017.

LLM reasoning input: list of open ports with service guesses.

---

**Component: EnvSubAgent**  
Purpose: inspect environment variables for sensitive values (credentials, tokens, keys) that should not be present in a running process environment.

Stateful: inherits from BaseSubAgent.

Tools used: `inspect_environment_variables() -> list[dict]`

LLM reasoning input: list of env var names flagged as potentially sensitive (MUST NOT include values — values MUST NOT appear in audit trail, report, or LLM context).

---

**Component: ConfigSubAgent**  
Purpose: parse configuration files in the CWD for insecure settings (debug mode enabled, hardcoded credentials, permissive CORS/auth, plaintext connection strings).

Stateful: inherits from BaseSubAgent.

Tools used: `scan_config_files(path: str) -> list[dict]`

LLM reasoning input: list of flagged config keys and their non-secret context.

---

**Component: LLM Client**  
Purpose: issue a single LLM API call with a given system prompt and user message; return the text response.

Stateless: holds no mutable state between calls.

Invariants: None — this component is stateless.

Preconditions for `call(system, user)`:
- API key env var set.
- `system` and `user` are non-empty strings.

Returns:
- On success: string response from LLM.
- On failure: raises `LLMError`.

Guarantees:
- Applies a 30-second timeout per call.
- Retries once on timeout or rate-limit response before raising `LLMError`.

---

**Component: AuditTrailWriter**  
Purpose: append AuditTrailEntry records to `audit_trail.jsonl` incrementally during a run.

Stateful: yes — holds open file handle.

Invariants:
- File handle MUST be open between `open()` and `close()` calls.

Preconditions for `append(entry)`:
- `open()` has been called and succeeded.
- Violation behaviour: raises `OrchestratorError`.

Guarantees:
- Each `append()` call flushes to disk before returning.
- Never raises on malformed `entry` — serialises what it can; logs a warning to stderr.

Failure behaviour:
- `OUTPUT_WRITE_FAILURE` (§7): raises `OrchestratorError`.

---

## §6 Lifecycle

**Orchestrator lifecycle:**

```
UNINITIALISED → (run() called) → RUNNING → COMPLETE | FAILED
```

- `UNINITIALISED`: initial state after construction.
- `RUNNING`: from first LLM call through output file close.
- `COMPLETE`: both output files written, process exits 0.
- `FAILED`: `OrchestratorError` raised, process exits 1.

`run()` MUST NOT be called more than once on the same Orchestrator instance. If called a second time: raises `OrchestratorError`.

**BaseSubAgent lifecycle:**

```
CONSTRUCTED → (run() called) → EXECUTING → RETURNED
```

- `run()` MUST NOT be called on an instance in `RETURNED` state. Raises `SubAgentError("already_run")`.
- No `close()` method. Instance is single-use and discarded after `run()` returns.

**AuditTrailWriter lifecycle:**

```
CLOSED → (open() called) → OPEN → (close() called) → CLOSED
```

- `append()` is valid only in `OPEN` state.
- `close()` is idempotent: calling it in `CLOSED` state is a no-op.
- `open()` in `OPEN` state raises `OrchestratorError`.

---

## §7 Failure Taxonomy

The failure mode set is closed. Callers encountering an unknown failure name MUST treat it as `UNRECOVERABLE_SUBAGENT_FAILURE`.

| Name | Category | Meaning | Recoverability | Representation | What is NOT done |
|---|---|---|---|---|---|
| `OUTPUT_WRITE_FAILURE` | Operational failure | CWD is not writable, or disk full, when attempting to create or append to an output file | Permanent for this run | Raises `OrchestratorError` | Does not suppress the error or continue silently |
| `LLM_CALL_FAILURE` | Operational failure | LLM API call failed after one retry: timeout, rate limit, authentication error, or response not parseable as expected format | Retry after backoff (handled internally by LLM Client) | Raises `LLMError` | Does not partially apply LLM output |
| `TOOL_EXECUTION_FAILURE` | Operational failure | A Tool raised an exception (permission denied, socket refused, parse error) | Permanent for this tool invocation | Raises `ToolError`; caught by Sub-Agent | Does not retry the tool |
| `SUBAGENT_TIMEOUT` | Operational failure | A Sub-Agent's total execution exceeds 45 seconds | Triggers recovery flow (retry once, then graceful partial) | Caught by Orchestrator at task boundary | Does not kill the LLM session |
| `DECOMPOSITION_OUT_OF_BOUNDS` | Operational failure | LLM returns a subtask list with fewer than 2 or more than 4 items, or with no items matching the closed registry | Permanent for this call | Silently clamped by Orchestrator; logged as `decomposition` trail entry | Does not raise or abort the run |
| `UNKNOWN_AGENT_TYPE` | Operational failure | LLM decomposition names a type not in the closed registry | Permanent for this name | Type silently dropped before dispatch; recorded in `decomposition` trail entry | Does not raise |
| `UNRECOVERABLE_SUBAGENT_FAILURE` | Operational failure | Sub-Agent raised an unhandled exception not covered by `ToolError` or `LLMError` | Recovery: retry once; then graceful partial result | Caught by Orchestrator at task boundary | Does not propagate to top level |
| `ALL_SUBAGENTS_FAILED` | Operational failure | Every dispatched Sub-Agent returned `status: "failed"` | Not retried | Orchestrator exits 0; report documents total failure | Does not raise `OrchestratorError`; does not exit 1 |
| `INVALID_AUDIT_REQUEST` | Programming error | Audit request is absent, whitespace-only, or exceeds 2000 characters | Permanent | Raises `OrchestratorError` before any I/O | Does not create output files |
| `MISSING_API_KEY` | Programming error | Neither `ANTHROPIC_API_KEY` nor `OPENAI_API_KEY` is set | Permanent | Raises `OrchestratorError` before any LLM call | Does not attempt unauthenticated call |
| `DOUBLE_RUN` | Programming error | `run()` called on an Orchestrator already in `RUNNING` or `COMPLETE` state | Permanent | Raises `OrchestratorError` | Does not produce partial output |
| `SECRET_VALUE_LEAK` | Internal invariant violation | A tool output or LLM context is detected to contain an actual env var value or matched secret string | Must not occur; detected defensively | Raises `OrchestratorError`; aborts run | Does not write the leaking value to any output file |

---

## §8 Boundary Conditions

**`run(audit_request)`:**
- Empty string `""`: rejected — `INVALID_AUDIT_REQUEST`.
- Whitespace-only `"   "`: rejected — `INVALID_AUDIT_REQUEST`.
- Exactly 2000 characters: accepted.
- 2001 characters: rejected — `INVALID_AUDIT_REQUEST`.
- Request that produces exactly 2 subtasks after clamping: valid — run proceeds with 2 sub-agents.
- Request that produces 0 subtasks after unknown-type filtering: treated as `DECOMPOSITION_OUT_OF_BOUNDS`; Orchestrator falls back to dispatching all 4 specialist types.

**`probe_local_ports`:**
- Port already in use by the running process itself: reported as open.
- Port that accepts connection but immediately closes: reported as open.
- Connection refused: reported as closed.
- Timeout (> 2 seconds per port): reported as closed; `status: "error"` in ToolOutput.

**`scan_filesystem_for_secrets`:**
- Empty CWD (no files): returns empty list; `status: "ok"`.
- File with no read permission: skipped; counted in a `skipped_files` summary field.
- Symlink loop: followed at most once; loop detected and skipped on second encounter.
- Binary file: skipped; not scanned for patterns.

**`inspect_environment_variables`:**
- Empty environment: returns empty list; `status: "ok"`.
- Env var with empty-string value: included in output with name only; value MUST NOT be included.

**LLM decomposition returning exactly 1 subtask:** clamped up to 2 by duplicating the single subtask with a different specialist type chosen from the registry by the Orchestrator.

**LLM decomposition returning more than 4 subtasks:** first 4 (by order returned) are kept; remainder dropped.

---

## §9 Sentinel Values and Encoding Conventions

| Value | Location | Meaning | Does NOT mean |
|---|---|---|---|
| `null` in `SubAgentResult.error` | SubAgentResult | Sub-Agent completed without error | That findings are non-empty |
| `null` in `AuditTrailEntry.agent_id` | AuditTrailEntry | Entry is from the Orchestrator | That the entry lacks a source |
| `"Info"` severity | SubAgentResult, report | Either: (a) findings were present but low severity, or (b) sub-agent failed and returned graceful partial result | No findings at all; distinguish via `status` field |
| Empty `findings` array | SubAgentResult | Sub-Agent ran and found nothing of note | Sub-Agent failed; check `status` field |
| `status: "partial"` | SubAgentResult | Tools ran but LLM reasoning step failed; findings are raw tool summaries | Sub-Agent crashed; that is `status: "failed"` |

All strings in all output files MUST be UTF-8 encoded. No BOM. Unix line endings (`\n`).

---

## §10 Atomicity and State on Failure

**`audit_trail.jsonl` appends:** not atomic. Each `append()` flushes one entry to disk. A process kill between two appends leaves all prior entries intact and readable. The in-progress entry MAY be truncated. A truncated final line MUST be treated as absent by readers; it does not corrupt preceding entries.

**`report.md` write:** written in a single operation at run end. If the write fails midway (`OUTPUT_WRITE_FAILURE`): the file MAY be partially written. The Orchestrator does not delete the partial file. The caller can detect a partial write by checking that the file ends with the `## Audit Metadata` section.

**Ungraceful shutdown (process kill):**
- `audit_trail.jsonl`: all entries up to and including the last completed `append()` are intact and valid JSONL.
- `report.md`: MAY be absent or partial. No recovery is performed on next startup.
- No automatic recovery on restart. A new invocation starts a fresh run.

**Sub-Agent state on failure:** each Sub-Agent is a single-use concurrent task. If a Sub-Agent's task is cancelled (timeout), it leaves no shared mutable state. Tool calls that completed before cancellation have no side effects on the scanned environment.

---

## §11 Ordering and Sequencing

The following ordering MUST be preserved:

1. Validate `audit_request` and API key → 2. Open `audit_trail.jsonl` → 3. Append `run_start` → 4. Call LLM to decompose → 5. Append `decomposition` → 6. Launch all Sub-Agents concurrently → 7. Collect all SubAgentResults (with recovery as needed) → 8. Call LLM to synthesise → 9. Append `synthesis` → 10. Write `report.md` → 11. Append `run_end` → 12. Close `audit_trail.jsonl` → 13. Exit.

Steps 6 and 7 are concurrent across Sub-Agents; their internal tool and LLM calls are unordered relative to each other.

Step 4 (decompose) MUST complete before step 6 (launch). Step 7 (collect all results) MUST complete before step 8 (synthesise). Step 10 (write report) MUST complete before step 11 (run_end).

Within each Sub-Agent: Tools MUST be called before the Sub-Agent's LLM reasoning call. LLM reasoning MUST complete before the Sub-Agent returns its SubAgentResult.

---

## §12 Interaction Contracts

**Orchestrator → Sub-Agent:**
- The Orchestrator constructs each Sub-Agent instance with: `agent_id` (UUID), `agent_type` (string), and `audit_request` (the original request string, for LLM context only).
- The Orchestrator calls `run()` once per instance and awaits the returned SubAgentResult.
- The Orchestrator MUST cancel the sub-agent task after 45 seconds and treat cancellation as `SUBAGENT_TIMEOUT`.
- Resource ownership: the Orchestrator owns the event loop and the file handle; Sub-Agents own no shared resources.

**Sub-Agent → Tool:**
- Tools are called as regular synchronous function calls within the Sub-Agent's async task.
- A Tool MUST NOT modify filesystem state, kill processes, or open persistent connections.
- A Tool MUST complete or raise `ToolError` within 10 seconds. If a Tool does not return within 10 seconds, the Sub-Agent MUST raise `ToolError("timeout")`.
- Resource ownership: Tools own no state and hold no open handles on return.

**Sub-Agent → LLM Client:**
- Sub-Agent calls `LLMClient.call(system, user)` once.
- Sub-Agent MUST NOT pass raw secret values or matched secret strings in the `user` argument — only pattern category names and file paths.
- Cross-reference §16: the LLM Client is a shared stateless resource; Sub-Agents MUST NOT assume exclusive access.

**Orchestrator → AuditTrailWriter:**
- Only the Orchestrator calls `AuditTrailWriter.append()`. Sub-Agents return structured data; they do not write trail entries directly.

---

## §13 Concurrency and Re-entrancy

Sub-Agents MUST run concurrently. The implementation MUST use async coroutines (preferred) or threads; the orchestrator MUST NOT run Sub-Agents sequentially.

`LLMClient.call()` is re-entrant. Concurrent calls from multiple Sub-Agents are permitted. Each call is independent.

`AuditTrailWriter.append()` is NOT re-entrant. All calls MUST be serialised through the Orchestrator. Sub-Agents MUST NOT call `append()` directly.

Tool functions are stateless and re-entrant. Two Sub-Agents MAY call the same Tool function concurrently.

Sub-Agents MUST NOT share mutable state with each other. Each Sub-Agent operates on its own copy of inputs.

---

## §14 External Dependencies

| Dependency | Required | Absence behaviour |
|---|---|---|
| Anthropic or OpenAI LLM API | Required | `MISSING_API_KEY` before any call; `LLM_CALL_FAILURE` if unreachable at call time |
| Local filesystem (CWD, read access) | Required for SecretsSubAgent and ConfigSubAgent | `TOOL_EXECUTION_FAILURE` per file; Sub-Agent continues with zero findings |
| TCP stack (localhost port probe) | Required for PortsSubAgent | `TOOL_EXECUTION_FAILURE` if all probes fail; Sub-Agent returns graceful partial |
| OS environment (`os.environ`) | Required for EnvSubAgent | If `os.environ` is empty: valid — returns empty findings |
| `fixtures/` directory | Optional | If absent: SecretsSubAgent and ConfigSubAgent scan only the CWD root and existing subdirectories |
| Python 3.11+ | Required | Not checked at runtime; assumed by §22 |

---

## §15 Configuration

All configuration is via environment variables. No config file.

| Variable | Required | Default | Valid values | Effect |
|---|---|---|---|---|
| `ANTHROPIC_API_KEY` | One of these two is required | — | non-empty string | Selects Anthropic as LLM provider |
| `OPENAI_API_KEY` | One of these two is required | — | non-empty string | Selects OpenAI as LLM provider; if both set, Anthropic takes precedence |
| `MASP_MODEL` | Optional | `claude-sonnet-4-6` (Anthropic) or `gpt-4o` (OpenAI) | any string | Model name passed to the selected provider |
| `MASP_MAX_TOKENS` | Optional | `1024` | integer 1–4096 | Max tokens per LLM response |
| `MASP_TIMEOUT_SECS` | Optional | `45` | integer 10–120 | Per-sub-agent timeout in seconds |

If both `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` are set, Anthropic is used. `OPENAI_API_KEY` is ignored.

---

## §16 Extension Contracts

**Extension point: Sub-Agent specialisation.**

A conformant specialist Sub-Agent MUST:
1. Extend `BaseSubAgent`.
2. Override `run() -> SubAgentResult` as a coroutine.
3. Return a `SubAgentResult` in all code paths — never raise past the method boundary.
4. Call at least one Tool function before calling the LLM.
5. Not pass secret values or matched secret strings to the LLM.
6. Not write to `audit_trail.jsonl` directly.
7. Complete within the timeout configured in `MASP_TIMEOUT_SECS`.

A conformant specialist Sub-Agent MUST NOT:
- Modify the filesystem, terminate processes, or open network connections outside of Tool functions.
- Call other Sub-Agents.
- Hold state between two separate `run()` invocations (the second call raises per §6).

**Extension point: Tool functions.**

A conformant Tool function MUST:
1. Be a pure function with no side effects on the scanned environment.
2. Raise `ToolError` on failure; not raise any other exception type.
3. Return within 10 seconds or raise `ToolError("timeout")`.
4. Return a value serialisable to JSON.

Cross-reference §12: Sub-Agents own the call; Tools own no shared resources on return.

Adding a new specialist to the closed registry (§2b) requires updating the registry in the Orchestrator's dispatch logic. Adding a new Tool requires no Orchestrator changes.

---

## §17 Error Propagation

| Failure mode | Raised by | Caught by | Action taken | Reaches caller? |
|---|---|---|---|---|
| `INVALID_AUDIT_REQUEST` | Orchestrator (validation) | — | `OrchestratorError` raised; process exits 1 | Yes (exit code 1) |
| `MISSING_API_KEY` | Orchestrator (startup) | — | `OrchestratorError` raised; process exits 1 | Yes (exit code 1) |
| `OUTPUT_WRITE_FAILURE` | AuditTrailWriter / report write | Orchestrator | `OrchestratorError` raised; process exits 1 | Yes (exit code 1) |
| `LLM_CALL_FAILURE` (decompose) | LLM Client | Orchestrator | Run aborts; `OrchestratorError` raised | Yes (exit code 1) |
| `LLM_CALL_FAILURE` (synthesise) | LLM Client | Orchestrator | Executive summary replaced with "Synthesis unavailable"; report still written; exits 0 | No (exit code 0) |
| `LLM_CALL_FAILURE` (reasoning) | LLM Client | BaseSubAgent | SubAgentResult status set to `"partial"`; findings = raw tool summaries | No |
| `TOOL_EXECUTION_FAILURE` | Tool | BaseSubAgent | Recorded in `tool_outputs`; Sub-Agent continues | No |
| `SUBAGENT_TIMEOUT` | Orchestrator (timeout) | Orchestrator | Retry once; if timeout again → graceful partial result | No |
| `UNRECOVERABLE_SUBAGENT_FAILURE` | BaseSubAgent | Orchestrator | Retry once; if fails again → graceful partial result | No |
| `ALL_SUBAGENTS_FAILED` | Orchestrator (post-collection) | — | Report written with all-failed content; exits 0 | No (exit code 0) |
| `SECRET_VALUE_LEAK` | Orchestrator (defensive check) | — | `OrchestratorError`; run aborts; exits 1 | Yes (exit code 1) |
| `UNKNOWN_AGENT_TYPE` | Orchestrator (decompose) | Orchestrator | Type dropped silently; logged in trail | No |

---

## §18 Observability Contract

**`audit_trail.jsonl`** is the primary observability surface. Requirements:
- MUST contain at minimum: `run_start`, `decomposition`, one `agent_start` + `agent_end` per Sub-Agent, `synthesis`, `run_end`.
- MUST contain one `tool_call` entry per Tool invocation.
- MUST contain one `llm_call` entry per LLM API call.
- MUST contain `agent_retry` for each retry attempt.
- MUST contain `agent_recovery` for each graceful partial substitution.
- MUST be valid JSONL throughout (each line independently parseable).

**What MUST NOT be logged:**
- Environment variable values.
- Matched secret strings or file contents.
- LLM prompt or response text.
- Any value that could be a credential.

**stderr:** the process MAY write human-readable progress messages to stderr. These are not a contractual observability surface and their format is unspecified.

**No metrics, no structured logging beyond `audit_trail.jsonl`, no remote telemetry.**

---

## §19 Security Properties

**Input sanitisation:** the Audit Request string is passed to the LLM as user content. It MUST NOT be interpolated into shell commands, file paths, or system prompts in a way that allows prompt injection to cause filesystem writes, process execution, or exfiltration.

**Secret value handling:**
- Matched secret strings (regex match content) MUST NOT appear in: LLM prompts, `audit_trail.jsonl`, `report.md`.
- Environment variable values MUST NOT appear in: LLM prompts, `audit_trail.jsonl`, `report.md`.
- Only: file paths, env var names, pattern category names, and port numbers are permitted in LLM context and output files.

**Scope limitation:** Tools MUST operate read-only. No Tool MUST write, delete, or execute anything in the scanned environment.

**LLM output trust:** LLM responses are treated as untrusted structured text. The Orchestrator MUST validate that decomposition output matches the closed registry before dispatch. Invalid LLM output triggers `UNKNOWN_AGENT_TYPE` or `DECOMPOSITION_OUT_OF_BOUNDS`; it never causes code execution.

**What is NOT guaranteed:**
- The system does not guarantee detection of all secrets or vulnerabilities.
- The system does not guarantee the LLM's severity ratings are accurate.
- The system is not a substitute for a full security audit.

---

## §20 Versioning and Evolution

**Spec version:** 1.0.0. Substantive changes MUST bump the version and be recorded in a CHANGELOG section.

**`audit_trail.jsonl` format:** version 1. The `event_type` set is declared closed in this version. Adding a new `event_type` is a minor version bump. Changing field names or removing fields is a major version bump.

**SubAgentResult schema:** version 1. Adding optional fields is a minor version bump. Removing or renaming required fields is a major version bump.

**Sub-agent registry:** adding a new specialist type is a minor version bump. Removing a type is a major version bump.

**`report.md` structure:** the required section sequence is stable. Additional sections MAY be added after `## Audit Metadata` without a version bump.

**CLI interface (`python main.py "<request>"`):** stable. The positional argument contract MUST NOT change without a major version bump.

---

## §21 What Is Not Specified

The following are deliberately unspecified and left to the implementor:

- The specific regex patterns used by `scan_filesystem_for_secrets` — any reasonable set of patterns for common secret types is conformant.
- The exact wording of LLM system prompts and user messages, beyond the constraints in §12 and §19.
- The specific fields returned by individual Tool functions within the `summary` string.
- The severity label chosen by LLM reasoning for any specific finding.
- How the implementation constructs concurrency (asyncio tasks vs. thread pool), provided the concurrency guarantee in §13 is met.
- The LLM model used, beyond defaults in §15.
- The order in which Sub-Agent sections appear in `report.md` (beyond the required top-level structure).
- Port probe technique (TCP connect vs. other) provided it is read-only and reports open/closed accurately.

---

## §22 Assumptions

| Assumption | Detectable if violated? |
|---|---|
| Python 3.11 or later is available. | Yes — import errors or syntax errors at startup. |
| The LLM API endpoint is reachable over the network. | Yes — `LLM_CALL_FAILURE` on first call. |
| The CWD is readable by the running process. | Yes — `TOOL_EXECUTION_FAILURE` on first scan. |
| The CWD is writable (for output files). | Yes — `OUTPUT_WRITE_FAILURE` on first write attempt. |
| The running process has TCP socket capability for localhost. | Yes — `TOOL_EXECUTION_FAILURE` on first port probe. |
| The caller does not pass a crafted audit request designed to exfiltrate secrets via prompt injection. | Partially — the system limits what reaches the LLM, but cannot detect all injection attempts. |
| The system is invoked interactively by a trusted operator, not exposed as a web endpoint or daemon. | No — if exposed as a service, the security properties in §19 are insufficient. |
| `fixtures/` directory, if present, contains non-production secrets (example/dummy values only). | No — the system will report fixtures findings at face value. |

---

## §23 Performance Contracts

The following are correctness contracts, not aspirational targets:

| Contract | Threshold | Effect of violation |
|---|---|---|
| Total run duration | MUST complete within 60 seconds from CLI invocation to exit | Defines the outer wall-clock budget |
| Per-sub-agent timeout | MUST be at most 45 seconds (configurable via `MASP_TIMEOUT_SECS`) | Exceeded → `SUBAGENT_TIMEOUT` → recovery flow |
| Per-LLM-call timeout | MUST be at most 30 seconds | Exceeded → `LLM_CALL_FAILURE` after one retry |
| Per-tool timeout | MUST be at most 10 seconds | Exceeded → `ToolError("timeout")` |

The 45-second sub-agent timeout + 2 sub-agents sequential (worst case: retry of slowest) + 30-second synthesis call fits within 60 seconds only if the retry is not universally triggered. The implementation MUST ensure concurrent Sub-Agent execution (§13) so that the common case (no retries) completes well under 60 seconds.

---

*End of specification. Version 1.0.0.*
