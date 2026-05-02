# Agent Task Database Requirements

Date: 2026-04-28

## Context

We explored replacing `tasks.md`-style task state in repos like `compricing`, `riemann2`, `sportsmarket`, and `whitehacky` with a more structured system that supports agent loops, multiprocess coordination, Git persistence, and downstream workflow-specific behavior.

This note captures the current analysis and requirements baseline before deeper external research.

## Current Loop Findings

The existing Ralph-style loops are not uniform:

- `compricing` and `sportsmarket` effectively run `orient -> execute -> finalize`, but `orient` is really an `orient+plan` step that both selects work and mutates `tasks.md` up front.
- `riemann2` uses a truer `orient -> plan -> execute -> finalize` flow, but still relies on Markdown task parsing and LLM-text-driven cycle classification.
- `whitehacky` uses `orient` as a routing step that decides both `TASK_TYPE` and the concrete task, with many downstream branches depending on that output.

Main problem uncovered: `tasks.md` is currently doing three jobs at once:

1. Human planning
2. Canonical machine state
3. Runtime coordination / claiming

That makes it fragile for multiple concurrent loops or hosts.

## Architectural Direction Uncovered

The refactor direction is toward an agent-first PM/task database:

- one logical source of truth
- structured canonical task state
- runtime claims separated from canonical Git-persisted state
- sparse / dynamic fields
- support for many different downstream workflow interpretations

Important nuance uncovered during exploration:

- task type must be allowed to come from canonical task data
- task type must also be allowed to be inferred or proposed by downstream code or LLM output
- downstream orchestration may decide effective task type, commit policy, merge-request policy, execution routing, etc.
- therefore the database should remain workflow-neutral and policy-light

## Goal

Design a database for agent task management that acts like a neutral core under something closer to an agent-native Jira/YouTrack, rather than a loop-specific queue.

It must support:

- multiple machines
- multiple processes
- many readers
- low-frequency writes
- task claims / leases
- liveness inspection of claimants
- Git-persisted deeper state
- non-Git runtime coordination
- CLI and script-library access
- sparse evolving metadata
- downstream workflow diversity

## Core Principles

1. Canonical task state and runtime coordination are separate concerns.
2. Canonical state must be human-inspectable and Git-friendly.
3. Runtime state must be queryable live and allowed to disappear.
4. The database must not encode workflow policy that belongs downstream.
5. Schema must tolerate sparse, evolving metadata without constant migrations.
6. Task type may be declared by canonical data, inferred by code, or proposed by LLM output.

## Requirements

### 1. Source Of Truth

The system must provide a single logical source of truth for task state.

That source of truth must include:

- task identity
- current lifecycle state
- dependencies
- provenance
- priority
- long-form notes / rationale
- structured metadata
- history of meaningful state changes

The source of truth must be durable across process restarts and machine restarts.

The source of truth must be inspectable without a running server.

### 2. Separation Of Canonical And Runtime State

The system must distinguish between:

- canonical persistent state
- runtime ephemeral state

Canonical persistent state includes:

- task definitions
- status changes
- dependencies
- tags
- notes
- policy-relevant metadata
- workflow decisions worth preserving
- human/agent comments
- archival history

Runtime ephemeral state includes:

- current claims
- heartbeat / lease info
- worker host
- worker PID
- process liveness checks
- temporary execution metadata
- in-flight planning/execution ownership

Runtime ephemeral state must not need to be committed to Git.

Canonical state must be committable to Git at chosen checkpoints.

### 3. Multi-Process / Multi-Machine Operation

The system must support:

- many concurrent readers
- one effective writer at a time per logical mutation path
- multiple processes on one host
- multiple hosts on a shared project/workspace

The system must support safe concurrent reads while writes occur.

The system must not assume one single long-running coordinator process.

The system must support degraded operation when a claimant process dies unexpectedly.

The system must allow a different process or host to verify whether a claim is still valid.

### 4. Claims / Leases

The system must support task claims.

A claim must minimally include:

- `task_id`
- `claim_id`
- `host_id` or machine identity
- `pid`
- `process_start_time` or equivalent anti-PID-reuse marker
- `claimed_at`
- `lease_until` or heartbeat expiry
- optional `worker_id`
- optional `run_id`
- optional `purpose` (`plan`, `execute`, `review`, etc.)

The system must allow a reader to answer:

- who currently claims this task?
- from which machine?
- with which PID?
- when was the claim made?
- when does it expire?
- is the claiming process likely still alive?
- has the claim gone stale?

The system should support both:

