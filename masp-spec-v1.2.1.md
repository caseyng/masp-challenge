```markdown
# Specification Contract: Multi-Agent Security Pipeline (MASP) — REVISION 1.2.1

**Spec Version:** 1.2.1
**Status:** READY FOR IMPLEMENTATION HANDOFF
**Based on Challenge:** masp-challenge.md

---

## §1 Purpose and Scope

**Purpose:** This system accepts a natural-language security audit request from a CLI, orchestrates concurrent execution of 2–4 specialised sub-agents (each with local tool access and LLM reasoning), aggregates their findings, and produces a structured security audit report (`report.md`) with a complete machine-readable audit trail (`audit_trail.jsonl`). Error recovery is mandatory: any sub-agent failure MUST NOT crash the overall run.

**One thing this system does that nothing else does:** It combines concurrent specialised security agents (filesystem, ports, env vars, patterns) with an orchestrator that performs decomposition, recovery, and synthesis — all observable via a structured audit trail.

**What would break if this system were removed:** No single-purpose script currently provides concurrent multi-agent security scanning with LLM synthesis and mandatory error recovery in under 60 seconds.

**Adjacent problems deliberately not solved:**
- Remote host scanning (only local environment)
- Remediation or automatic fixing (audit only)
- Persistent state across runs (stateless per invocation)
- Authentication or multi-user isolation (single caller, single run)
- Real-time monitoring or daemon mode (CLI batch only)

**Design principles:**
1. Failures MUST be observable, not silent. Every error MUST appear in `audit_trail.jsonl` with enough detail to debug.
2. Sub-agents MUST be independent. No sub-agent MAY depend on another's output.
3. The orchestrator MUST complete even if every sub-agent fails (graceful degradation).
4. No mock tools in final submission. Every sub-agent MUST invoke a real local operation.

---

## §2 Concepts and Vocabulary

| Term | Operational Definition | Distinction from Related Terms |
|---|---|---|
| Orchestrator | The top-level agent that decomposes the user request, dispatches sub-agents, aggregates results, and synthesises the final report. | Not a sub-agent. Has no tool of its own except LLM calls. |
| Sub-agent | A specialised agent that: (a) receives a named subtask from the orchestrator, (b) invokes exactly one tool, (c) calls an LLM to reason about tool output, (d) returns a structured JSON result. | Not the orchestrator. Does not decompose further. |
| Tool | A local operation (filesystem scan, port probe, env var inspection, pattern match) that a sub-agent invokes. Each invocation produces raw output (string or JSON). | Not an LLM call. Not a sub-agent. |
| Audit trail | A JSON Lines file (`audit_trail.jsonl`) with one JSON object per event. Events include: agent start/end, tool call (with arguments/result), LLM call (with prompt/response summary), error, recovery action. | Not the final report. Not log output to stdout. |
| Recovery action | An action the orchestrator takes when a sub-agent fails: retry (once) or substitute a graceful partial result. MUST be logged with the failure it recovers from. | Not a silent ignore. Not a crash. |
| Structured result | A sub-agent's returned JSON containing: `subtask_name`, `success` (bool), `findings` (string or object), `severity` (Critical/High/Medium/Low/Info), `tool_output_summary` (string). | Not free text. Not raw tool output. |
| Final report | `report.md` containing: original request, one section per sub-agent (findings + severity), executive summary synthesised by orchestrator's final LLM call. | Not the audit trail. Not raw JSON. |
| Decomposition | The process by which the orchestrator's initial LLM call breaks the user's natural-language request into 2–4 named subtasks with descriptions. | Not a sub-agent action. Not tool invocation. |
| Graceful degradation | The property that the orchestrator completes and writes both output files even when some or all sub-agents fail. | Not error recovery (which is a mechanism). Graceful degradation is the outcome. |
| Catch-all | A substitution mechanism: when decomposition produces a subtask name with no matching registered sub-agent, the orchestrator substitutes a partial result with findings="Unhandled subtask type: {name}" and severity Info. | Not a sub-agent. Not a retry. |

**Named exception types (caller-side — may be raised by system or used by caller for handling):**

| Exception Name | Operational Definition | When System Raises It | Distinct From |
|---|---|---|---|
| OrchestrationError | Decomposition or orchestration failed irrecoverably. | Orchestrator's LLM call fails to produce valid decomposition (malformed JSON, missing subtasks, fewer than 2 subtasks) after 1 retry. | Sub-agent failures (handled via recovery, not this exception). |
| ToolExecutionError | A tool call failed (file not found, port probe timeout, permission denied). | Sub-agent catches tool exception and wraps in this before returning `success=false`. Never raised to top-level caller. | LLM inference errors. |
| LLMTimeoutError | An LLM call exceeded the configured timeout. | Sub-agent or orchestrator catches timeout and raises this internally before retry. Never raised to top-level caller. | Tool timeout (separate). |
| AggregationError | Final synthesis LLM call failed after retry. | Orchestrator raises this internally, catches it, writes partial report with `synthesis_success=false`. Never raised to top-level caller. | Sub-agent result parsing errors (logged but non-fatal). |

---

## §2b Architectural Constraints

```

[Component hierarchy]:

· Orchestrator owns all Sub-agent instances. Orchestrator creates, starts, and collects from Sub-agents. Sub-agents do not own each other.
· Sub-agents are ephemeral: created per subtask, destroyed after result collection.

