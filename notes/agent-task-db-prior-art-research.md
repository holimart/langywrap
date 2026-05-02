# Agent Task Database Prior Art Research

Date: 2026-04-28

## Purpose

This note expands `notes/agent-task-db-requirements.md` with external prior art research.

Goal of the research:

- find systems adjacent to a Git-backed, agent-native task database
- understand what they solve well
- identify what they do not solve
- surface operational gaps and failure modes
- extract design lessons for a local-first, Git-persisted canonical task DB with runtime claims

Research was split across five tracks:

1. Git-backed and text-first issue/task systems
2. Lease/claim protocols for distributed workers
3. Workflow/orchestration systems
4. Sparse-schema and local-first data models
5. Agent/multi-agent PM prior art

## Executive Summary

The niche remains open.

There is strong prior art for:

- Git-native distributed issue history
- plaintext task authoring
- distributed lease/heartbeat patterns
- durable workflow execution
- multi-agent runtime orchestration

There is weak prior art for the exact target here:

- canonical task state persisted into Git in a human-reviewable way
- runtime claims kept outside Git
- task types allowed to come from stored data or downstream LLM/code inference
- multi-machine, multi-process-safe claiming and stale recovery
- developer-native PM semantics for autonomous agents working in repositories

Best current conclusion:

- canonical durable state should be text-first and append-only
- runtime coordination should be separate, ephemeral, and lease-based
- the system should borrow queue/lease semantics from workflow systems, but not try to make Git itself the hot runtime queue

## Track 1: Git-Backed And Text-First Task Systems

### Main systems looked at

- `git-bug`
- Fossil tickets
- `org-mode`
- TaskPaper
- `taskell`
- `todo.txt`
- TicGit / `git-meta` style metadata stores

### What these systems prove

#### `git-bug`

- Very strong proof that issue/task history can live canonically in Git.
- Uses operation history and deterministic merge logic rather than plain file overwrite.
- Strong distributed/offline story.

Main lesson:

- operation/event-style storage is much better than whole-record overwrite for distributed issue history.

Gap:

- no first-class ephemeral lease/claim layer for agents.

#### Fossil tickets

- Strong proof that code, tickets, wiki, and discussion can share one repo transport and artifact history.
- Tickets are durable repository artifacts, not working-tree files.

Main lesson:

- task/ticket state belongs in durable repo-native history, not mixed directly into source tree files.

Gap:

- no explicit runtime claim model
- some semantics rely on timestamps
- ticket schema/display config can be local rather than globally canonical

#### `org-mode`, TaskPaper, `taskell`, `todo.txt`

- Strong proof that text-first task management is highly usable for humans.
- Great inspectability, portability, grepability, and Git friendliness.

Main lesson:

- human-readable plain text matters a lot and should not be lost.

Gap:

- concurrency semantics are weak
- task structure is often too loose for autonomous scheduling
- no real claim/lease semantics

#### TicGit / `git-meta`

- Good middle ground between plain files and opaque object graphs.
- Stronger structure than Markdown, better queryability than purely ad hoc files.

Main lesson:

- there is value in separating canonical Git metadata from local query/index caches.

Gap:

- no real agent coordination or ephemeral claim layer

### Synthesis From Track 1

The field splits into two camps:

- human-first text systems with weak concurrency semantics
- distributed Git/object systems with stronger history but weaker manual inspectability

The missing combination is:

- Git-canonical
- mergeable/deterministic
- human-inspectable
- agent-safe for parallel runtime work

## Track 2: Lease / Claim Patterns For Distributed Workers

### Main systems/patterns looked at

- SQS visibility timeout
- Postgres queue patterns with `FOR UPDATE SKIP LOCKED`
- Postgres advisory locks
- SQLite locking and file locking caveats
- ZooKeeper lock recipes
- etcd leases and locks
- Consul sessions and lock index/session patterns
- Redis/Redlock critiques
- Chubby-style coarse lock services

### Core conclusion

Lease alone is not enough.

Minimal safe runtime claim protocol needs both:

1. expiring lease with heartbeat
2. monotonic fencing token checked on meaningful writes

Without fencing, a paused or partitioned worker can resume after lease expiry and still write stale results.

### Important lessons

#### Visibility timeout style

- Good model for reclaimability.
- Expiry means someone else may retry, not that the old worker is impossible.

#### Heartbeats

- Must re-check current ownership before extending.
- Should extend from authoritative store time, not stale local time.

#### Fencing tokens

- Essential for correctness once multiple machines/processes can reclaim work.
- Monotonic `claim_epoch` or equivalent should be carried with completion or any state-changing write.