- explicit release
- implicit expiration by stale lease

The system should allow an external liveness checker to say:

- process alive on same host: yes/no
- remote host reachable: yes/no/unknown

The database itself need not perform OS liveness checks, but it must store enough data for a checker to do so.

### 5. Sparse / Dynamic Schema

The system must support sparse records and evolving fields.

It must be possible for different tasks to carry different metadata without forcing rigid table migrations.

Examples:

- research task may have `rigor_target`
- bounty task may have `program`, `case_path`
- coding task may have `repo`, `branch_policy`
- PM task may have `epic`, `sprint`, `owner`

The system should support:

- stable core fields
- extensible metadata bags / documents
- optional typed projections for common fields

The system should not require schema rewrites for every new task subtype.

### 6. Git Persistence

Canonical state must be persistable into Git in a human-reviewable form.

Requirements for Git persistence:

- stable serialization
- deterministic field ordering
- diff-friendly
- merge-tolerant
- plain text
- easy to regenerate higher-level views from it

The persistence format should support append-friendly history and snapshot-friendly current state.

Likely canonical format:

- `JSONL` for task snapshots and/or events

Why it fits:

- one object per line
- sparse fields natural
- good diffs
- good machine ingestion
- good DuckDB support

Runtime claims should be excluded from Git by default.

### 7. Queryability

The system must be queryable from:

- CLI
- script library
- simple local tooling
- downstream schedulers
- LLM orchestration code

The query interface must support:

- current task lookup by ID
- filter by status / priority / tags / repo / task type
- dependency traversal
- ready-to-run task selection
- blocked-task detection
- stale-claim detection
- claim ownership inspection
- history inspection
- metadata filtering and ad hoc inspection

The query layer should support ad hoc analytics over text-backed state.

### 8. Mutation Interface

The system must provide a controlled mutation API for:

- create task
- update task
- transition status
- add note/comment
- add/remove dependency
- archive / supersede / split / merge tasks
- claim / heartbeat / release claim
- record task-type inference or override
- compact or snapshot canonical state

Mutations should be available from both:

- CLI
- script library

Mutations must be atomic at the logical operation level.

### 9. Task Type Semantics

Task type must support multiple sources.

The system must support at least:

- `task_type_declared`
  - canonical type stored on the task
- `task_type_inferred`
  - derived by downstream code or rules
- `task_type_proposed`
  - suggested by an LLM or planner output
- `task_type_effective`
  - the type a downstream orchestrator actually uses

The database must not force only one task type truth source.

The database must allow downstream components to:

- trust canonical type
- override it
- propose a different type
- record why

### 10. Workflow Neutrality

The database must remain workflow-neutral.

It must not assume:

- Ralph
- Scrum
- Jira-like fields only
- coding-only lifecycle
- bounty-only lifecycle
- mandatory commits
- mandatory merge requests
- one repo per task
- one machine per task

Downstream systems may interpret the same database differently.

Examples:

- one repo may require merge request for `task_type=feature`
- another may allow direct commit for `task_type=research`
- another may forbid commits entirely for `task_type=analysis`

The database stores facts and structured state, not repo-specific policy.

### 11. History / Auditability

The system must preserve meaningful history.

It should be possible to answer:

- when was this task created?
- who/what changed it?
- how did status evolve?
- when was a dependency added?
- when did a task get split/merged/superseded?
- when did task type change?
- what did the planner infer last cycle?

History should be durable for canonical state.

Runtime claim history may be kept briefly or discarded depending on operational needs.

### 12. Human Operability

Humans must be able to:

- open canonical files directly
- review diffs
- understand current state
- inspect one task without special infrastructure
- repair malformed state if needed
- regenerate reports/views

The system should support generated human views like:

- `tasks.md`
- dashboard summaries
- per-repo reports

Those should be views, not the only source of truth.

### 13. Failure Recovery

The system must tolerate:

- crashed workers
- stale claims
- interrupted writes
- multiple hosts trying to inspect same task
- missing runtime state after reboot

Canonical state must remain consistent after crashes.

Runtime claims may be lost, but stale claims must be recoverable by expiry or liveness verification.

### 14. Portability

The system should work:

- locally on one machine
- on multiple machines sharing a repo
- with no mandatory central SaaS
- from shell scripts and Python libraries at minimum

If multiple-machine correctness depends on filesystem semantics, that must be explicit.

### 15. Minimal Policy Assumptions

The database should not decide:

- whether to commit
- whether to open MR/PR
- which model to use
- whether a task is `research` or `execute` for all consumers
- whether finalize reorganizes tasks
- whether orient exists

