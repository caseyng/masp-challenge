# MASP challenge — spec + prompt harness complete

## WHAT THIS IS
Timed coding challenge: build a multi-agent security pipeline CLI in Python.
Spec written. Implementation prompts ready. Next: user submits prompts in wave order, then runs the system.
Exit condition: `python main.py "..."` produces `report.md` + `audit_trail.jsonl` in <60s.

## WHERE WE ARE
**Done:**
- `SPEC.md` — full 23-section spec (implementation authority)
- `CLAUDE.md` — implementation harness (canonical models, file layout, rules, wave order)
- `prompts/00_foundations.md` through `prompts/11_main.md` — 12 self-contained Claude Code prompts

**Not done:**
- No Python code written yet — prompts exist but have not been submitted
- No `pip install` has been run

**File tree expected after prompts run:**
```
exceptions.py, models.py, trail_writer.py, llm_client.py, tools.py, orchestrator.py, main.py
agents/__init__.py, agents/base.py, agents/secrets.py, agents/ports.py, agents/env.py, agents/config.py
fixtures/ (.env.example, config.yaml, dummy_private_key.pem, settings.json)
requirements.txt
```

## CONSTRAINTS
- HARD: No LangChain/LangGraph. Raw SDK calls only.
- HARD: Anthropic SDK preferred (ANTHROPIC_API_KEY takes precedence over OPENAI_API_KEY).
- HARD: No secret values in any output — only names, paths, pattern categories, port numbers.
- HARD: Overall run MUST exit 0 even if all sub-agents fail.
- HARD: `audit_trail.jsonl` written incrementally (flush per append).
- HARD: Python 3.11+, asyncio for concurrency.
- SOFT: Spec is authoritative — deviations require explicit justification.

## DECISIONS MADE
| Decision | Choice | Why |
|---|---|---|
| Retry semantics | Re-run entire sub-agent once | Simplest; avoids partial-state tracking |
| Failed sub-agent output | `status:"failed"`, `severity:"Info"`, one finding describing failure | Cleanest report, unambiguous |
| LLM decomposition OOB | Clamp [2,4] silently; 0 valid → fallback all 4 | Avoids abort on LLM weirdness |
| All sub-agents fail | Exit 0, report documents failures | Spec: "must not crash" |
| Sub-agent type set | Closed registry: secrets, ports, env, config | Predictable dispatch, no open-set risk |
| audit_trail writes | Incremental, flush per event | Crash-safe; partial trail survives kill |
| Sub-agent architecture | Inheritance: `BaseSubAgent` ABC, specialists override `run()` | Simple, direct |
| Exception hierarchy | `MASPError > OrchestratorError / SubAgentError / ToolError / LLMError` | Clean propagation stops |

## REASONING PATTERNS
- SITUATION: Timed challenge, user said "simplest win" → WRONG INSTINCT: ask more questions → CORRECT FRAMING: make all decisions now, bias toward simple, document in spec → IMPLICATION: every gap was resolved unilaterally with the most boring correct choice.
- SITUATION: "batch mode" mentioned → WRONG INSTINCT: assume Claude Code `batch` command → CORRECT FRAMING: there is no `claude batch` in v2.1.119; user means submitting individual `claude -p` prompts in parallel waves using shell `&`/`wait`.

## USER CORRECTIONS
- User said "simplest win" as override to asking clarifying questions. Stop elaborating tradeoffs; make the call and move on.
- "Batch mode" = individual `claude -p` invocations run in parallel, NOT a special command.
- User interrupted once mid-response — means answer was getting too long. Keep responses tight.

## NEXT
- MUST: User submits prompts in wave order (see CLAUDE.md for wave structure and shell commands)
- MUST: After all prompts run, verify `python main.py "..."` works end-to-end
- SHOULD: Check that `audit_trail.jsonl` contains all required event types per SPEC.md §4
- SHOULD: Confirm `report.md` has all required sections per SPEC.md §4
- DEBT: No tests written (out of scope for timed challenge)

## OPEN QUESTIONS
- None blocking. All spec gaps were resolved.

## ARTIFACTS
| Artifact | Location | State |
|---|---|---|
| Challenge brief | `/root/challenge/masp-challenge.md` | Read-only reference |
| Specification | `/root/challenge/SPEC.md` | Complete, v1.0.0, READY |
| Implementation harness | `/root/challenge/CLAUDE.md` | Complete |
| Prompt: foundations | `/root/challenge/prompts/00_foundations.md` | Ready to submit |
| Prompt: trail_writer | `/root/challenge/prompts/01_trail_writer.md` | Ready to submit |
| Prompt: llm_client | `/root/challenge/prompts/02_llm_client.md` | Ready to submit |
| Prompt: tools | `/root/challenge/prompts/03_tools.md` | Ready to submit |
| Prompt: fixtures | `/root/challenge/prompts/04_fixtures.md` | Ready to submit |
| Prompt: base_agent | `/root/challenge/prompts/05_base_agent.md` | Ready to submit |
| Prompt: secrets_agent | `/root/challenge/prompts/06_secrets_agent.md` | Ready to submit |
| Prompt: ports_agent | `/root/challenge/prompts/07_ports_agent.md` | Ready to submit |
| Prompt: env_agent | `/root/challenge/prompts/08_env_agent.md` | Ready to submit |
| Prompt: config_agent | `/root/challenge/prompts/09_config_agent.md` | Ready to submit |
| Prompt: orchestrator | `/root/challenge/prompts/10_orchestrator.md` | Ready to submit |
| Prompt: main+requirements | `/root/challenge/prompts/11_main.md` | Ready to submit |

## RESUME INSTRUCTIONS
1. Read `/root/challenge/SPEC.md` — this is the authority for all behaviour
2. Read `/root/challenge/CLAUDE.md` — contains canonical shared code and wave order
3. Skim the prompt files in `/root/challenge/prompts/` if needed to understand component scope
4. Do NOT rewrite or re-spec anything unless the user explicitly asks

---
ORIENTATION: The spec and implementation harness for the MASP challenge are complete. The user's next action is to run the 12 prompt files in wave order using `claude -p "$(cat prompts/NN_xxx.md)" --dangerously-skip-permissions`, with Wave 1 prompts run in parallel (`&`/`wait`), Wave 3 in parallel, and Waves 0/2/4/5 sequential. The dominant reasoning pattern: this is a timed challenge, so every decision biases toward the simplest correct implementation — never ask when you can decide. SPEC.md is the single source of truth; if any implementation question arises, answer it from the spec before opening any other file.