#### Host + PID

- useful as an observability hint
- not a correctness boundary
- PID reuse, namespaces, and reboots make it insufficient alone

#### Advisory / file locks

- workable locally
- dangerous as a cross-machine correctness basis, especially on NFS/SMB

### Common failure modes simple systems miss

- worker pauses longer than TTL, then writes stale result
- network delay delivers stale completion after reclaim
- clock jumps distort lease semantics
- heartbeat races with reclaim without CAS checks
- PID reuse makes liveness checks lie
- file locks behave differently on shared/network filesystems
- stale worker mutates external systems after losing claim

### Synthesis From Track 2

For runtime claims, the system should assume:

- at-least-once execution
- stale workers can come back
- claims need explicit compare-and-set semantics

Recommended minimal runtime claim protocol:

- `claim_id`
- `claim_epoch` fencing token
- `lease_until`
- `last_heartbeat_at`
- `host_id`, `pid`, `process_start_time`, maybe `boot_id`
- heartbeat extension only if claim still matches
- completion accepted only if claim still matches current state

## Track 3: Workflow / Orchestration Systems

### Main systems looked at

- Temporal
- Airflow
- Prefect
- Dagster
- Celery
- RQ
- Luigi
- Argo Workflows

### What these systems solve well

#### Temporal

- strongest durable execution model
- append-only event history
- retries, queueing, ownership, heartbeats
- excellent concepts for agent loops

Main lesson:

- durable execution should be modeled as history of events, not just current mutable state.

#### Airflow / Prefect / Dagster

- rich run states
- scheduling and pooling
- late/zombie/stuck worker concepts
- concurrency controls

Main lesson:

- task state should be richer than just `pending / running / done`.

#### Celery / RQ

- practical queue routing and retry semantics

Main lesson:

- queues should be separated by capability or workload class
- idempotency and retry discipline matter

#### Luigi

- output/target-based completion

Main lesson:

- for some tasks, completion should be validated by artifacts or effects, not only status text.

### Why these do not directly solve the target problem

They all assume a hot runtime store or queue:

- DB
- broker
- Redis
- Kubernetes API

Git is not a good hot runtime store for:

- frequent heartbeats
- ownership renewals
- queue claim/requeue cycles
- tiny runtime events

### Synthesis From Track 3

Borrow their concepts, not their storage assumptions.

Best concepts to borrow:

- append-only event histories
- lease ownership with heartbeat expiry
- richer state machine
- retry policies
- queue separation
- idempotency keys
- pause/suspend states
- stale/lost worker handling

But do not try to make Git itself behave like Temporal or a message broker.

## Track 4: Sparse-Schema And Local-First Data Models

### Main patterns looked at

- JSONL append-only event logs
- document snapshots
- CQRS / event sourcing
- Datomic-style immutable facts
- CRDT/local-first systems
- SQLite with JSON columns / generated columns
- DuckDB over files
- CouchDB-like document storage

### Core conclusion

Best fit is a hybrid:

1. Git-persisted canonical append-only JSONL event log
2. deterministic materialized task snapshots in text
3. non-Git runtime state in SQLite
4. DuckDB for read-side analytics over files if needed

### Why JSONL scores well for canonical state

- line-oriented
- sparse fields natural
- human inspectable
- Git-friendly
- easy to process incrementally
- good fit for audit/event logs

### Why SQLite scores well for runtime state

- excellent local mutable coordination store
- easy indexes and queries
- JSON columns for flexible metadata
- generated columns for projecting common fields

But:

- binary file is poor as Git-canonical source

### Why DuckDB scores well for read-side

- query files directly
- schema-on-read over evolving JSONL
- excellent for reporting, analytics, and forensics

But:

- not the ideal transaction/claim path

### Why CRDT/local-first is not the first fit here

- optimized for true multi-writer mergeable editing
- usually less Git-review-friendly as canonical persistence
- adds complexity not obviously needed unless offline concurrent editing is a first-class requirement

### Synthesis From Track 4

Most promising architectural stack so far:

- canonical: append-only JSONL events in Git
- derived durable view: deterministic task snapshots in text
- runtime: SQLite or similar mutable store for claims/indexes
- optional analytics: DuckDB over events/snapshots

## Track 5: Agent / Multi-Agent PM Prior Art

### Main systems looked at

- LangGraph
- CrewAI
- AutoGen
- OpenHands
- AutoGPT Platform
- Devin public materials
- MetaGPT
- ChatDev
- CAMEL

### Core conclusion

Prior art is strong on agent runtime state, weak on project/task database semantics.

Most systems have:

- workflow state
- conversation state
- checkpoint state
- team/agent state

Most do not have a true task DB with:

- stable task identity
- explicit dependency graph
- lease/ownership model
- branch/worktree binding
- PR/test/review artifact linkage
- conflict prevention across many agents in one repo

### Important lessons

#### LangGraph

- very strong checkpoint/thread/store model

Main lesson:

- checkpointable execution state is valuable and should be attached to task attempts.

Gap:

- no backlog/task DB as such

#### CrewAI / AutoGen

- useful workflow and messaging patterns
- persistence exists, but mostly at flow/session/team level

Main lesson:

- execution state and messaging state should be modeled separately from task records.

Gap:

- PM/control-plane semantics still thin

#### OpenHands

- closest to practical developer workflow integration
- branch/PR-based execution patterns

Main lesson:

- branch-per-task and isolated execution surfaces are important.

Gap:

- conflict prevention largely achieved by serializing work or externalizing PM to GitHub/Jira/TODO systems

#### Devin public UX

- suggests async agent work through PRs/comments

Main lesson:

- human review and artifact linkage matter

Gap:

- public materials do not expose a general reusable task DB model

### Synthesis From Track 5

The market gap is not just “another coding agent”.

The gap is:

- durable multi-agent engineering control plane
- Git-native artifacts
- backlog/tasks as first-class durable objects
- safe parallel coordination
- human approval points

## Cross-Track Synthesis

### Strongest reusable ideas from prior art

- Git-backed durable issue history from `git-bug` / Fossil-like systems
- line-oriented inspectability from text-first trackers
- leases, heartbeats, stale recovery, and fencing from distributed lock/job systems
- append-only event histories and replay mindset from Temporal
- richer lifecycle states from orchestration systems
- execution checkpointing from LangGraph-like runtimes
- branch/PR-per-task execution patterns from practical coding-agent systems

### Biggest gaps still uncovered by prior art

1. **Git-canonical + agent-safe runtime split**
   - not well served directly

2. **First-class ephemeral claims for developer tasks**
   - most issue/task systems do durable assignment, not runtime leasing

3. **Task type from multiple sources**
   - stored type, inferred type, LLM-proposed type, effective downstream type
   - very little prior art makes this explicit

4. **One source of truth with workflow neutrality**
   - existing systems tend to assume one workflow model

5. **Conflict-safe many-agent repository PM**
   - most systems serialize work socially or externally instead of modeling conflict directly

6. **Human-readable canonical state plus rich machine semantics**
   - the field usually picks one side harder than the other

## Current Recommended Direction

### Canonical durable layer

Use append-only text-first event storage in Git.

Most likely shape:

- `events/**/*.jsonl`
- optionally deterministic materialized `tasks/<task_id>.json`
- optionally generated `tasks.md` reports/views

Why:

- sparse and evolving metadata
- durable audit trail
- Git reviewable
- can preserve multiple task-type sources and policy-neutral facts

### Runtime coordination layer

Keep claims outside Git.

Most likely shape:

- SQLite or similarly simple mutable local/service-backed runtime store
- lease + heartbeat + fencing token
- host/PID/process-start metadata for observability and liveness hints

Why:

- runtime claims are too hot/noisy for Git
- need compare-and-set correctness semantics
- need stale recovery without repository churn

### Query / read layer

- CLI and script library as primary interface
- optional DuckDB over canonical files for reporting, audit, and analytics

### Policy layer

Keep downstream.

Examples of downstream policy decisions:

- which task type is effective for this run
- whether commits are allowed
- whether MR/PR is required
- whether task can be directly executed or needs human approval
- which model/tooling lane to use

The database should store facts and state, not hardcode these policies.

## Open Questions For Next Design Pass

1. Canonical event model
   - snapshot-only
   - event-only
   - event log + materialized snapshot

2. Runtime claims implementation
   - local SQLite
   - one small networked service
   - hybrid local cache + shared service

3. Multi-machine operational assumptions
   - trusted shared filesystem
   - each machine has local runtime store but shared canonical Git state
   - explicit central coordinator for claims

4. Liveness protocol
   - lease only
   - lease + same-host PID validation
   - lease + optional remote probe

5. Snapshot generation model
   - generated on every canonical write
   - generated lazily
   - generated by maintenance/compaction command

## Bottom Line

No existing system appears to already cover the full target.

The best design path remains:

- Git-persisted canonical event/state layer
- non-Git runtime claim/lease layer
- workflow-neutral schema
- support for declared, inferred, proposed, and effective task type
- human-readable durable state
- machine-safe runtime coordination

This remains a real product and architecture gap.
