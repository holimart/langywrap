# Memento-Skills: Let Agents Design Agents — Research Report

## Citation

**Full Title:** Memento-Skills: Let Agents Design Agents
**ArXiv ID:** 2603.18743v1
**Link:** https://arxiv.org/abs/2603.18743
**Published:** March 19, 2026
**GitHub:** https://github.com/Memento-Teams/Memento-Skills
**Live site:** https://skills.memento.run/

**Authors:** Huichi Zhou, Siyuan Guo, Anjie Liu, Zhongwei Yu, Ziqin Gong, Bowen Zhao, Zhixun Chen, Menglong Zhang, Yihang Chen, Jinsong Li, Runyu Yang, Qiangbin Liu, Xinlei Yu, Jianmin Zhou, Na Wang, Chunyang Sun, Jun Wang

---

## 1. Core Concept

Memento-Skills is a **generalist, continually-learnable LLM agent system that functions as an agent-designing agent**: it autonomously constructs, adapts, and improves task-specific agents through experience — without updating any LLM parameters.

The central insight: **skills stored as structured, executable files are the persistent memory of the system.** Instead of encoding knowledge in weights (fine-tuning), knowledge is encoded in an evolving library of reusable skills. When the agent encounters a new task, it either retrieves an existing skill, composes multiple skills, or generates a new one — and then reflects on the result to improve the skill for next time.

This is sometimes called "deployment-time learning": the agent learns live, during operation, using its own outputs as training signal — but the training target is the skill library, not the model.

### Predecessor: Memento (2025)

The earlier paper ("Memento: Fine-tuning LLM Agents without Fine-tuning LLMs", arxiv.org/abs/2508.16153) established the memory-based reinforcement learning foundation:

- Frames agent improvement as a **Memory-augmented Markov Decision Process**
- Stores experiences in episodic memory (non-parametric or differentiable)
- Uses **memory rewriting** as the policy update mechanism (instead of gradient descent)
- Achieved 87.88% Pass@3 on GAIA validation, 79.40% on test set
- Core principle: *"Learn from experiences, not gradients"*

Memento-Skills extends this to a full multi-agent architecture where skills are the memory units and agents can generate other agents.

---

## 2. How Agents Design Other Agents via Skills

The "agents designing agents" mechanism works through three layers:

### Layer 1: Skill Generation
When a task arrives that no existing skill can handle, the agent calls its **skill builder** to synthesize a new skill from scratch. The builder uses the LLM to:
- Analyze the task requirements
- Identify what capability is missing from the current library
- Generate executable skill code (functions, prompts, tool calls) with metadata

The generated skill is immediately usable and stored persistently.

### Layer 2: Skill Mentorship
Higher-capability agents can synthesize task-specific skills for lower-tier agents by:
- Observing what challenges the sub-agent encounters
- Documenting solution strategies as retrievable skill objects
- Enabling structured knowledge transfer across an agent population

### Layer 3: Skill Market
Skills can be shared via a cloud catalogue ("Skill Market"), enabling agents across deployments to benefit from collectively accumulated capabilities. This is the distributed compounding layer.

---

## 3. The Skill Creation and Refinement Loop

The system implements a **4-stage Read-Execute-Reflect-Write cycle**:

```
Intent → Planning → Execution → Finalize
  ↑                                  |
  |         (Reflect phase)          |
  └──────── update/regenerate ───────┘
```

### Stage 1: Intent
Parse user task into a structured representation. Identify the task domain, required capabilities, and constraints.

### Stage 2: Planning (Read)
The **skill router** performs hybrid retrieval:
- `local_db_recall` — query local database by skill name/tags
- `local_file_recall` — filesystem-based discovery
- `remote_recall` — cloud catalogue downloads
- **Hybrid BM25 + semantic vector search** for retrieval

Router selects the highest-utility existing skill, or triggers the builder to generate a new one. The stateful prompt is updated with the selected skill context.

### Stage 3: Execution
Run the selected skill in a sandboxed environment using **ReAct reasoning** (Thought → Action → Observation loops). The Tool Bridge layer handles:
- Argument marshalling
- Sandboxed execution
- Result validation
- Error recovery

### Stage 4: Finalize + Reflect (Write)
After execution, the Reflection phase:
- Records success/failure
- Updates **utility scores** for the used skill
- Diagnoses *which specific skill* underperformed (not just "task failed")
- Regenerates weak skill code and persists the improved version
- Optionally generates new skills for capability gaps encountered

The agent learns from failure by rewriting the skill, not by retrying with the same broken tool.

---

## 4. How Skills Are Stored and Composed

### Storage Backend (Three-Layer)

```
Skill Storage
├── file_storage/      # Filesystem skill definitions (markdown/code files)
├── db_storage/        # Database-backed skill catalog with metadata
└── vector_storage/    # Semantic embeddings for routing
```

### Skill Object Structure
Each skill is a structured unit containing:
- **Executable content**: code, prompt template, or tool call sequence
- **Metadata**: name, tags, domain, creation timestamp
- **Utility tracking**: success count, failure count, last-used timestamp
- **Execution history**: recent ReAct traces for reflection context

