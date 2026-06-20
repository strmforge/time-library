# GitHub Positioning Draft For 2026.6.16

This is a local maintainer draft. Do not publish it before the release decision.

## One-line Positioning

Keep local AI agents from starting over.

## Chinese Positioning

让本机 AI 不再每次从零开始。忆凡尘会保留可回源的工作上下文：找回旧对话和偏好，复用做成过的修复办法，并且能回到原始记录核对。

## Homepage Should Lead With Features

Use the high-star memory-project pattern: one sentence, feature list, quick
demo, install, safe verification. Do not lead with internal theory.

1. **Shared local context**
   One local record base for Claude Desktop, Claude Code CLI, Codex, OpenClaw,
   Hermes, Cursor-style tools, and popular open-source agents.

2. **Automatic local records**
   Useful AI conversations and tool traces stay on the user's own computer,
   organized by device and source tool.

3. **Source-backed recall**
   The agent can answer old decisions, preferences, fixes, and project
   boundaries with compact source refs, hit reasons, and optional bounded
   excerpts.

4. **Reusable work paths**
   Repeated fixes, review steps, project rules, gotchas, and validation paths
   become reusable guidance for the next AI window.

5. **Traceable experience evolution**
   Successful fixes, mistakes, and user corrections can become candidates.
   Only source-backed candidates with original evidence and acceptance checks
   can be adopted into Xingce; later changes can leave errata, upgrade, or
   rollback receipts.

6. **Experience for every local agent**
   Xingce is not private to one tool. Skill-, custom-instruction-, and
   MCP-capable local agents can read the same work experience before acting.

7. **Record Doctor**
   A one-command safe check shows whether records are guarded before the user
   trusts recall.

8. **Local console**
   A browser page shows connected tools, recent record health, safe capability
   checks, and raw record locations.

9. **No cloud account required**
   Data stays local by default. Summaries help navigation, but original records
   remain the source of truth.

10. **Simple install**
   One shell command, PowerShell, or double-click installers in the release zip.

## Competitor Function Profiles And Copy Samples

These are competitor notes and writing-pattern notes, not claims to copy and not
public README text.

### Memobase competitor profile

Memobase is a competitor in the AI application memory-backend lane. It leads
with "AI memory is expensive and slow", then immediately names the functional
answer: buffered batch processing, lower LLM cost, online latency under 100ms,
LOCOMO result, familiar FastAPI/Postgres/Redis stack, Python/Node.js/Go SDKs,
MCP, Docker deployment, and target scenarios such as customer service,
personalization, and long-term companion apps.

Useful lesson for Memcore Cloud: say the pain, say what turns on after
connection, then list measurable or concrete capabilities. Do not lead with
philosophy. Strategic contrast: Memobase sells fast, low-cost memory for AI
apps; Memcore Cloud should sell a source-backed local AI memory library for
people who use multiple local agents and need original records, preferences,
experience, receipts, and provenance.

### Memary pattern

Memary leads with "AI Agent forgets this conversation in the next one", then
explains what happens after connection: each conversation automatically extracts
people, relationships, and events into a knowledge graph; later conversations
retrieve related graph context to keep cross-session cognition consistent. It
also explains the graph in plain words: people are nodes, relationships are
edges, and the AI follows the network to remember context.

Core features named in the sample:

- recursive retrieval and multi-hop reasoning;
- memory-stream timestamp tracking;
- reference-frequency statistics;
- automatic memory generation;
- multiple graphs and multi-agent support;
- local models and GPT-4 both supported.

Useful lesson for Memcore Cloud: users understand concrete mechanisms when they
are tied to a familiar metaphor. For us, the metaphor is not "graph database";
it is the local AI memory library: holdings, library ids, shelves, source
records, borrowing receipts, Zhiyi, and Xingce.

### LangMem competitor profile

LangMem is a competitor in the Agent self-improvement and procedural-memory
lane. It leads with "AI Agents do not self-improve", then names three abilities
that turn on after connection:

- automatically extract important information from conversations into long-term
  memory;
- improve agent behavior through prompt optimization;
- run a background manager that continuously consolidates memory.

Core functions named in the sample:

- core memory APIs;
- memory-management tools for hot-path recording and search;
- background memory manager for automatic extraction, consolidation, and
  knowledge updates;
- native integration with LangGraph long-term memory storage for production
  agent applications.