[Structural roles]:

· Orchestrator: standalone class. Does not extend anything. Holds a list of Sub-agent instances.
· Sub-agent: abstract base class (or protocol) with method run(subtask: dict) -> dict. Concrete sub-classes: FileScanSubAgent, PortProbeSubAgent, EnvInspectSubAgent, PatternMatchSubAgent.

[Ordering rule (structural, not pipeline)]:

· Sub-agent registry: order of registration determines dispatch order for concurrent execution (concurrency is concurrent start, not sequential). No priority ordering beyond "all start at once".

[Named patterns]:

· Registry pattern: The orchestrator maintains a registry mapping subtask names to sub-agent classes. Registration MUST happen before orchestration.
· Catch-all: If decomposition produces a subtask with no matching registered sub-agent, orchestrator MUST substitute a graceful partial result indicating "unhandled subtask type" — not crash.

[Inheritance prohibition]:

· Sub-agent concrete classes MUST NOT inherit from Orchestrator.
· Orchestrator MUST NOT inherit from Sub-agent.

[Concurrency model constraint]:

· Concurrency MUST be implemented using asyncio (not threading). All tool calls MUST be async or wrapped in asyncio.to_thread() to avoid GIL contention. The event loop MUST be single-threaded.
· Reason: Threading introduces GIL limits for IO-bound tools and complicates cancellation for timeout enforcement.

```

No architectural constraints beyond those implied by §5 component contracts beyond the above.

---

## §3 System Boundary

**Inputs:**

| Input | Type | Valid Range | Invalid Input Handling | Null/Empty Meaning |
|---|---|---|---|---|
| Audit request (CLI argument) | String | 1–5000 chars, printable UTF-8 | If empty string: treated as DECOMPOSITION_FAILED — raises OrchestrationError, report.md is written with error notice and synthesis_success=false, audit trail written, exit code 1. If >5000 chars: truncate to 5000 with warning in audit trail. | N/A (CLI argument always present as string, may be empty) |

**Outputs:**

| Output | Type | Possible Values | Guarantees |
|---|---|---|---|
| `report.md` | Markdown file | Always written (even on partial failure or 60s timeout). Contains original request. If synthesis fails: includes "Synthesis failed — raw sub-agent results follow" section. On 60s timeout: includes notice identifying cancelled sub-agents. File is written atomically using `pathlib.Path.replace()`. | Always written. |
| `audit_trail.jsonl` | JSON Lines file | One JSON object per line. Each object has `timestamp_iso`, `event_type`, `agent_name` (if applicable), `details`. Written incrementally (flush after each event). On crash: events up to crash are preserved. | Written incrementally. |
| Exit code | Integer | `0` (success or partial success), `1` (orchestration error before any sub-agent dispatch, including empty request — report.md still written), `2` (aggregation error but report written), `3` (report write failure after retry), `4` (audit trail write failure after retry) | Process exits with code after all cleanup. |

**Side effects:**
- Reads from local filesystem (cwd or specified paths via tool)
- Scans network ports on localhost (or configured interface)
- Reads environment variables
- Writes `report.md` and `audit_trail.jsonl` to current working directory (overwrites existing files)

**Idempotency:** NOT guaranteed. Running twice with same request MAY produce different results (file system may change, ports may open/close). Each run is independent.

**Delivery semantics:** Not applicable (no streams/queues — each run is a single batch).

**Caller types:** Single caller (the human operator via CLI). No multi-caller contracts.

---

## §4 Data Contracts

**Sub-agent result JSON (returned to orchestrator):**

```json
{
  "subtask_name": "string (required, matches assigned name)",
  "success": "boolean (required)",
  "findings": "string or object (required, human-readable or structured)",
  "severity": "enum('Critical','High','Medium','Low','Info') (required, if success=false MUST be 'Info' with explanation)",
  "tool_output_summary": "string (required, first 500 chars of raw tool output)",
  "error_details": "string (optional, present only if success=false)"
}
```

Unknown fields: orchestrator MUST ignore them (forward compatibility). Caller (orchestrator) does not produce unknown fields.

Audit trail event object (one per line):

```json
{
  "timestamp_iso": "2024-01-01T12:00:00.123456Z",
  "event_type": "enum('orchestrator_start','orchestrator_end','subagent_start','subagent_end','tool_call','llm_call','error','recovery')",
  "agent_name": "string (optional, present for subagent events)",
  "details": "object (schema varies by event_type)",
  "run_id": "string (UUID per invocation, same for all events in a run)"
}
```

tool_call event details schema:

```json
{
  "tool_name": "string",
  "arguments_summary": "string (first 200 chars of serialized arguments)",
  "result_summary": "string (first 500 chars of raw tool output or error message)",
  "duration_ms": "float",
  "success": "boolean"
}
```

Unknown fields: MUST NOT be emitted. Consumers MAY ignore. Event schemas are stable per spec version.

Version negotiation: Not applicable (no version negotiation between producer/consumer — audit trail is consumed offline by human or debugger).

Encoding: UTF-8, no BOM. JSON Lines: each line is a valid JSON object, \n separated.

---

§5 Component Contracts

Component Hierarchy

```
Orchestrator
  ├── FileScanSubAgent
  ├── PortProbeSubAgent
  ├── EnvInspectSubAgent
  └── PatternMatchSubAgent
