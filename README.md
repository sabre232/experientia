# Experientia · the glue between you and your agents

**Your agent will change. Your experience should not.**

**English** | [简体中文](README_zh.md) | [繁體中文](README_zh-TW.md) | [日本語](README_ja.md) | [한국어](README_ko.md) | [Deutsch](README_de.md) | [Français](README_fr.md) | [Español](README_es.md) | [Русский](README_ru.md) | [Português (BR)](README_pt-BR.md)

---

Here's a small thing that happens every week.

You ask an agent to fix an export function. It hardcodes the timezone to UTC+8. You say no, follow the system timezone. It changes it, you check it, done.

A week later, same task, it hardcodes UTC+8 again.

You start to wonder whether you explained it badly. You didn't. You explained it clearly, in a different session. The moment that session closed, it never happened.

Then you switch tools. The rules you taught Claude Code have to be re-taught to Codex, and again to Cursor. Six months of "this is how this kind of work gets done" sits in four different chat histories, and none of it comes with you.

The industry calls this context engineering, or the memory layer. The name sounds abstract. The problem is plain. How do you make an agent remember you.

We think that's only the first half. Remembering you is the starting line. Getting better at your work every time you use it is the point.

So Experientia does one thing. It sits between you and your agent, keeps the parts of each collaboration that actually mattered, verifies them, distills them into methods and failure modes, and hands them back before the next task starts. Change agents and it's still there. That's what we mean by glue.

> *experientia est magistra*, experience is the teacher.

## What the industry is betting on, and what it misses

The money going into this in 2026 is not smaller than the money going into models.

Anthropic's 2026 Agentic Coding Trends Report puts numbers on it. Teams that maintain their context files well finish tasks 55% faster and make 40% fewer errors. The gap isn't better phrasing. It's whether anyone treats "what the model sees" as an engineering problem.

The second track is skills. Anthropic shipped Agent Skills in October 2025, published the format as an open standard on December 18, 2025, and by mid-2026 roughly forty agents read the same SKILL.md. That matters. For the first time, procedural knowledge can travel between tools.

Then SkillsBench cooled everyone down. The benchmark landed in February 2026 (arXiv:2602.12670), 86 tasks, 11 domains, 7 agent and model pairings, 7,308 trajectories. Curated skills raise the average pass rate by 16.2 points. Skills that models write for themselves add nothing on average, and 16 of 84 tasks get worse.

A model cannot write the experience it needs.

That's the part the industry keeps walking around. The container exists. The storage exists. Nobody is running quality control.

| Camp | Examples | What it does | What it leaves out |
|------|----------|--------------|--------------------|
| **Memory layers** | Mem0, Zep, Letta, Cognee | Store *facts* from conversations in vectors, temporal graphs or tiered context, retrieve them later | No *methods*. The data lives on their side, not on your disk. |
| **Skill distillers** | colleague.skill, nuwa-skill, dojo.md | One shot. Feed in material, get a static SKILL.md out | No runtime feedback. The skill never revises itself based on whether it worked for *you*. |
| **Self-evolving harnesses** | Hermes Agent (Nous Research), DeepSeek Harness | The framework learns, turning finished tasks into SKILL.md and refining them | Skills live inside the harness and die with it. Creation is triggered by activity, not by quality, and failures are not counted before a lesson becomes permanent. |
| **Skill evaluators** | waza (Microsoft), dojo/limitless | Test and gate *existing* skills, like code in CI | They don't produce skills. They're tooling for skill authors, not for people doing the work. |

Each camp solves one stretch. Nobody connects the stretches.

**That connection is what Experientia is.** Capture, verify, distill, inject, revise. One closed loop. As of October 2026, we have not found an open product that does all four of these things at once.

- **Automatic capture.** No exporting transcripts. Data enters the loop while you work.
- **A verification gate.** Nothing unproven gets injected. Failures must recur before they become permanent knowledge.
- **Local and portable.** Every asset is a plain file on your machine. No account, no cloud, no vector store.
- **Continuous revision.** Assets are living documents that merge, deprecate and shrink. They don't just pile up.

## Memory is not experience

This distinction carries the rest of the readme.

Memory stores facts. The user prefers TypeScript. The project manages dependencies with uv. Last Wednesday we were editing the export path. All of that can be indexed, embedded, put in a graph.