Useful lesson for Memcore Cloud: "memory" and "experience" must affect behavior,
not only retrieval. Strategic contrast: LangMem sells production agent
self-improvement inside the LangGraph ecosystem; Memcore Cloud should sell
source-backed local experience that can be shared across Codex, Claude, Hermes,
OpenClaw, Cursor-style tools, and other skill-, instruction-, or MCP-capable
agents. Xingce should be described as reusable work paths and experience
evolution with original evidence, validation receipts, adoption, errata,
upgrade, and rollback, not just as prompt optimization.

### KnowledgeGraphMCP competitor profile

KnowledgeGraphMCP is a competitor in the lightweight local graph-memory lane. It
leads with "add AI memory without running a database", then names the functional
answer: during each conversation the AI can create entities, create
relationships, and query historical memories, while all data persists in local
JSON files.

Core value named in the sample:

- zero dependency;
- local privacy;
- cross-session persistent memory;
- one-file setup for personal knowledge management, long-term context, and
  lightweight AI assistants.

Useful lesson for Memcore Cloud: simple local persistence is an attractive
promise. Strategic contrast: KnowledgeGraphMCP sells one-file local graph
memory; Memcore Cloud should sell a richer local library system where raw
records remain the source-of-truth holdings, library ids make items addressable,
five shelves separate memory types, borrowing receipts show use, and Xingce
experience can be validated and shared across local agents.

### cognee competitor profile

cognee is a competitor in the hybrid knowledge-infrastructure lane. It leads
with "AI memory is forced to choose either semantic search or relationship
search", then names the functional answer: ingest documents, conversations, and
tables into both a vector index for semantic lookup and a knowledge graph for
relationship lookup, so the AI can retrieve similar content and reason along
relationship chains.

Core positioning named in the sample:

- knowledge infrastructure: unified ingest, hybrid retrieval, and local
  deployment;
- continual-learning agents: learn from feedback and coordinate across agents;
- trustworthy and observable agents: audit logs and OpenTelemetry telemetry;
- one-command Python installation with `uv pip install cognee`.

Useful lesson for Memcore Cloud: hybrid retrieval and observability are strong
developer-facing promises. Strategic contrast: cognee sells a general knowledge
infrastructure layer; Memcore Cloud should sell a local AI library where
retrieval is not only semantic or relational but also provenance-first. The
public story should emphasize source records, library ids, borrowing receipts,
five shelves, Zhiyi preferences, Xingce experience, and reviewable experience
evolution across local agents.

### ObsidianMCP adjacent competitor profile

ObsidianMCP is an adjacent competitor in the local notes copilot lane. It leads
with "Obsidian notes pile up until even the user cannot find them", then names
the functional answer: connect AI directly to the local Obsidian vault to search
notes, read content, create notes, edit existing notes, manage tags, and run
full-text search through Obsidian's local REST API. The privacy promise is that
all note data stays local.

Core value named in the sample:

- local Obsidian vault connection;
- search, read, create, edit, tag, and full-text search operations;
- local REST API rather than cloud upload;
- useful for diaries, research notes, and personal knowledge management;
- AI as a notes copilot.

Useful lesson for Memcore Cloud: local, AI-readable notes are already an
understandable category. Strategic contrast: ObsidianMCP is a copilot for an
existing note app. Memcore Cloud should not present itself as an Obsidian
integration. The stronger story is that Obsidian-like structure inspired our
AI-readable library model: raw source holdings, shelves, library ids, citations,
borrowing receipts, Zhiyi preferences, Xingce experience, and provenance across
multiple local agents.

### memvid competitor profile

memvid is a competitor in the append-only, versioned memory-archive lane. It
leads with "traditional memory is either too heavy with databases or lacks
traceable versions", then names the functional answer: borrow video-encoding
ideas, split AI memory into immutable "intelligent frames", and pack memory,
index, and metadata into a single `.mv2` file.

Core value named in the sample:

- append-only rather than in-place modification;
- history stays traceable;
- time-travel view of memory state at any moment;
- committed data survives crashes;
- video-style compression keeps files small;
- local sub-5ms query response;
- offline, multimodal, and model-independent;
- useful for long-running agents and audit-heavy offline-first, medical, legal,
  or financial scenarios.

