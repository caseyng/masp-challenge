# Multi-Agent Security Pipeline: Runtime Orchestration with Verification & Recovery

## Challenge / 编程挑战

Build a working multi-agent CLI system that accepts a user's natural-language security audit request, decomposes it into subtasks, executes them concurrently across specialized sub-agents (each with tool use), aggregates results, and produces a structured audit report — with full error recovery and an observable audit trail.

The scenario is intentionally chosen to match Kok Chuan's background: a "security posture audit" agent that inspects a local environment (files, ports, env vars, config patterns). This means he can apply genuine domain judgment to tool design and agent decomposition — the challenge tests delivery skill, not domain learning.

**The system must:**
1. Accept a free-text audit request from the CLI (e.g. "audit this project directory for secrets leakage and exposed network surfaces")
2. An **Orchestrator Agent** calls an LLM to decompose the request into 2–4 named subtasks, each assigned to a specialist sub-agent
3. Each **Sub-Agent** runs concurrently, uses at least one real tool (e.g. filesystem scan, port probe, env var inspection, pattern match), calls an LLM to reason about its findings, and returns a structured result
4. The Orchestrator aggregates sub-agent results, calls an LLM once more to synthesize a final report with severity ratings, and writes it to `report.md`
5. A full **audit trail** (which agent ran, which tools were called, LLM calls made, errors encountered, recovery actions taken) is written to `audit_trail.jsonl`

**Error recovery is mandatory:** if any sub-agent fails (tool error, LLM timeout, bad output), the orchestrator must detect it, log the failure to the audit trail, and either retry once or substitute a graceful partial result — the overall run must not crash.

One command to run: `python main.py "audit this project for secrets and open ports"` — produces `report.md` and `audit_trail.jsonl` in under 60 seconds.

---

构建一个可运行的多智能体 CLI 系统，接受用户的自然语言安全审计请求，将其分解为子任务，并发地在多个专业子智能体（每个均有工具调用）中执行，聚合结果并生成结构化的审计报告——同时具备完整的错误恢复机制和可观测的审计轨迹。

场景特意贴合候选人背景：一个"安全态势审计"智能体，检查本地环境（文件、端口、环境变量、配置模式）。这让候选人可以应用真实的领域判断力来设计工具和分解任务——挑战测试的是交付能力，而非领域学习。

**系统必须：**
1. 从 CLI 接受自由文本审计请求（例如："审计本项目目录，检查密钥泄露和暴露的网络面"）
2. **编排智能体（Orchestrator Agent）** 调用 LLM 将请求分解为 2–4 个命名子任务，每个子任务分配给一个专业子智能体
3. 每个**子智能体**并发运行，至少使用一个真实工具（如文件系统扫描、端口探测、环境变量检查、模式匹配），调用 LLM 对其发现进行推理，并返回结构化结果
4. 编排智能体聚合子智能体结果，再次调用 LLM 综合生成带有严重性评级的最终报告，并写入 `report.md`
5. 完整的**审计轨迹**（哪个智能体运行、调用了哪些工具、发出了哪些 LLM 调用、遇到了哪些错误、采取了哪些恢复行动）写入 `audit_trail.jsonl`

**错误恢复是必须的：** 如果任何子智能体失败（工具错误、LLM 超时、输出格式错误），编排器必须检测到它，将失败记录到审计轨迹中，并进行一次重试或替换为优雅的部分结果——整体运行不得崩溃。

一条命令运行：`python main.py "audit this project for secrets and open ports"` — 在 60 秒内生成 `report.md` 和 `audit_trail.jsonl`。

## Requirements / 需求

- Single entry point: `python main.py "<audit request>"` runs end-to-end and exits cleanly, producing both `report.md` and `audit_trail.jsonl`.
- Orchestrator Agent uses an LLM call to decompose the input into 2–4 named subtasks and dispatches them to typed Sub-Agent instances that run concurrently (asyncio or threads).
- Each Sub-Agent must invoke at least one real local tool (e.g. recursive file scan for secret patterns, socket-based port probe, os.environ inspection, config file parser) and then call an LLM to reason about the raw tool output before returning a structured JSON result.
- Error recovery is enforced: simulate or trigger at least one sub-agent failure (e.g. a deliberately bad tool call or forced exception), prove in the audit trail that the orchestrator caught it, logged it, retried or substituted a partial result, and the run completed successfully.
- The final `report.md` must contain: the original request, one section per sub-agent with findings and a severity label (Critical / High / Medium / Low / Info), and an executive summary synthesized by the Orchestrator's final LLM call. `audit_trail.jsonl` must contain one JSON-lines entry per event (agent start/end, tool call, LLM call, error, recovery).

## Evaluation Criteria / 评判标准

- Agent architecture & decomposition judgment: Is the orchestrator/sub-agent boundary well-reasoned? Are subtasks meaningfully distinct and appropriately scoped — not just arbitrary splits? Does tool design reflect real security domain knowledge (e.g. the patterns scanned for, the ports probed, the env vars flagged)?
- Context engineering: How does each agent's system prompt / context window get constructed? Does the orchestrator pass only what each sub-agent needs? Does the synthesis step receive a clean, token-efficient aggregation — not a raw dump?
- Error recovery completeness: Is failure detection explicit (not just a bare try/except)? Is the recovery action logged with enough detail to debug? Does the system remain correct under partial failure — i.e. does the final report clearly flag what was and wasn't completed?
- Audit trail quality & observability: Is `audit_trail.jsonl` machine-readable, consistently structured, and sufficient to reconstruct the full execution post-hoc? Would this trail be useful for debugging a silent agent failure in production?
- Delivery completeness under time pressure: Does the system run in one command with no manual setup beyond `pip install -r requirements.txt` and setting an API key? Is the output actually useful — a real report a security engineer could act on — rather than lorem-ipsum filler?

## Tech Hints / 技术提示

- Python 3.11+, asyncio for concurrency
- OpenAI SDK or Anthropic SDK (candidate's choice — they should justify it)
- No agent framework required — raw LLM API calls are preferred so architectural decisions are visible; LangChain/LangGraph allowed but must not hide the orchestration logic
- All tools must be real local operations — no mocked tool results in the final submission
- A small fixture directory (`fixtures/`) with sample config files, a `.env.example`, and a dummy private key file should be included so the scanner has something real to find

## Rules / 规则

- **Time limit / 时间限制**: 60 minutes (2026-04-26 18:06 UTC)
- **AI tools required / 必须使用 AI 工具**: Claude Code, Cursor, Copilot, etc. This challenge is designed to be impossible without AI tools — use them.
- **AI session logs are MANDATORY / AI 会话记录为必交项**: Your AI interaction history (`.claude/`, `.cursor/`, `.codex/`, `.windsurf/`, or `ai-session/`) is a core evaluation deliverable. Do NOT delete or `.gitignore` these directories. **Submissions without AI session logs will receive a significant scoring penalty.** / 不提交 AI 会话记录将严重扣分。
- **Multiple pushes OK / 可以多次 push**: We evaluate your last push before the deadline
- **Language / 语言**: Any programming language, any framework

## Getting Started / 开始

1. Read this README carefully
2. Use Claude Code or your preferred AI tool
3. Build a complete, runnable project
4. `git push` your code (multiple pushes OK)
5. Keep the `.claude/` directory for AI collaboration evaluation

Good luck! / 祝你好运！