Skills are stored as **structured markdown files** (following the Memento v1 convention of "stateful prompts") with embedded executable sections.

### Skill Composition
Skills compose **hierarchically**:
1. Atomic skills handle single-step operations (web search, file read, terminal command)
2. Composite skills chain atomic skills for multi-step workflows
3. Agent-level skills orchestrate entire reasoning pipelines

When a task exceeds any single skill's scope, the planner assembles a composite skill dynamically. Composition happens at plan time, not design time — the agent decides the composition based on task context.

### Skill Evolution Path
```
elementary skills → composite skills → specialized agents → agent pipelines
(web search)        (research workflow)  (domain expert)     (multi-agent team)
```

The library grows from atomic tools into a richer, self-repairing, semantically-indexed memory of capabilities.

---

## 5. Key Architecture Decisions

### Decision 1: Skills as External Memory, Not Weights
All learning happens through skill library evolution. The underlying LLM is frozen. This means:
- No GPU retraining cost
- Real-time adaptation
- Skills are inspectable, editable, and versionable
- Rollback is trivial (restore previous skill file)

### Decision 2: Bounded Context Architecture
The codebase separates concerns into pluggable phase modules:

```
core/agent/          — 4-stage orchestrator
core/skill/builder/  — programmatic skill generation
core/skill/loader/   — discovery and loading pipeline
tool_bridge/         — tool invocation with isolation
execution/           — composable policy modules
```

Each phase has entry/exit hooks for middleware injection. Safety and execution control are **policy-as-code** (composable modules: tool_gate, path_validator, error_recovery, loop_detector) rather than monolithic logic.

### Decision 3: Utility-Driven Skill Selection
Skills carry utility scores updated after every execution. The router prefers high-utility existing skills before generating new ones — prevents skill library bloat and reinforces proven patterns.

### Decision 4: Stateful Prompts as the Learning Unit
The "stateful prompt" is the fundamental representation: a prompt that carries execution history, selected skill context, and intermediate results. When skills are updated, the prompt template is updated — not model weights.

### Decision 5: Hybrid Retrieval (BM25 + Semantic)
Pure semantic search misses exact-match cases; pure BM25 misses paraphrase. The hybrid approach handles both structured queries (skill names, tags) and fuzzy intent matching.

### Decision 6: Three-Layer Configuration Isolation
```json
{
  "llm": {
    "active_profile": "default",
    "profiles": {
      "default": {
        "model": "openai/gpt-4o",
        "api_key": "...",
        "base_url": "https://api.openai.com/v1"
      }
    }
  }
}
```
System config (read-only defaults) → User config (persistent) → Runtime config (merged). Fields marked `x-managed-by: user` are protected during auto-migration. Pydantic validation with JSON Schema throughout.

---

## 6. Relation to Compound Engineering and Knowledge Accumulation

Memento-Skills is a formalization of the **compound engineering** pattern at the agent-system level:

| Compound Engineering Concept | Memento-Skills Equivalent |
|------------------------------|---------------------------|
| `docs/solutions/` episodic memory | Skill library (file_storage + db_storage) |
| Lessons learned capture | Reflect phase → skill rewrite |
| Sub-agent definitions | Skill objects (agent-level skills) |
| Knowledge accumulation over time | Utility score evolution + library growth |
| Retrieval-augmented generation | BM25 + semantic hybrid recall |
| Working memory (notes/) | Stateful prompt (execution context) |

### The Core Parallelism
Compound engineering says: *capture what worked, retrieve it next time, avoid repeating mistakes*. Memento-Skills implements this as a closed automated loop — the agent does the capture and retrieval itself, without human intervention.

### Knowledge Accumulation Properties
Memento-Skills achieves several properties that manual compound engineering aspires to:
1. **Non-forgetting**: Skills persist; the library never shrinks unless explicitly pruned
2. **Compositional growth**: New skills build on old ones
3. **Self-repair**: Failed skills are diagnosed and rewritten, not abandoned
4. **Cross-instance transfer**: Skill Market enables knowledge to move between agent deployments
5. **Measurable improvement**: Utility scores provide a quantitative signal of accumulated knowledge

### Experimental Evidence of Compounding
- GAIA benchmark: **26.2% relative improvement** over baseline through accumulated skills
- Humanity's Last Exam: **116.2% relative improvement** — a task specifically designed to resist pattern matching, showing genuine capability accumulation rather than memorization

---

## 7. Implementation Approach

### Technology Stack
- **Language**: Python
- **Validation**: Pydantic with JSON Schema
- **Vector storage**: Embedding models (not specified, pluggable)
- **Retrieval**: Hybrid BM25 + semantic search
- **Execution**: Sandboxed ReAct loops
- **Config**: Three-layer JSON with auto-migration
- **Surfaces**: CLI, desktop GUI (Flet-based), Feishu/DingTalk/WeCom/WeChat messaging
- **Testing**: 97 test files covering skills, config, context, tools, security