It should only expose enough state for downstream orchestrators to decide those things.

## Data Model Requirements

### Core task record must support

- `task_id`
- `title`
- `status`
- `priority`
- `created_at`
- `updated_at`
- `repo` or scope
- `summary`
- `body_md`
- `tags`
- `depends_on`
- `blocks`
- `task_type_declared`
- `metadata`
- `provenance`
- `supersedes` / `superseded_by`
- `parent_task_id` / `child_task_ids`
- `archived`
- `evidence`
- `decision_log` or references to events

### Canonical event/history record should support

- `event_id`
- `task_id`
- `event_type`
- `timestamp`
- `actor_type` (`human`, `agent`, `scheduler`, `policy_engine`)
- `actor_id`
- `host_id` optional
- `run_id` optional
- `payload`

### Runtime claim record should support

- `claim_id`
- `task_id`
- `host_id`
- `pid`
- `process_start_time`
- `worker_id`
- `run_id`
- `claimed_at`
- `lease_until`
- `last_heartbeat_at`
- `released_at`
- `release_reason`
- `liveness_status` optional cached field
- `metadata`

## Storage Requirements

### Canonical persistence

- plain text
- Git-friendly
- deterministic
- sparse-compatible

Preferred:

- `tasks.jsonl`
- `task_events.jsonl`

Optional:

- generated `tasks.md`
- generated indexes
- generated query cache

### Runtime persistence

- not committed to Git
- may be local file, socket-backed store, SQLite, or service-backed
- must support fast lookup of active claims
- must support expiry/liveness inspection

## Interface Requirements

### CLI must support

- `list`
- `show TASK_ID`
- `create`
- `update`
- `transition`
- `claim`
- `heartbeat`
- `release`
- `ready`
- `blocked`
- `stale-claims`
- `infer-type`
- `set-effective-type`
- `split`
- `merge`
- `archive`
- `render-md`
- `snapshot` / `compact`

### Library must support

- read current state
- read history
- claim lifecycle
- liveness hooks
- task selection hooks
- effective-type resolution hooks
- transactional mutation helpers

## Non-Functional Requirements

- deterministic serialization
- low operational complexity
- no mandatory always-on cloud service
- safe under concurrent read-heavy usage
- low-frequency write optimized
- inspectable with ordinary tools
- extensible without constant migrations
- robust enough for agent orchestration

## Architecture Constraints Implied By These Requirements

These requirements strongly imply a hybrid design, not one storage mechanism for everything.

Best fit so far:

- canonical layer:
  - Git-tracked `JSONL`
- runtime layer:
  - non-Git claims store
- query layer:
  - CLI/library over both
- optional analytical/read view:
  - DuckDB over canonical JSONL plus runtime source

Reasons:

- Git persistence and sparse evolving fields point toward `JSONL`
- live claims across machines/processes point away from Git-only runtime coordination
- many-reader query convenience points toward a query layer like DuckDB or equivalent
- workflow neutrality argues for core storage plus downstream policy engines

## Open Design Questions

These requirements still leave several architecture choices open:

1. Runtime claims store
   - local files with locks
   - SQLite
   - small central daemon
   - Postgres
   - per-host registry plus federation

2. Multi-machine guarantee model
   - shared filesystem trusted
   - central runtime claims service
   - per-host claims plus federation

3. Claim liveness verification
   - direct OS check on same host
   - SSH/agent probe for remote host
   - lease-only with optional liveness hints

4. Canonical representation style
   - snapshot-only `tasks.jsonl`
   - snapshot + `task_events.jsonl`
   - event-only with generated snapshot

## Short Summary

This is not just “a better `tasks.md`”.

It is a design for:

- a canonical Git-backed task database
- plus a live runtime coordination layer
- plus a neutral interface for many downstream agent workflows

Most important requirements:

1. one canonical source of truth
2. strict separation of canonical and runtime state
3. sparse/evolving metadata
4. claims with `host + pid + timestamp + lease`
5. multi-process and multi-machine readability
6. Git-friendly persistent canonical state
7. CLI/library access
8. task type support from both stored data and LLM/code inference
9. workflow neutrality

## Next Step

Next expansion pass should do a deep external research sweep on prior art:

- systems that tried Git-backed issue/task databases
- event-sourced PM/task systems
- lease/claim systems for distributed work queues
- local-first / text-first issue trackers
- sparse-schema task DB designs
- uncovered operational gaps in prior approaches

Recommended next move: run a 5-subagent web research pass and compare this requirements set against existing systems and their failure modes.