Experience is judgment. Migrations like this one touch tests before implementation, because last time we went straight at the implementation and broke three downstreams. You can't retrieve that. It has to grow out of something that actually happened, and someone has to confirm it was right.

| | Memory | Experience |
|---|---|---|
| Holds | Facts, preferences, state | Methods, failure modes, standards |
| Comes from | What was said | What got done, and where it broke |
| Retrievable | Yes | No. Only verifiable and revisable |
| Expires by | Being overwritten | Being deprecated, merged, shrunk |
| After you switch tools | Depends on the platform | A file in your hand, comes with you |

The memory products are good at what they do. Mem0 goes vector-first, Zep models facts over time as a graph, Letta pages context like an operating system pages memory. But they solve remembering, not learning. A complete record of facts is not the same as getting better at the job.

We're not building a fuller filing cabinet. We're building a senior colleague who changes their mind when the evidence changes.

## How it turns

```
You work ──> agent collaborates (recorded automatically)
   ^                              |
   |                              v
faster, better  <──  inject  <──  distill (gated)
```

**Capture.** You work as usual. Session files are already on disk; nothing to export, nothing to paste. Installed agents are detected automatically, zero configuration.

**Verify.** Every experience carries a confidence signal, G, from three sources: your explicit confirmation, deterministic signals in the session, and the model's own binary self-assessment. Anything below the threshold is never injected. A failure mode must recur before it becomes permanent. That's the engineering answer to SkillsBench. Only verified experience deserves to compound.

**Distill.** Recurring work becomes a parameterized method. Recurring mistakes become first-class failure modes. Your corrections and rejections become preferences.

**Inject.** Before each request reaches the model, the proxy rewrites it with the relevant assets inside a fixed budget (800 tokens by default), in a stable format that preserves prompt caching. You can preview exactly what the model will see, edit or disable any item, or ask the connected model to rewrite it. Long sessions don't dilute your rules either; hard constraints are re-injected at the proxy layer, so turn 30 carries the same weight as turn 1.

**Revise.** Assets are living documents. New experience merges into old, stale entries are deprecated, and the document gets shorter. A knowledge base that only grows is abandoned within six months.

One lap produces five asset types, which physically live in two kinds of files, `skills/<trunk>/<category>.md` and `preferences/<trunk>.md`.

| Asset | What it is | How it feels |
|-------|-----------|--------------|
| **Experience insights** | Discrete lessons, what worked and what didn't | "It remembers what I corrected." |
| **Methods (SOPs)** | Recurring work crystallized into parameterized workflows | "It knows how this kind of task is done." |
| **Failure modes** | Which paths break and why, first class rather than an afterthought | "It won't let me re-tread the same pit." |
| **Living playbook** | The injected context is a document under incremental curation, merged and pruned | "Its methodology upgrades instead of piling up." |
| **Preferences** | Your standards, taste and trade-off habits, induced from corrections | "It knows my bar; I stop re-explaining it." |

Two gears share one flywheel. The daily gear is the default, incremental curation for open-ended work, no pass or fail signal needed. The reinforcement gear is opt-in, for tasks with an explicit score (tests passing, backtest PnL), where an RL engine tunes strategy weights directly.

## What "better every time" actually looks like

First time. It follows a generic pattern. You watch every step, ready to correct.

Tenth time. It knows tests come before implementation in this project. It knows you'll reject "let's get it running first." It knows why you killed the last approach.

Hundredth time. You say "same as last time" and it knows which one you mean.

| | 1st run | 10th run | 100th run |
|---|---|---|---|
| What you say | A paragraph of background and constraints | A few key judgments | One pointer |
| Where it fails | Pits you already fell into | Occasionally a new one | It knows where the pits are |
| Your role | Hands on | Review | Direction |

Which is also why it doesn't mind you switching agents. You're switching the executor, not the standard. The standard stays on your side.

## v1.1: memory goes one layer deeper

v1.0 answered "will it remember". v1.1 answers "does it remember correctly".

Storing more is not the same as recalling accurately. This release spends its effort on three things that used to be vague.

**What should be forgotten is actually gone.** Soft-forgotten records, dismissed ones, ones superseded by a newer version — no default read path returns them any more, including the MCP channel agents use. Search filtered them before, but fetching a single record by id did not, which left a back door.