### Directory Structure
```
memento-skills/
├── core/
│   ├── agent/           # 4-stage pipeline orchestrator
│   ├── skill/
│   │   ├── builder/     # Skill generation
│   │   └── loader/      # Discovery and loading
│   └── execution/       # Policy modules (tool_gate, validator, recovery)
├── builtin/             # 10 pre-packaged elementary skills
├── tool_bridge/         # Tool invocation isolation layer
├── middleware/
│   └── im/              # Feishu, DingTalk, WeCom, WeChat gateways
├── cli/
├── gui/
├── daemon/
└── tests/               # 97 test files
```

### Skill Verification
`memento verify` — audits the skill library for correctness, coverage, and utility score validity.

### Skill Market
A remote cloud catalogue where skills can be published and downloaded. The `remote_recall` pathway in the router queries this catalogue when local retrieval fails. This is the mechanism for cross-deployment knowledge transfer.

### Planner-Executor Pattern (from Memento v1)
The base architecture uses a two-tier hierarchy:
- **Meta-Planner** (e.g., GPT-4.1): strategic task decomposition into JSON-structured subtasks
- **Executor** (e.g., o3): tactical execution using MCP tools

This hierarchy persists in Memento-Skills, with skills mediating the interface between planning and execution.

---

## 8. Implications for a Repo Storing Evolving Agent Configurations

The llmtemplate repo already implements core compound engineering patterns. Memento-Skills suggests several concrete extensions:

### 8.1 Treat Claude Slash Commands as Skills
Each `.claude/commands/*.md` file is already structurally analogous to a Memento skill:
- Named capability
- Executable prompt template
- Domain-specific logic

**Extension**: Add metadata frontmatter to each command file tracking utility (usage count, success rate, last modified). Build a lightweight router that selects commands based on task similarity.

### 8.2 Implement Read-Execute-Reflect-Write on Solutions
The `docs/solutions/` directory (compound engineering) captures past solutions. Memento-Skills suggests a tighter loop:
1. Before a task: retrieve semantically similar past solutions (Read)
2. After a task: write the solution with structured metadata (Write)
3. On failure: diagnose which solution component failed, update it (Reflect)

Currently the compound skill does steps 1 and 2 manually. Automating step 3 closes the loop.

### 8.3 Utility Scoring for Agent Definitions
Each `.claude/agents/*.md` agent definition should carry utility metadata:
```yaml
---
usage_count: 47
success_rate: 0.89
last_used: 2026-04-01
domains: [security, smart-contracts]
---
```
This enables automated routing: given a task, select the highest-utility agent with domain overlap.

### 8.4 Skill Composition via Agent Pipelines
The ralph-loop pattern (tree-search ML experimentation) maps directly to Memento's composite skill concept. A ralph-loop is a composed pipeline of: planner skill + executor skill + evaluator skill + reflection skill. Making this composition explicit and storable enables reuse across different problem domains.

### 8.5 Three-Layer Config Pattern
Adopt Memento's config isolation:
- `system_config.json` — repo defaults (committed)
- `~/.llmtemplate/config.json` — user overrides (gitignored)
- Runtime merge — applied at agent startup

This prevents config drift between users while preserving local customization.

### 8.6 Skill Market as Shared Library
The `.claude/commands/` directory is currently local. Memento's Skill Market pattern suggests: maintain a curated set of "published" commands that can be pulled into any project using the llmtemplate blueprint — analogous to how `execwrap-setup` copies scripts from llmtemplate into target repos.

### 8.7 Stateful Prompt Format for Long-Running Agents
For agents that run across multiple sessions (ralph-loop, compound loop), adopt the stateful prompt pattern: persist execution state (current plan, intermediate results, skill selections) to a file. On resumption, load this state as context before the first LLM call.

---

## Summary

Memento-Skills is the most complete published implementation of the insight that **knowledge accumulation in AI systems should be stored as executable, versioned, composable artifacts — not as gradient updates to model weights**. The skill library is a living codebase that grows, self-repairs, and compounds over time.

The architecture is directly applicable to any repo that manages evolving agent configurations: treat each agent definition, command, and solution as a skill object with utility metadata, implement hybrid retrieval at task dispatch time, and close the loop with automated reflection that rewrites underperforming components.

The 116% improvement on Humanity's Last Exam is particularly significant: it demonstrates that this pattern generalizes beyond pattern-matched benchmarks and produces genuine capability accumulation.

---

## Sources

- [Memento-Skills: Let Agents Design Agents (arXiv)](https://arxiv.org/abs/2603.18743)
- [PDF (arXiv)](https://arxiv.org/pdf/2603.18743)
- [GitHub: Memento-Teams/Memento-Skills](https://github.com/Memento-Teams/Memento-Skills)
- [Memento-Skills live site](https://skills.memento.run/)
- [Memento: Fine-tuning LLM Agents without Fine-tuning LLMs (arXiv)](https://arxiv.org/abs/2508.16153)
- [HuggingFace paper page](https://huggingface.co/papers/2603.18743)
- [Medium: Exploring Memento](https://medium.com/the-ai-forum/exploring-memento-fine-tuning-llm-agents-without-fine-tuning-llms-4a76bf918cdd)