Useful lesson for Memcore Cloud: immutable history and time-travel are strong
trust promises. Strategic contrast: memvid sells a compact `.mv2` memory file
with frame-like versioning; Memcore Cloud should sell a local library whose
trust base is original source records, raw mirrors, record chains, library ids,
borrowing receipts, and reviewable Zhiyi/Xingce evolution. The public story
should make "original records never get replaced by summaries" as concrete as
memvid's "append-only intelligent frames".

## Competitor Comparison Table

This table is for positioning work. Feature claims about competitors are based
on public project pages/docs at the time of review and should be rechecked
before being used in public copy.

| Project | Lane | Publicly visible functional promise | Strongest user hook | Memcore Cloud contrast |
| --- | --- | --- | --- | --- |
| [Mem0](https://github.com/mem0ai/mem0) | Universal memory layer for agents and apps | Long-term memory for AI assistants and agents; remembers preferences, adapts to users, supports personalized assistants, support bots, and autonomous systems. Mem0 docs also promote MCP so agents can decide when to save, search, and update memories. | "Drop-in memory" and personalization for production apps. Easy to understand and easy to adopt. | Memcore Cloud should not compete as a generic hosted memory API. The stronger lane is local source-backed continuity: original records, library ids, borrowing receipts, Zhiyi preferences, Xingce experience, and multi-agent local use. |
| [Memobase](https://github.com/memodb-io/memobase) | AI application memory backend | User-profile long-term memory for LLM apps. README emphasizes LOCOMO performance, built-in per-user buffering for lower LLM cost, online latency under 100ms, SDK/API style adoption, and app scenarios like companions, education, and assistants. | "Memory is expensive and slow; we make it cheap and fast." Clear for app developers. | Do not fight on latency/SDK breadth first. Memcore Cloud should say: "AI did work on your machine; we keep original evidence and reusable experience so the next local agent does not start over." |
| [agentmemory](https://github.com/rohitg00/agentmemory) | Local memory server for coding agents | Persistent memory for Claude Code, Codex CLI, Cursor, Gemini CLI, Hermes, OpenClaw, OpenCode, and MCP clients. Public README emphasizes hooks/MCP/REST, shared memory server, and coding-agent context continuity. | Very close to our user: coding agents forget project facts and prior fixes. Strong "works with every agent" message. | This is a direct local-agent competitor. Memcore Cloud must make the difference concrete: not only capture/search/inject, but source-of-truth raw records, five shelves, library ids, borrowing receipts, Zhiyi/Xingce separation, and reviewable experience adoption/rollback. |
| [Memary](https://github.com/kingjulio8238/Memary) | Knowledge-graph agent memory | Agent memory through a knowledge graph; the public repo describes querying existing nodes and doing external search when no related entities exist, with a plan to support any type of agent from any provider. | "AI remembers through a relationship network." The graph metaphor is easy to explain. | Memcore Cloud should avoid sounding like just another graph. Our metaphor is a library: holdings, shelves, source records, library ids, borrowing receipts, and experience lifecycle. |
| [LangMem](https://github.com/langchain-ai/langmem) | Agent self-improvement and procedural memory | Extract important information from conversations, optimize agent behavior through prompt refinement, maintain long-term memory, support hot-path record/search tools, background memory manager, and native LangGraph long-term store integration. | "Agents learn and adapt over time." Strong self-improvement story with LangGraph production fit. | This is the closest conceptual competitor for "experience evolves." Memcore Cloud should stress that Xingce is not just prompt optimization: it is source-backed work paths with validation receipts, adoption, errata, upgrade, rollback, and cross-tool local access. |
| [MCP memory server / KnowledgeGraphMCP family](https://github.com/modelcontextprotocol/servers/blob/main/src/memory/index.ts) | Lightweight local graph memory | Reference memory server stores entities, relations, and observations in a graph structure and exposes tools such as `create_entities`, `create_relations`, `add_observations`, `read_graph`, `search_nodes`, and `open_nodes`. Storage is local JSONL-style graph data. | "No database; entities and relations in a local file." Lightweight and easy to reason about. | Memcore Cloud should not be reduced to entity/relation CRUD. Our selling point is evidence governance: raw holdings, source refs, record health, five shelves, and borrowing/adoption receipts. |
| [cognee](https://github.com/topoteretes/cognee) | Hybrid knowledge infrastructure | Open-source AI memory platform. Ingests data in many formats and builds a self-hosted knowledge graph; combines vector embeddings, graph reasoning, and ontology generation so documents are searchable by meaning and connected by relationships. | "Vector search plus graph reasoning." Strong developer/infrastructure pitch. | cognee is broad knowledge infrastructure. Memcore Cloud should sell the trust layer for local AI work: provenance-first recall, library ids, original records, Zhiyi preferences, Xingce experience, and visible receipts. |
| [ObsidianMCP / obsidian-mcp-server](https://github.com/cyanheads/obsidian-mcp-server) | Local notes copilot | MCP server for Obsidian vaults: read, write, search, surgically edit notes, tags, and frontmatter via the Obsidian Local REST API plugin. | "Your existing Obsidian vault becomes AI-operable." Strong for note-taking users. | Adjacent, not core direct. Memcore Cloud should not present as an Obsidian integration. We borrow AI-readable note structure, but authority comes from raw records, shelves, citations, receipts, Zhiyi, and Xingce across agents. |
| [memvid](https://github.com/memvid/memvid) | Append-only single-file memory archive | Memory layer for AI agents using a single `.mv2` file. Smart Frames are immutable units with timestamps, checksums, and metadata; official README emphasizes append-only writes, queries over past memory states, and timeline-style inspection. | "Your AI memory is one portable, rewindable file." Very concrete and memorable. | memvid owns the single-file/time-travel image. Memcore Cloud should make our trust claim equally concrete: "原始记录是馆藏原件，摘要不能替代；每次召回有馆藏号和借阅回执；经验采纳可回源、可回滚。" |

### Positioning Implications

- If the competitor sells **speed/cost** (Memobase), we sell **source-backed
  local continuity**.
- If the competitor sells **graph memory** (Memary, KnowledgeGraphMCP, cognee),
  we sell **library governance over raw records plus graph-like recall only when
  it helps**.
- If the competitor sells **self-improvement** (LangMem), we sell **reviewable
  experience evolution with receipts**, not black-box self-training.
- If the competitor sells **local notes** (ObsidianMCP), we sell **AI-readable
  library structure without requiring a note app**.
- If the competitor sells **portable append-only archive** (memvid), we sell
  **original holdings plus borrowing/adoption receipts**.
- If the competitor sells **coding-agent shared memory** (agentmemory), we must
  lead with our sharpest concrete differences: raw source records, five shelves,
  library ids, borrowing receipts, Zhiyi/Xingce split, and cross-agent Xingce
  experience.

## Functional Implementation Matrix

This section compares implementation maturity, not slogans. It is based on a
local repo inspection pass plus public README/docs. Recheck before publishing
claims.

## Benchmark Score Reading

Use a 100-point scale when comparing against public memory benchmark writeups,
because most competitors present percentages or 0-100 scores rather than raw
0-1 decimals.

Current Memcore Cloud diagnostic numbers:

| Area | Dataset / evaluator | Current score | Comparable to competitor marketing? | Reading |
| --- | --- | ---: | --- | --- |
| Evidence retrieval | LoCoMo locomo10 no-key diagnostic, top5 exact | 66.5/100 | Partial | Shows raw evidence can often be found, but LoCoMo identity/relationship questions still need better entity/time routing. |
| Evidence retrieval | LoCoMo locomo10 no-key diagnostic, top5 bundled | 82.3/100 | Partial | Stronger if adjacent raw evidence bundles are counted, but this is still retrieval, not final QA. |
| Evidence retrieval | LongMemEval oracle no-key diagnostic, top5 exact | 82.6/100 | Partial | Good source-finding signal; the system usually gets to the right raw turn. |
| Evidence retrieval | LongMemEval oracle no-key diagnostic, top5 bundled | 91.2/100 | Partial | Strong raw-record premise: the answer is often in the borrowed evidence bundle. |
| QA official-like binary | LongMemEval oracle full=500, Codex `gpt-5.5 / xhigh` local judge | 39.4/100 | No | Closer to LongMemEval yes/no evaluation because partial cases do not score. Not an official leaderboard score and not GPT-4 API evaluator. |
| QA internal half-credit | LongMemEval oracle full=500, Codex `gpt-5.5 / xhigh` local judge | 43.7/100 | No | Useful for miss analysis because partial cases get half credit, but do not use it as the official-like comparison score. |

Interpretation:

- Against Mem0 / Mastra / Supermemory-style public claims, Memcore Cloud should
  not claim SOTA yet. Their public numbers are often QA or recall percentages
  in the 80-95+ range, while our current full=500 official-like binary accuracy
  is 39.4/100.
- The more favorable honest comparison is diagnostic depth: Memcore Cloud now
  publishes full-run coverage, missed-case buckets, raw/source evidence
  boundaries, and separates retrieval strength from answer-synthesis weakness.
- The public headline should therefore be "source-backed local AI memory with
  reproducible diagnostics", not "best benchmark score".
- The next score target before louder public comparison should be roughly
  55-65/100 on full=500 official-like binary accuracy, while keeping
  LongMemEval exact source recall above 80/100 and bundled recall above 90/100.

Legend:

- **✅ mature**: implemented as code/package/service/tests, not just roadmap.
- **🟡 partial**: implemented but narrower, less visible, or not polished enough
  for users to feel immediately.
- **⚪ not core**: not the product's main job or not clearly present.
- **❌ absent**: no meaningful implementation found in the inspected repo.

| Project | Install / entrypoint | Storage model | Automatic capture / hot path | Retrieval | Agent integration | Experience / self-improvement | Provenance / audit / versioning | UI / diagnostics | Implementation read |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Mem0 | ✅ PyPI/npm/CLI, self-host server, cloud, skills | ✅ vector stores, graph/entity signals, server/cloud storage | 🟡 agents can call add/search; not a local all-agent capture daemon by default | ✅ semantic + BM25 + entity + temporal in current README | ✅ SDK/API/MCP/skills; strong app integration | 🟡 "learns over time" and agent-generated facts, but not review-gated experience | 🟡 metadata and memory history, not raw-source-first library governance | ✅ dashboard/cloud and self-host surfaces | Very mature generic memory product; high stars are deserved by SDK breadth, benchmarks, cloud path, and easy quickstart. |
| Memobase | ✅ Python/Node/Go SDK, FastAPI service, MCP, Docker | ✅ Postgres + Redis profile/event memory | 🟡 buffered batch processing after chats; app must send blobs | ✅ profile/event context, time-aware memory, LOCOMO claims | ✅ API/SDK/MCP for LLM apps | 🟡 user profiles evolve; less about agent work procedures | 🟡 telemetry/auth/cache; not raw source library | ✅ playground/docs; production service shape | Mature app-backend lane: cheap/fast profile memory for products, not local agent work continuity. |
| agentmemory | ✅ npm/npx CLI, `connect`, MCP package, skills | ✅ local engine with SQLite/iii, hybrid indexes | ✅ many agent hooks; captures sessions/tool use; import JSONL; replay | ✅ BM25 + vector + graph fusion, temporal graph, benchmarks | ✅ strongest: Claude Code, Codex, Cursor, Hermes, OpenClaw, OpenCode, etc. | ✅ lessons, consolidation, skill extraction, auto-forget/lifecycle code | 🟡 replay/audit/governance exist, but not framed as raw source-of-truth holdings | ✅ real-time viewer, doctor, demo, benchmarks | Closest direct competitor. It wins on obvious "it just plugs into every agent and feels smarter" implementation. |
| Memary | ✅ PyPI, Streamlit app | 🟡 JSON memory streams plus FalkorDB/Neo4j option | 🟡 auto-generated memory inside its ChatAgent demo path | 🟡 KG recursive retrieval / multi-hop described; smaller codebase | ⚪ no MCP in repo; provider-agnostic support is future-facing | 🟡 memory modules / dashboard improvement ideas; some items are roadmap | 🟡 memory stream timestamps; rewind is marked coming soon | 🟡 Streamlit demo | Real implementation, but lighter/research-demo maturity than high-star infra projects. |
| LangMem | ✅ PyPI package | ✅ LangGraph BaseStore / long-term store | ✅ hot-path tools plus background memory manager | ✅ search/manage memory tools; graph RAG module | 🟡 excellent inside LangGraph; no standalone MCP/server in repo | ✅ core strength: prompt optimization + procedural/semantic memory | ⚪ relies on store/app ecosystem; not raw-source-first | 🟡 docs/examples/tests; no standalone dashboard | Small repo, but high leverage because it rides LangGraph. Strong on self-improvement primitives, weaker as turnkey local product. |
| MCP memory / KnowledgeGraphMCP family | ✅ official MCP server via npx/Docker | ✅ local JSONL graph file | 🟡 only when the agent calls tools | 🟡 entity/type/observation string search; graph open/read tools | ✅ Claude Desktop/MCP-native | ⚪ no experience lifecycle | ⚪ JSONL persistence, but no evidence/receipt/version governance | ⚪ minimal | Narrow but complete. It gets adoption because it is official, tiny, and obvious. |
| cognee | ✅ pip/uv, CLI, Docker, MCP, cloud/local service, plugins | ✅ self-hosted knowledge graph + vector/semantic layer | ✅ session memory and Claude Code hook path described; permanent graph sync | ✅ vector + graph reasoning + auto-routing | ✅ Python API, CLI, MCP, Claude Code/OpenClaw integration paths | 🟡 `improve`, feedback/learning positioning; implementation broad but complex | ✅ observability/audit traits/OTEL modules visible | ✅ frontend/local UI/visualization, docs, examples | Very mature knowledge-infra competitor. It wins on breadth: graph/vector/UI/MCP/Docker/evals. |
| ObsidianMCP | ✅ npm/Bun, MCPB, Docker, Cursor/VS Code/Claude install buttons | ✅ delegates to existing Obsidian vault via Local REST API | ⚪ no memory extraction; it is a tool server | ✅ text/JSONLogic/Omnisearch/BM25 note search | ✅ MCP with 14 tools / 3 resources | ⚪ no agent experience evolution | ✅ path permissions, read-only mode, typed errors, destructive confirmation | ✅ status resource/logging; tool-level diagnostics | Very solid tool integration. Not a memory system, but a polished local notes copilot. |
| memvid | ✅ Rust crate, CLI, Node/Python/Rust SDKs, Docker | ✅ single `.mv2` file with Smart Frames | ⚪ no first-party agent hook/MCP in main repo | ✅ local search, BM25/vector features, smart recall claims | 🟡 SDK/CLI; agent integration left to users/adjacent packages | ⚪ no procedural experience governance | ✅ strongest: append-only frames, checksums, time-travel/history | 🟡 docs/sandbox/benchmarks; no full agent dashboard | Strong core engine/format. It wins because the artifact is simple: one portable rewindable memory file. |
| Memcore Cloud / Yifanchen | 🟡 installers, local console, MCP bridge, skill/instruction path | ✅ raw records, canonical index, five shelves, source refs | 🟡 local capture/connectors exist, but user-facing hot-path intervention is not yet strong enough | 🟡 source-backed recall, active/window/project scopes, work_preflight; no public benchmark yet | 🟡 Codex/Claude/OpenClaw/Hermes/Cursor-style support, but not as one-command-obvious as agentmemory | 🟡 Xingce candidates, validation/adoption/rollback receipts; Hermes skill diff dry-run. Strong concept, still needs more automatic visible use. | ✅ strongest: raw source-of-truth, library ids, borrowing/consumer receipts, Record Doctor, lost-source/lost-raw checks | 🟡 local console and record doctor exist; not yet a polished growth/benchmark dashboard | Technically real, with 533 local tests passing in this audit. Differentiation is evidence-first local library plus experience governance; biggest gaps are ease of connection, automatic intervention, and public proof. |

### Engineering Gap Notes

The high-star projects are high-star for concrete reasons:

- Mem0 and Memobase are easy to adopt in applications: SDKs, server/cloud path,
  benchmarks, docs, and productized onboarding.
- agentmemory is dangerous for us because it directly solves local coding-agent
  continuity with one command, many hooks, viewer, doctor, demo, and benchmark
  claims.
- cognee is dangerous for knowledge infrastructure because it ships graph,
  vector, UI, MCP, Docker, examples, and observability in one story.
- memvid is dangerous because one file, append-only frames, and time travel are
  concrete enough for users to remember.
- ObsidianMCP is narrower but polished: many typed tools, permissions, status
  resources, and install buttons.

Memcore Cloud's real implementation advantage is narrower but distinctive:

- original records stay as source-of-truth holdings;
- `raw`, `zhiyi`, `xingce`, `toolbook`, and `errata` are trust boundaries, not
  just folders;
- source refs, raw excerpts, library ids, and borrowing/consumer receipts are
  part of recall;
- Record Doctor checks lost source, lost raw, canonical indexes, and record
  health before asking users to trust memory;
- Xingce experience can move through candidate, evidence, validation, adoption,
  errata, upgrade, and rollback.

The next implementation work should therefore not add another storage layer. It
should make the existing advantages visible and automatic:

1. one-command connect/doctor for each major local agent;
2. hot-path preflight that is visibly called before work;
3. a small reproducible recall/experience benchmark;
4. a local viewer that shows holdings, recalls, and borrowing receipts;
5. a clear "experience candidate -> adopted Xingce -> reused by another agent"
   demo.

### Memcore Cloud feature framing to keep

Memcore Cloud should not sound like another graph memory backend. Its functional
story should be:

- solve "local agents forget, redo work, and cannot explain where memory came
  from";
- after connection, local agents share one library of original records,
  preferences, boundaries, corrections, and reusable work experience;
- original records are the source-of-truth holdings;
- library ids locate memories and experience;
- borrowing receipts show what an agent used before answering;
- Zhiyi keeps identity, preferences, corrections, habits, and boundaries;
- Xingce keeps repair paths, validation steps, gotchas, SOPs, and experience
  candidates;
- experience is not private to Hermes, Codex, Claude, or OpenClaw; skill-,
  custom-instruction-, and MCP-capable agents can read the same Xingce before
  acting;
- Hermes skill evolution is a specific strong example: skill changes and Xingce
  experience can produce source-backed upgrade/adoption candidates.

## Product Story To Keep

- Keep the homepage centered on user tasks: preserve local records, recall prior
  context, reuse proven work paths, and verify answers from source evidence.
- Raw records are the trust basis: public copy should say source-backed, raw
  records, source refs, receipts, and record chain.
- AI-readable knowledge sediment should reuse the existing five shelves instead
  of adding a sixth Obsidian-like layer:
   - `raw`: original records and source material.
   - `zhiyi`: preference, intent, corrections, and stable understanding.
   - `xingce`: work experience, methods, validation paths, and adoption status.
   - `toolbook`: tool-facing usage knowledge and operational notes.
   - `errata`: corrections, conflicts, and trust repair.
- Quiet recall remains a feature: default to compact source refs, counts,
  receipts, and rank reasons; raw excerpts are explicit and bounded.

## What Not To Lead With

- Do not present this as an Obsidian integration. Markdown-like, AI-readable
  structure is an inspiration, not a product dependency.
- Do not present Xingce as a Skill marketplace. Xingce is experience sediment
  and validation governance.
- Do not put detailed connector matrices in the main public story. Public copy
  can say "supports local AI tool connection"; maintainer docs can keep the
  detailed integration table.
- Do not mention private local agent-rule files or maintainer-only repository
  mechanics.

## Suggested README Shape

1. Hero:
   "Keep local AI agents from starting over."

2. Feature list:
   shared local context, automatic local records, source-backed recall,
   reusable work paths, Record Doctor, local console, no cloud account, simple
   install.

3. Quick demo:
   local console, safe capability check, one sample real recall question.

4. Proof blocks:
   - "Records are guarded": record doctor / record chain.
   - "Recall is source-backed": source refs and bounded raw excerpts.
   - "Experience can improve": Xingce candidates, validation receipts, apply
     gates, rollback receipts.

5. Install:
   simple commands plus double-click installer entries for macOS and Windows.

6. Safety first:
   capability check before real recall.

## Short Chinese Homepage Copy

忆凡尘让本机 AI 工具保留可回源的工作上下文：自动保留本机对话记录，按来源归档；问旧决定、偏好、修复办法或项目边界时，默认返回来源线索和命中理由；需要原文时，再展开有界证据。

它不只找回“说过什么”，也保留“下次怎么做”：排障顺序、复核步骤、项目规矩、踩坑记录和验收办法，都可以变成下一次可参考的工作路径。行策经验不是某个工具的私有 skill；支持 skill、自定义指令或 MCP 的本机 agent，都能在动手前读取同一套经验。经验会进化，但不黑箱；做成、踩坑、纠错会先进入候选馆藏，带来源、原文和验收条件后才能采纳进行策，后续还能升级、勘误或回滚。记录医生会先证明记录链路守住了，再让你测试真实召回。

## Release Decision Notes

- 2026.6.16 is still a local candidate until the user explicitly authorizes
  push, tag, or GitHub Release publication.
- The candidate package must be rebuilt after any README or release-note edits
  that should ship.
- Public release claims should only cite validation actually run in the current
  candidate pass.