```

---

Component: Orchestrator

Purpose: Decompose user request, dispatch sub-agents concurrently, aggregate results, synthesise final report.

Stateful or stateless: Stateless — holds no mutable state between runs. Holds configuration (timeouts, registered sub-agent classes) but those are immutable after construction.

Invariants:

· None — stateless.

Preconditions for run(request: str) -> dict:

· request is a non-None string (may be empty — handled as DECOMPOSITION_FAILED per §8).
· request length ≤ 5000 chars (if longer, truncated per §3).
· Violation behaviour: if request is None, raise OrchestrationError("request cannot be None"). If >5000, truncate and log warning to audit trail — does not raise.

Accepts:

· request: str — any printable UTF-8, 0–5000 chars (post-truncation).

Returns (success case):

· dict with keys: report_path (str), audit_path (str), subagent_results (list of result dicts per §4), synthesis_success (bool).

Postconditions:

· After run() returns or raises: report.md and audit_trail.jsonl exist in cwd (may be partial if crash before write).
· report.md contains original request verbatim in a "Original Request" section.
· On 60-second timeout: report written with partial results and cancellation notice. synthesis_success may be false if aggregation was skipped.

Guarantees:

· MAY raise OrchestrationError if initial decomposition LLM call fails after 1 retry or returns fewer than 2 subtasks (including empty request). Report.md is still written.
· MAY raise AggregationError internally but catches it and writes partial report (never surfaces to caller).
· Always writes audit_trail.jsonl with at minimum: orchestrator_start, orchestrator_end (or error if crash before end).
· Always writes report.md within 60 seconds — on timeout, writes with partial results and cancellation notice.

Configuration fields read:

· LLM_API_KEY — required for all LLM calls
· LLM_MODEL — model selection
· LLM_TIMEOUT_SEC — timeout for decomposition and synthesis calls
· MAX_SUBTASKS — upper bound on subtask count
· AUDIT_TRAIL_PATH — output path for audit trail

Failure behaviour references §7:

· DECOMPOSITION_FAILED: raises OrchestrationError. Report.md is always written with error notice and synthesis_success=false. Writes audit trail with error. Exit code 1.
· AGGREGATION_FAILED: writes report with raw sub-agent results, synthesis_success=false, exit code 2.

---

Component: SubAgent (abstract base)

Purpose: Execute a single subtask using one tool + one LLM reasoning call.

Stateful or stateless: Stateless — each instance used once.

Invariants:

· None — stateless.

Preconditions for run(subtask: dict) -> dict:

· subtask contains key name (str) and description (str).
· Violation behaviour: return success=false with error_details "invalid subtask format".

Accepts:

· subtask: dict with at least name and description.

Returns:

· Structured result per §4 schema.

Postconditions:

· Tool called exactly once (unless tool raises, then logged as error and returns success=false).
· LLM called exactly once (unless LLM call fails, then returns success=false with error_details).

Guarantees:

· Never raises exception to caller (orchestrator). All exceptions caught and converted to success=false result.
· tool_output_summary never exceeds 500 chars.

Configuration fields read:

· TOOL_TIMEOUT_SEC — timeout for tool execution
· LLM_TIMEOUT_SEC — timeout for LLM reasoning call

Failure behaviour references §7:

· TOOL_FAILURE: returns success=false with error_details containing exception class and message.
· LLM_FAILURE: returns success=false with error_details.
· TIMEOUT: treated as LLM_FAILURE or TOOL_FAILURE depending on which timed out.

---

Component: FileScanSubAgent (concrete)

Purpose: Scan files for secret patterns (keys, tokens, passwords).

Stateful or stateless: Stateless.

Invariants: None.

Preconditions: None beyond base.

Accepts: subtask with optional paths (list of strings, default = ["."]) and patterns (list of regex strings, default = built-in secret patterns).

Tool used: scan_files(paths, patterns) — recursive scan, returns list of matches with file path, line number, matched text.

Returns: Structured result per §4. Findings contain matched files (top 10) with severity based on pattern type (Critical for private keys, High for API keys, etc.).

Guarantees: Does not modify files.

---

Component: PortProbeSubAgent (concrete)

Purpose: Detect open TCP ports on localhost.

Stateful or stateless: Stateless.

Preconditions: None.

Accepts: subtask with optional ports (list of ints, default common ports 22,80,443,3000,8000,8080) and timeout_seconds (float, default 1.0).

Tool used: probe_ports(port_list, timeout) — socket connect attempts, returns list of open ports with service name guess.

Returns: Structured result. Severity: Critical if 22,443,3389 open without expected service; High if unexpected high-numbered ports open.

Guarantees: Does not send data, only connect/disconnect.

---

Component: EnvInspectSubAgent (concrete)

Purpose: Inspect environment variables for secrets or misconfigurations.

Stateful or stateless: Stateless.

Preconditions: None.

Accepts: subtask with optional sensitive_names (list of substrings, default=["KEY","SECRET","PASS","TOKEN"]).

Tool used: inspect_env(sensitive_names) — reads os.environ, redacts values but flags variable names matching patterns.

Returns: Structured result. Severity: Critical if AWS/API keys exposed, High if database passwords in env, Medium if generic SECRET vars.

Guarantees: Does not log full environment variable values to audit trail (only names and redacted "present/absent").

---

Component: PatternMatchSubAgent (concrete)

Purpose: Search config files for dangerous patterns (hardcoded credentials, unsafe defaults).

Stateful or stateless: Stateless.

Preconditions: None.

Accepts: subtask with optional file_patterns (list of globs, default=[".yaml",".json",".conf",".ini","*.toml"]).

Tool used: grep_patterns(file_patterns, patterns) — searches files matching patterns for regex list.

Returns: Structured result. Severity: High for hardcoded credentials, Medium for unsafe defaults (debug=true, allow_any_cors, etc.).

Guarantees: Does not modify files.

---

§6 Lifecycle

Stateless components (Orchestrator, all SubAgents) — no lifecycle to specify beyond:

· Construction: initialise configuration (timeouts, registered agents, LLM client).
· After construction: ready to call run() immediately.
· No close() required. Python GC handles.

---

§7 Failure Taxonomy

Distinction: Failure = system cannot produce any defined outcome for a subtask or overall run. Defined operational outcome = success=false with structured result (sub-agent) or partial report (orchestrator). Failures are only at orchestration level where no report can be produced.

Failure Name Category Meaning Recoverability Information Carried Representation What is NOT done
DECOMPOSITION_FAILED Operational (LLM) Orchestrator's LLM call returns malformed JSON, missing subtasks, or fewer than 2 subtasks after 1 retry (including empty request) Permanent for this input LLM response (truncated), retry count Exception raised (OrchestrationError) Does not skip report.md writing — report is always written (with error notice and synthesis_success=false)
TOOL_FAILURE Operational (local) Tool raises exception (file not found, permission denied, timeout) Retry once for same sub-agent Exception class, message, tool name Sub-agent result success=false Does not crash orchestrator
LLM_FAILURE Operational (remote) LLM call times out or returns invalid response Retry once for same call Error type, duration, model Sub-agent result success=false (or orchestrator retries then DECOMPOSITION_FAILED) Does not expose raw API key in audit trail
TIMEOUT Operational Tool or LLM exceeds configured timeout Retry once Which timeout, duration, threshold Same as TOOL_FAILURE or LLM_FAILURE Does not hang indefinitely
AGGREGATION_FAILED Operational (LLM) Orchestrator's final synthesis LLM call fails after 1 retry Permanent for this run (but report still written) LLM response, retry count, sub-agent results (still available) Returns from run() with synthesis_success=false; report written with raw results Does not prevent report.md from being written
REPORT_WRITE_FAILURE Operational (filesystem) Cannot write report.md after retry (permission denied, disk full, invalid path) Retry once with different path (.report.md.tmp then rename), then permanent Path, error message, retry count Exit code 3, writes error to audit trail, no report.md Does not crash with unhandled IOError
AUDIT_TRAIL_WRITE_FAILURE Operational (filesystem) Cannot write to audit_trail.jsonl (permission denied, disk full, invalid path) Retry once with same path (flush and retry), then permanent Path, error message, retry count Exit code 4, no audit trail written, system exits immediately Does not proceed without audit trail
RECOVERY_FAILURE Operational (logic) A sub-agent retry fails after the first recovery attempt (retried sub-agent returns success=false again) No further retry — substitute partial result Original error, retry error, subtask name Orchestrator substitutes success=false result with findings="Sub-agent failed after retry: {error}" Does not retry twice; does not crash
INTERNAL_INVARIANT Internal invariant violation A condition that should be impossible occurs (e.g., sub-agent returns success=false but no error_details) Not recoverable — bug in system Assertion message, component, state Exception raised (crash) This MUST NOT happen in correct implementation

This set is closed. No future failure modes will be added without a major spec version increment.

Handling contract for unknown values: Not applicable (set is closed).

---

§8 Boundary Conditions

Orchestrator.run():

Condition Behaviour
Empty request string ("") DECOMPOSITION_FAILED. Orchestrator raises OrchestrationError. Report.md is written containing an error notice and synthesis_success=false. Audit trail written with orchestrator_start, error event, and orchestrator_end. Exit code 1.
Request containing only whitespace Same as empty string (after strip).
Request >5000 chars Truncated to 5000 chars. Warning logged to audit trail. Proceed with truncated request.
Decomposition returns 0 subtasks DECOMPOSITION_FAILED. Report.md written.
Decomposition returns 1 subtask DECOMPOSITION_FAILED (minimum 2 required). Report.md written.
Decomposition returns >4 subtasks Truncate to first 4, log warning to audit trail.
Decomposition returns exactly 2–4 subtasks Proceed to dispatch.
Decomposition produces subtask with no matching registered sub-agent Catch-all: substitute partial result with findings="Unhandled subtask type: {name}", severity Info.
Sub-agent returns success=false Orchestrator logs error, attempts recovery. Recovery selection: retry once if failure is TIMEOUT or TOOL_FAILURE with a transient error; otherwise substitute partial result with findings="Sub-agent failed: {error_details}" and severity Info.
Transient error definition Errors where retry has a reasonable chance of success on second attempt. Includes: ConnectionRefusedError, TimeoutError, ResourceBusyError, BrokenPipeError, socket.timeout, errno.EAGAIN, errno.EWOULDBLOCK, errno.EBUSY. Does NOT include: FileNotFoundError, PermissionError, IsADirectoryError, ValueError (invalid input), TypeError.
Recovery action (retry) fails again (sub-agent returns success=false on retry) RECOVERY_FAILURE. Substitute partial result. Do not retry twice. Log both failures to audit trail.
All sub-agents return success=false Still runs aggregation LLM with all failures. Report includes "All sub-agents failed" executive summary.
Aggregation LLM returns empty string Write report with "Synthesis produced no content" and raw results. synthesis_success=false.
Sub-agent returns success=true but missing required field (severity or findings) Treat as success=false with error_details "Malformed result: missing field X". Log to audit trail.
Audit trail write fails during run AUDIT_TRAIL_WRITE_FAILURE. Retry once with same path (flush and retry). If retry fails, exit with code 4. Do not continue without audit trail.
Overall 60-second deadline reached All in-flight sub-agents and LLM calls are cancelled via asyncio task cancellation. Results collected up to cancellation point are used. Aggregation runs on available partial results (or skipped if none completed). Report written with section noting which sub-agents did not complete. synthesis_success may be false if aggregation was skipped. Exit code 0 if report written, or 2 if aggregation failed. Full audit trail up to cancellation point.

Sub-agent.run() (all concrete types):

Condition Behaviour
Tool returns empty result (no findings) success=true, findings="No issues found", severity="Info"
Tool raises FileNotFoundError success=false, error_details includes path that wasn't found
Tool raises PermissionError success=false, error_details includes "permission denied"
LLM returns malformed JSON (when parsing expected) success=false, error_details includes "LLM returned invalid response format"
LLM call takes >timeout_seconds Raise timeout internally → success=false, error_details "LLM timeout after N seconds"

---

§9 Sentinel Values and Encoding Conventions

Sentinel Where Used Meaning Does NOT Mean
null (JSON) Sub-agent result error_details when success=true No error occurred "Error details present but null" (not used)
"" (empty string) findings field No findings or summary unavailable "Findings exist but were omitted"
"Info" severity when success=false Failure is informational, not a security finding The failure is not a finding (correct)
None (Python) Not used in public boundaries N/A N/A
⚠️ "Synthesis failed — raw sub-agent results below" report.md header when aggregation fails Indicates synthesis LLM failed, raw results follow Not a real security finding
"Sub-agents cancelled at 60s deadline" report.md section on overall timeout Indicates which sub-agents were cancelled, results up to cancellation point are included Not a sub-agent failure

---

§10 Atomicity and State on Failure

Stateless components — no mutable state. §10 not applicable for component state.

File writes (report.md, audit_trail.jsonl):

· audit_trail.jsonl: each event appended immediately with flush. If write fails (IOError, PermissionError, disk full), retry once immediately with same path. If retry fails, raise AUDIT_TRAIL_WRITE_FAILURE and exit code 4. No partial writes — previous events up to last successful flush are preserved.
· report.md: written atomically using pathlib.Path.replace() (atomic on POSIX and Windows). If write fails, retry once with different path (report.md.tmp then replace). If retry succeeds, continue normally (exit code 0). If retry fails, raise REPORT_WRITE_FAILURE and exit code 3.

Ungraceful shutdown (process kill, power loss):

· audit_trail.jsonl: events up to last flush are preserved. Last line may be incomplete (truncated). No recovery on next startup — operator must inspect manually.
· report.md: may be missing if crash before write. Operator re-runs.
· System does not perform automatic recovery on next startup (intentional — each run is independent).

---

§11 Ordering and Sequencing

Pipeline steps (sequential in orchestrator):

1. Decompose (LLM call) → produces subtask list. MUST precede dispatch because dispatch depends on subtasks.
2. Dispatch concurrent sub-agents (asyncio.gather). Order within concurrency not specified.
3. Collect results (wait for all sub-agents to complete or fail). Postcondition: all sub-agents have terminated (success or failure).
4. Aggregate + synthesise (LLM call) → produces final report. MUST follow collection because it depends on all results.
5. Write files (report.md, audit_trail.jsonl). MUST follow synthesis.

Correctness reason for ordering: Step 4 cannot run before Step 3 completes because synthesis requires all sub-agent results. Step 1 must precede Step 2 because dispatch list comes from decomposition. On 60-second timeout, steps 2–4 may be truncated — step 5 always executes with whatever results are available.

If order can be changed without correctness impact: None — changing any step order would break dependencies.

---

§12 Interaction Contracts

Orchestrator ↔ Sub-agent:

· Initiator: Orchestrator (caller), Sub-agent (callee)
· Caller guarantees before calling run(subtask): subtask contains valid name and description. Orchestrator has registered a sub-agent class for this subtask name via exact string match on subtask["name"].
· Callee guarantees after returning: Result dict matches §4 schema. Sub-agent no longer holds resources (files open, sockets).
· Resource ownership: Orchestrator creates sub-agent instances. Sub-agent does not own shared resources beyond its tool call (file handles closed after tool returns). Orchestrator does NOT close sub-agents (GC handles).
· If interaction fails midway: Sub-agent catches all exceptions, returns success=false result. Orchestrator does not retry the same instance (creates new instance on retry). Orchestrator is never left in undefined state because it only reads the result dict.

Orchestrator ↔ LLM (decomposition and synthesis):

· Initiator: Orchestrator, LLM API (callee)
· Caller guarantees: API key valid (from env), request size ≤ model context (8000 tokens max)
· Callee guarantees: Response returned within timeout (15s) or raised exception
· Resource ownership: HTTP connection pool managed by SDK. Orchestrator does not manually close.
· If interaction fails: Orchestrator retries once. If second fails, DECOMPOSITION_FAILED (decomposition) or AGGREGATION_FAILED (synthesis).

Callback contracts: No callbacks (system does not accept caller-supplied handlers).

---

§13 Concurrency and Re-entrancy

Orchestrator: Not thread-safe. MAY be called from single thread only. Concurrent calls from multiple threads produce RuntimeError (explicit check at entry) — not undefined behaviour.

Sub-agent: Not thread-safe. Each instance called once from orchestrator's event loop. No concurrent calls to same instance.

Tool calls: Each tool runs in the same thread as the sub-agent (no internal parallelism within a sub-agent). Tools themselves are not re-entrant across different sub-agents — they access global resources (filesystem, ports, env). This is safe because sub-agents run concurrently but each tool accesses read-only resources (no write contention).

Re-entrancy: Not applicable — no callbacks.

Cross-reference §22: Assumes single-threaded caller. This section makes concurrent calls raise RuntimeError — consistent.

---

§14 External Dependencies

Dependency Provides Required? Absence Behaviour (startup) Runtime Absence Behaviour
LLM API (OpenAI/Anthropic) Decomposition, reasoning, synthesis Yes Orchestrator fails with OrchestrationError immediately on first API call If API becomes unavailable mid-run: fails current LLM call, retries once, then DECOMPOSITION_FAILED
Local filesystem (cwd) Reading files for scans, writing report/audit Yes System checks os.access(cwd, os.W_OK) at start; fails with error message if not writable If report write fails: REPORT_WRITE_FAILURE (retry once, then exit 3). If audit trail write fails: AUDIT_TRAIL_WRITE_FAILURE (retry once, then exit 4)
Python standard library (os, socket, glob, re, json, asyncio) Tools, concurrency, file handling Yes Always present (Python runtime) N/A
LLM SDK (openai or anthropic) API client Yes ImportError at startup → system exits with "Missing dependency: install openai or anthropic" N/A

---

§15 Configuration

All configuration via environment variables (no config file).

Field Type Valid Range Default Absent/null meaning Invalid behaviour Security-relevant? Changeable after construction?
LLM_API_KEY string Non-empty string None (required) System exits with error at startup on first LLM call N/A (checked before use) Yes (exposes API access) No
LLM_MODEL string One of: "gpt-4o-mini", "gpt-4o", "claude-3-haiku", "claude-3-sonnet" "gpt-4o-mini" Use default Use default, log warning No No
LLM_TIMEOUT_SEC float 1.0–60.0 15.0 Use default Clamp to [1.0, 60.0], log warning No No
TOOL_TIMEOUT_SEC float 0.5–10.0 5.0 Use default Clamp, log warning No No
MAX_SUBTASKS int 1–4 4 Use default Clamp, log warning No No
AUDIT_TRAIL_PATH string Valid file path "./audit_trail.jsonl" Use default If path invalid (directory not writable), system fails at startup No No

Why defaults chosen: gpt-4o-mini is fast and cheap; timeouts chosen to fit within 60s total (4 sub-agents × 5s tool + 2 LLM calls × 15s = max 50s, leaving buffer).

---

§16 Extension Contracts

Extension point: Sub-agent

The system is designed to be extended with new sub-agent types (e.g., Docker scan, process inspection). No code changes to orchestrator required — only register new class.

MUST implement:

· Subclass SubAgent abstract base class.
· Implement run(subtask: dict) -> dict returning §4 schema.
· Invoke exactly one tool (real local operation, no mocks).
· Call LLM exactly once with tool output to produce findings and severity.
· Catch all exceptions and return success=false with error_details.

MAY override:

· init to accept custom configuration (e.g., different port list). MUST call super().init() if overriding.
· Default tool arguments via subtask fields.

MUST NEVER do:

· Modify the audit trail directly (only orchestrator writes audit trail). Violation results in corrupted trail.
· Raise an exception to orchestrator (catch all → return success=false). Violation crashes orchestrator.
· Call more than one tool per run. Violation violates §1 design principle and will cause timeout.
· Depend on another sub-agent's result. Violation breaks concurrency model.

Registration matching rule:

· Orchestrator maintains dict self.subagent_registry: Dict[str, Type[SubAgent]].
· When dispatching a subtask with name N, orchestrator looks up registry[N] using exact string equality (case-sensitive, no wildcards).
· If N not found, catch-all triggers: substitute partial result with findings="Unhandled subtask type: {N}", severity Info.

Owns vs. references:

· Sub-agent owns its tool handles (opens and closes them).
· Sub-agent references the LLM client (shared, does not close it).
· Sub-agent does not own the orchestrator or audit trail.

Registration: Extension registers by adding to orchestrator.subagent_registry[subtask_name_pattern] = SubAgentClass. Registration happens at construction time. Does not require editing existing files. Registration changes security posture if new tool accesses sensitive resources — caller must review.

Transient error awareness: Extensions MUST NOT assume that retry will be attempted for non-transient errors. The orchestrator's recovery logic uses the transient error definition in §8.

---

§17 Error Propagation

Failure Mode Origin Absorbed? Transformed? Surfaces as System state after propagation
DECOMPOSITION_FAILED Orchestrator LLM call No — after retry Wrapped in OrchestrationError Exception raised from run(), exit code 1 Report.md written with error notice and synthesis_success=false. Audit trail contains events up to failure.
TOOL_FAILURE Sub-agent tool call Yes — sub-agent catches Converted to success=false result Orchestrator receives result dict with success=false, error_details Sub-agent still returns; orchestrator proceeds to recovery. System state defined (report may have partial findings).
LLM_FAILURE Sub-agent LLM call Yes — sub-agent catches Same as TOOL_FAILURE Same as TOOL_FAILURE Same
TIMEOUT (tool or LLM) Sub-agent Yes — caught as exception Converted to same as TOOL_FAILURE/LLM_FAILURE, with error_details indicating timeout Same Same
AGGREGATION_FAILED Orchestrator synthesis LLM No — after retry Converted to synthesis_success=false in return dict Return from run(), report written with raw results, exit code 2 Report written, audit trail complete. System state defined.
REPORT_WRITE_FAILURE Orchestrator file write Yes — retry once then absorb Converted to exit code 3 Exit code 3, error in audit trail, no report.md Audit trail complete, no report. System exits cleanly.
AUDIT_TRAIL_WRITE_FAILURE Orchestrator audit trail write Yes — retry once then absorb Converted to exit code 4 Exit code 4, no audit trail written (error to stderr) No audit trail. System exits immediately.
RECOVERY_FAILURE Orchestrator recovery logic (retry fails again) Yes — no further retry Substitute partial result with findings="Sub-agent failed after retry: {error}" Sub-agent result with success=false, orchestrator continues System state defined. Report includes partial result.
INTERNAL_INVARIANT Any component No — not caught Not transformed Exception raised, process crash Undefined — operator must re-run.
Overall 60-second deadline Orchestrator asyncio timer Yes — cancelled tasks produce existing failure modes In-flight sub-agents and LLM calls return LLM_FAILURE or TIMEOUT. Deadline itself is not a failure mode. Report written with partial results. synthesis_success may be false. Exit code 0 or 2. System state defined. Report written with available results. Audit trail includes cancellation entries.

---

§18 Observability Contract

Events in audit trail (audit_trail.jsonl):

Event Type When Emitted Fields Guarantee Emitted before/after operation
orchestrator_start Before any processing run_id, request_preview (first 200 chars) Always Before
orchestrator_end After report written (or after unrecoverable error) run_id, duration_ms, success (bool), report_written (bool) Always (except crash) After
subagent_start Before sub-agent runs run_id, subtask_name Always for each sub-agent Before
subagent_end After sub-agent returns run_id, subtask_name, duration_ms, success, severity Always for each started sub-agent After
tool_call Sub-agent invokes tool run_id, tool_name, arguments_summary, result_summary (string, truncated 500), duration_ms, success Always for each tool call (each sub-agent has exactly one) After tool returns
llm_call Orchestrator or sub-agent calls LLM run_id, caller ("orchestrator/decompose", "orchestrator/synthesise", or subagent name), prompt_tokens, response_tokens, duration_ms, success, error_summary (if failed) Always for each LLM call After LLM returns
error Any caught error (tool, LLM, recovery attempt) run_id, error_type, message, source (component), recovery_action_taken (if any) Always on any caught error At detection time
recovery Orchestrator performs recovery action run_id, recovery_type (retry/substitute), failed_subtask, outcome (success/failure of recovery) Always when recovery action taken After recovery attempt

What is not logged:

· Full environment variable values (only names and redacted "present/absent")
· Full LLM API keys (only "REDACTED" in error messages)
· Raw file contents (only matched patterns and line numbers)
· User's full request beyond first 200 chars in orchestrator_start (privacy)

Schema versioning: Audit trail schema version 1.0. Each event includes spec_version field ("1.2.1"). Consumers MUST ignore unknown event types and unknown fields within known event types. Breaking changes (field removal, type change) require new spec version.

---

§19 Security Properties

Single-caller adversarial input:

· User provides audit request string. System guarantees: request will not be executed as shell command (no injection). Request is passed as plain text to LLM with system prompt that prevents prompt injection (no "ignore previous instructions" will cause tool execution).
· System does NOT guarantee: LLM will not hallucinate findings. But hallucinated findings will not invoke real tools (tools are only invoked by hardcoded sub-agent logic, not LLM-decided tool calls).
· Fail-closed: If decomposition fails, system does not proceed to tool execution (no partial scan without user intent).

Multi-caller and resource isolation: Not applicable (single caller per run). No isolation guarantees needed.

Security-relevant decisions:

· Tool output truncated to 500 chars in audit trail to prevent credential leakage.
· Environment variable values not logged.
· API key read from environment only, never logged.
· File scans limit to 10 matches to prevent memory exhaustion.

Tradeoff: Availability vs security = not applicable (batch system).

---

§20 Versioning and Evolution

Stability levels:

Interface Stability Breaking change policy
CLI (single argument) Stable Removal or reordering of arguments requires major version. Adding optional flags = minor.
report.md format (Markdown sections) Evolving Sections may be added. Removing expected section (e.g., "Executive Summary") = major.
audit_trail.jsonl event schema Evolving (with notice) Adding event types/fields = minor. Removing fields or changing field types = major.
Sub-agent extension contract (§16) Stable Abstract base class method signatures cannot change without major version.
Configuration environment variables Stable Removing a variable = major. Adding new optional variable = minor.

Breaking change communication: Updated spec document, major version increment.

Spec maintenance: This spec document version 1.2.1. Changes recorded in changelog.

Provisional sections: None. All sections declared final.

---

§21 What Is Not Specified

The following decisions are left to implementors (any choice satisfying other sections is acceptable):

· Internal data structures (e.g., how sub-agent results are stored before aggregation)
· LLM prompt engineering details (as long as decomposition produces valid JSON with subtasks array containing at least 2 items)
· Concurrency implementation details (asyncio is required, but whether to use asyncio.gather() vs asyncio.wait() is not specified)
· Retry backoff strategy (immediate retry is acceptable)
· Exactly which secret patterns are used (must include reasonable defaults for keys, tokens, passwords)
· Logging to stdout/stderr (beyond audit trail — implementation may add debug logs)
· Memory layout and garbage collection
· Which LLM provider (OpenAI or Anthropic) — must be configurable via LLM_MODEL env var, but implementation may hardcode one provider with a flag to switch

---

§22 Assumptions

Environmental assumptions:

· Arithmetic: JSON serialisation/deserialisation handles floats and ints without overflow (Python arbitrary precision).
· Clock: System clock is monotonic for duration measurements (not critical if drifts within 60s).
· Filesystem: pathlib.Path.replace() is atomic on both POSIX and Windows (Python 3.3+ guarantees this).
· Memory: Python runtime manages memory; no manual deallocation needed.
· Character encoding: Source code and all inputs are UTF-8. Platform default not assumed.

Caller assumptions:

· Trust level: Caller (operator) is non-adversarial. Audit request may be arbitrary but not maliciously crafted to exploit LLM prompt injection (though system does not rely on this for security — see §19).
· Call pattern: Caller calls from single thread, does not call run() concurrently, does not call after process exit. Concurrent calls raise RuntimeError (detectable).
· Input validity: Caller provides string input. System validates emptiness but not content beyond length.

Operational assumptions:

· Network: LLM API reachable at startup. Latency bounded such that with retries, total time stays within 30s for LLM calls (leaving 30s for tools).
· Configuration: Required config (LLM_API_KEY) present in environment.
· Time: Wall clock approximately correct (not used for security decisions beyond timeout measurement).
· LLM availability: API uptime sufficient for single retry to succeed.

Violation detectability:

· Clock non-monotonic: Detectable (would cause negative duration — system clamps to 0)
· LLM API unreachable: Detectable (exception)
· Filesystem write failure: Detectable (IOError)
· Assumption undetectable: UTF-8 assumption (if input not UTF-8, may raise UnicodeDecodeError — detectable). Caller concurrency assumption violation raises RuntimeError (detectable).

---

§23 Performance Contracts

Correctness properties that appear performance-related:

· Timeout: run() MUST return within 60 seconds. If the deadline is reached, in-flight operations are cancelled via asyncio task cancellation. Partial results collected before the deadline are preserved. A report.md is ALWAYS written (consistent with §3 and §5 guarantees), containing all sub-agent results completed before the deadline plus a notice identifying any sub-agents that were cancelled. synthesis_success may be false if the aggregation LLM call was cancelled. Audit trail includes cancellation entries. Exit code 0 if report was written, 2 if aggregation also failed. Violation (no report within 60s) would break the §3 guarantee — this is a correctness contract.
· Enforcement: Orchestrator starts an asyncio timer at run() entry. If the timer fires before normal completion, all pending asyncio tasks are cancelled, and the orchestrator proceeds immediately to write the report with whatever results are available.
· Ordering (events): Audit trail events MUST have monotonically increasing timestamps (no backwards jumps). Violation breaks reconstruction — correctness contract.
· Enforcement: Timestamps from datetime.now() with fallback sequence counter if clock jumps backwards.
· Bounded memory: System MUST NOT buffer more than 10 MB of file content for scanning. Violation may cause crash — correctness contract.
· Enforcement: File scan tool reads files line by line, not whole file.

Genuine performance characteristics (not specified, defer to §21):

· Latency percentiles (p50, p95)
· CPU usage
· Memory usage (except the bound above)
· Throughput (requests per second)

---

§24 Future Directions

Extension: Remote host scanning

· Not in scope now (local only). Future spec may add RemotePortProbeAgent that accepts target_host.
· Constraints to preserve: sub-agent independence, concurrency, tool output summarisation.
· Open questions: authentication, rate limiting, network failure recovery.

Extension: Persistent state across runs

· Not in scope. Future version might cache scan results for incremental audits.
· Constraint: MUST NOT break idempotency (add cache invalidation).
· Open question: cache storage format.

Extension: Remediation actions

· Currently audit-only. Future version could add remediation field to findings with suggested commands.
· Constraint: MUST NOT execute remediation automatically (require opt-in flag).

---

End of Specification Contract — REVISION 1.2.1

```