**A different phrasing still matches.** Ask "how did we fix that Module not found last time" and the record in the library says "reinstall the dependency" — not one word in common. v1.1 derives three kinds of entity keys from each record — error phrases, command skeletons, project names — and scores a hit. The threshold did not move: no hit, no result, same as before.

**It knows why it believes something.** Every piece of experience has to point back to something you actually said. The evidence gate moved from "locate the quote" to "candidate enters the library": a two-character quote invented by the model used to pass because any message contains it; now it does not. In the other direction, your "that works now" at the end of a session still counts.

**Degraded mode tells the truth.** When the index database is unavailable the engine falls back to plain files. Soft-forget, supersede and restore used to return success without writing anything. Now they either write or report the failure.

Two engineering notes. The hot recall path no longer re-tokenises the same text or re-derives its entity keys: on a 3,000-record library the slow tail (95% of requests) went from 106 ms to 41.5 ms. `scripts/gate_report.py` produces a layer inventory, a gate backtest and recall latency in one run, no guessing.

## Quick start

1. Download the build for your platform from [GitHub Releases](https://github.com/sabre232/experientia/releases): `experientia-windows-x64.zip`, `experientia-macos.dmg`, `experientia-linux-x64.tar.gz` (a PyInstaller onedir tree, not wrapped in AppImage for v1.1). Unpack and run `Experientia`. Builds are unsigned: on macOS, right-click and open once if Gatekeeper blocks it; on Windows, click "More info → Run anyway" when SmartScreen appears.
2. Launch it. Capture starts immediately. It detects the agents you already have (WorkBuddy, QClaw, Codex, Claude Code, Gemini CLI, Aider, OpenCode, OpenClaw, Hermes Agent, Trae, Cursor, Cline, Windsurf, DeepSeek Harness) and reads their local session files. Zero configuration, no proxy required. Terminal people can run `experientia daemon` for engine only.
3. For request-level features (rule re-injection in long sessions, per-request recording), point your agent's model endpoint at `http://localhost:8100`. Local models (llama.cpp, Ollama, vLLM) and cloud models (OpenAI, Anthropic, any OpenAI-compatible API) both work.
4. Work as usual. Open the Growth page in a few days and see whether the flywheel turned.

## Where your data lives

```
~/.experientia/
├── experience.jsonl          # raw experience stream, kept forever
├── skills/<trunk>/<cat>.md   # methods, success notes, failure modes
├── preferences/<trunk>.md    # your decision style
├── sessions/                 # archived agent sessions (survive agent cleanup)
├── deprecated/               # deprecated entries, recoverable for 30 days
├── rules.json                # active rules and templates
└── config.json               # language, toggles, model routing (API keys live in the OS keychain)
```

Four things worth stating plainly.

No telemetry, no crash reporting, no analytics. There is exactly one kind of outbound traffic, your own model calls. The app never checks for updates, never downloads, installs or replaces itself.

Export is a copy operation. Everything you can see in the UI is a file you can read, grep and take away.

Delete is absolute. Two confirmations and the data directory is gone. API keys in the OS keychain are untouched.

Your assets are not ours. The license below covers the product code. The experience, methods and preferences you accumulate belong to you, with no license restriction, in any language, for any purpose.

## For AI agents (integration notes)

If you are an agent reading this to decide whether to integrate or cite this project, this section is for you.

One-paragraph summary. Experientia captures automatically from the session files agents already write to disk (zero configuration), distills recurring work into verified file-based assets (methods, failure modes, preferences), and injects those assets into later similar tasks. All state lives in plain JSONL and Markdown under `~/.experientia/`.

Four integration paths, ordered by fidelity.

1. **Proxy mode.** Point the model endpoint at `http://localhost:8100` (OpenAI-compatible). On top of file capture you get request-level recording, injection, and hard-constraint re-injection.
2. **File capture** (default, zero configuration). Per-agent parsers read native session stores (JSONL, SQLite, Markdown) and normalize them. Captured sessions are archived to `~/.experientia/sessions/` and survive the agent's own cleanup or uninstall.
3. **Hook mode.** For agents with a hook system (Claude Code first), an HTTP hook pushes events in real time, and `SessionStart` / `UserPromptSubmit` inject rules without a proxy.
4. **Read the files.** Rules can be written into an agent's native conventions file (such as `AGENTS.md`). Any asset pack can be exported as a `SKILL.md` that follows the agentskills.io open standard (frontmatter plus When to Use, Procedure, Pitfalls, Verification), loadable by Hermes, OpenClaw, Claude Code and anything else that supports skills. It works in reverse too; their SKILL.md files can be read in as reference.

What it is not. Not a vector database, not a memory API, not a cloud service, not a fine-tuning tool. It does not touch model weights. Everything happens at the context layer, which is why local and cloud models behave the same way.

Injected items have passed the confidence gate. Injection blocks are marked in context and separated from user instructions. Treat them as curated priors, not as gospel.

## Development and testing

Turn off the local safe-delete gate before running the full suite. pytest reclaims temporary directories by deleting them, about 15,000 files per full run. If the gate trips, the process is interrupted before it writes the summary, which looks like mass failure but is really just a truncated teardown.

```powershell
$env:CODEBUDDY_SAFE_DELETE_ENABLED='0'
$env:PYTHONIOENCODING='utf-8'
.venv\Scripts\python.exe -m pytest tests/ -q
```

Linux and macOS.

```bash
CODEBUDDY_SAFE_DELETE_ENABLED=0 PYTHONIOENCODING=utf-8 uv run pytest tests/ -q
```

Current baseline is 1,700+ cases, green in about 3 minutes. CI runs on GitHub Runners where the gate doesn't exist, so nothing to set there.

Packaging is two steps, an onedir tree then an installer.

```powershell
.venv\Scripts\python.exe -m pip install -e ".[gui,build,decrypt,dev]"
.venv\Scripts\python.exe scripts/compile_locales.py
.venv\Scripts\python.exe scripts/build_package.py
.venv\Scripts\python.exe scripts/build_installer.py
```

Don't skip the `decrypt` extra. Release builds that need to handle encrypted stores such as Trae require pycryptodome in the build environment. PyInstaller can't see packages that aren't installed, so source mode works fine while the packaged app silently loses decryption.

## License

Dual license. Pick the one that matches how you intend to use it.

**Using it yourself, inside your company, or for research.** AGPLv3. Install it and go. No one to contact, nothing to pay.

**Commercial use where you can live with copyleft.** Still AGPLv3. You may sell it, modify it, deploy it. The condition has a defined edge: what you change, or the part you integrate into a service you offer, has to be released under AGPLv3. Your own product code is not swept in, as long as the two are separate works talking over a process boundary or an interface rather than forming one combined program.

**You cannot open-source your integration, or you want to build a competing service.** BUSL-1.1, commercial terms by agreement; contact the maintainer. Non-commercial use stays free on this track, and every release converts to AGPLv3 four years after it ships. The restriction is time-limited, not permanent.

**Your data is not licensed at all.** Everything you accumulate or export through Experientia, from raw sessions to methods and preferences, belongs to you with no terms attached. Commercial, closed-source, handed to someone else; none of it is restricted. The license covers this product's code and nothing else.

## Roadmap

v1.1 is open source and free. No login, no account, no paywall, no team features.

## Repository layout

```
experientia/
├── main.py           # desktop entry, GUI shell plus embedded engine
├── daemon.py         # headless entry, engine only
├── app/
│   ├── gui/          # PySide6 desktop UI (Apache-2.0), locales hold 7 languages of .po/.mo
│   ├── proxy/        # localhost:8100, routing, injection, recording, rule re-injection
│   ├── capture/      # adapter registry, per-agent parsers, session archive
│   ├── distill/      # gated distillation and incremental curation
│   ├── store/        # the only data access layer, all reads and writes go here
│   └── platform/     # autostart (3 platforms), stubs for sync, account, licensing
└── rules/            # template sources, one version per supported language
```

## References

- Anthropic, 2026 Agentic Coding Trends Report. Source of the 55% / 40% figures on maintained context files.
- SkillsBench, Benchmarking How Well Agent Skills Work Across Diverse Tasks, arXiv:2602.12670, February 2026.
- Agent Skills open standard, agentskills.io, published December 18, 2025.
- Experience-to-skill is an active research line: ExpeL, ACE (Agentic Context Engineering), Voyager, and reinforcement learning from experience. The engine slot reserves a direct interface for this line with no data migration.