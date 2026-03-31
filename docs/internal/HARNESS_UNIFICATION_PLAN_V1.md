# Harness Unified Architecture Plan v1

## 1. Background

`apaas-builder-ai` currently has four major capability areas:

1. Intelligent Builder
   Self-developed conversational app building flow. The user mainly works in `ChatPage`, and the system generates and executes low-code configuration in phases.

2. Assisted Builder
   Currently a transitional solution based on `iframe` embedding of the low-code platform backend. It is useful, but it is not yet a real AI-operated platform runtime.

3. Intelligent Coding
   Self-developed agent initialization + workspace bootstrap, then handoff into `code-server / forked VS Code` for code inspection and conversational development.

4. Requirements Analysis
   Conversational requirements gathering module with its own page (`RequirementsPage`), session management, and design document generation. The user describes product needs in natural language, and the system produces structured requirements documents.

At the moment, the four areas each carry part of their own execution flow, event model, model routing, and state handling. This works short term, but it will gradually create:

- duplicated orchestration logic
- inconsistent event protocols
- difficulty sharing tooling and approvals
- fragmented observability
- high cost to evolve Assisted Builder away from `iframe`

The key conclusion is:

We should not build four separate harnesses.

We should build **one platform-level Harness Core**, then expose four runtime profiles on top of it:

- `builder_profile`
- `platform_profile`
- `coding_profile`
- `requirements_profile`


## 2. Current Product Structure

### 2.1 Intelligent Builder

Current characteristics:

- primary entry is `ChatPage`
- uses phased generation and SSE
- generates low-code config skeleton, dicts, models, steps
- executes changes against the aPaaS platform

Representative code:

- `backend/app/routes/chat.py`
- `backend/app/config_assembler.py`
- `backend/app/incremental_executor.py`

### 2.2 Assisted Builder

Current characteristics:

- entry is also in `ChatPage`
- currently relies on `iframe` to embed the platform backend
- mainly acts as a temporary operational bridge
- does not yet have an independent AI runtime layer

Representative code:

- `frontend/src/views/ChatPage.vue`
- platform-related APIs and env config routes

### 2.3 Intelligent Coding

Current characteristics:

- entry is `CodingPage`, currently embedded into `ChatPage` by `iframe`
- scaffolding uses df-apaas-cli pre-generated templates (replaced earlier Python hand-written scaffolding)
- agent model switched from MiniMax to Claude Sonnet 4.6 via jieko.ai
- frontend changed from loading overlay to real-time conversation stream (stream-pane)
- environment variables split: `ANTHROPIC_*` for LLMClient, `VIBE_AGENT_*` for Coding Agent
- supported project types refined: removed mobile/script types from UI, added list-view
- self-developed coding agent loop with tool calling
- integrates workspace, preview, debug, serve, and IDE URL generation

Representative code:

- `backend/app/routes/coding.py`
- `backend/app/coding/vibe_agent.py`
- `backend/app/coding/tools.py`
- `backend/app/coding/workspace.py`


## 3. Target Architecture

### 3.1 Core Idea

Build a unified Harness Core as the execution substrate for all four business modes.

Shared responsibilities of Harness Core:

- thread / turn / item lifecycle
- model routing and adapter abstraction
- model adapter unification (Anthropic native vs OpenAI-compatible formats)
- tool registration and execution
- policy and approval
- artifact management
- event streaming and replay
- observability and evaluation

Mode-specific responsibilities:

- Builder Mode: configuration planning and platform execution
- Platform Mode: platform reading, recommendation, guided operation, automated operation
- Coding Mode: workspace coding, tool calling, preview/debug/IDE handoff
- Requirements Mode: conversational requirements gathering, design document generation, session management

### 3.2 Architecture Diagram

```text
Frontend
  ChatPage / CodingPage / RequirementsPage / IDE
    ↓
Gateway API
  /harness/threads
  /harness/turns
  /harness/events
    ↓
Harness Core
  manager
  turn runner
  context builder
  event bus
  policy & approval
  artifact manager
    ↓
Profiles
  builder_profile
  platform_profile
  coding_profile
  requirements_profile
    ↓
Toolpacks
  builder tools
  platform tools
  coding tools
  requirements tools
    ↓
Adapters
  model adapters
  platform adapters
  workspace adapters
```


## 4. Business Mapping

### 4.1 Intelligent Builder -> Builder Mode

Builder Mode is the runtime profile for conversational low-code generation.

It should handle:

- requirement understanding
- config skeleton generation
- dictionary generation
- model generation
- change planning
- incremental execution
- validation and summary

The main output is not source code but structured low-code artifacts:

- config preview
- roles
- dictionaries
- models
- forms
- processes
- change plans
- execution results

### 4.2 Assisted Builder -> Platform Operator Mode

Platform Operator Mode is the future runtime profile for AI-assisted low-code operation.

Short term:

- retain `iframe` as transitional UI
- use it as observation and fallback

Mid term:

- introduce platform read tools
- let AI understand current platform state
- let AI answer "what exists now" and "what should change"

Long term:

- introduce platform write tools
- introduce browser automation for designer-only operations
- turn `iframe` into a supervision / takeover UI instead of the main engine

### 4.3 Intelligent Coding -> Coding Mode

Coding Mode is the runtime profile for source-code generation and iteration.

It should handle:

- workspace creation and binding
- file and shell tools
- code generation loop
- preview / serve / debug
- IDE handoff
- code artifacts and history replay

### 4.4 Requirements Analysis -> Requirements Mode

Requirements Mode is the runtime profile for conversational requirements gathering and design document generation.

It should handle:

- multi-turn conversational requirements elicitation
- structured requirements document generation
- session management and history persistence
- design artifact storage and versioning

Future integration:

- end-to-end flow from Requirements Mode into Builder Mode (requirements -> config generation)
- requirements traceability across generated artifacts


## 5. Repository Structure Proposal

Suggested new backend directory:

```text
backend/app/harness/
  contracts.py
  manager.py
  session_store.py
  events.py
  context.py
  policy.py
  approvals.py
  artifacts.py

  core/
    runtime.py
    turn_runner.py

  profiles/
    builder.py
    platform.py
    coding.py
    requirements.py

  models/
    base.py
    openai_chat.py
    openai_responses.py
    minimax.py

  tools/
    registry.py
    executor.py
    builder_tools.py
    platform_tools.py
    coding_tools.py
    requirements_tools.py
```

Suggested frontend additions:

```text
frontend/src/api/harness.ts
frontend/src/lib/harnessEventAdapter.ts
frontend/src/stores/harness.ts
```


## 6. File-Level Refactor Plan

### 6.1 New Files

#### `backend/app/harness/contracts.py`

Define core domain objects:

- `HarnessThread`
- `HarnessTurn`
- `HarnessItem`
- `HarnessArtifact`
- `HarnessApproval`
- `HarnessProfile`
- `HarnessMode`

#### `backend/app/harness/manager.py`

Responsibilities:

- create / load threads
- start turns
- manage background tasks
- provide event subscriptions
- support resume / replay

#### `backend/app/harness/session_store.py`

Responsibilities:

- persist thread / turn / item / approval / artifact
- bridge new harness tables with old `Conversation` and `Message`

#### `backend/app/harness/events.py`

Responsibilities:

- define unified internal event protocol
- normalize event envelopes
- provide adapters for SSE output

#### `backend/app/harness/context.py`

Responsibilities:

- collect conversation context
- inject workspace context
- inject platform context
- summarize old turns
- attach rules and references

#### `backend/app/harness/policy.py`

Responsibilities:

- tool permission checks
- publish restriction checks
- shell safety policies
- platform mutation gating

#### `backend/app/harness/approvals.py`

Responsibilities:

- create approval requests
- pause turn execution
- resume on approval
- deny and short-circuit execution

#### `backend/app/harness/artifacts.py`

Responsibilities:

- persist diffs
- persist screenshots
- persist build outputs
- persist preview links and logs

#### `backend/app/harness/profiles/builder.py`

Wrap current builder flow into a profile.

It should use existing capabilities from:

- `config_assembler`
- incremental update executor
- platform execution steps

#### `backend/app/harness/profiles/platform.py`

Initial responsibilities:

- platform read-only operations
- current state inspection
- action suggestion

Later responsibilities:

- platform write actions
- browser automation
- guided assisted operation

#### `backend/app/harness/profiles/coding.py`

Wrap current coding flow into a profile.

It should absorb the orchestration logic from `VibeCodingAgent` and `auto-pipeline`.

#### `backend/app/harness/models/*`

Provide a unified interface for all model providers.

Important:

- `openai_responses.py` should absorb current Codex `/responses` adaptation logic
- route handlers should no longer manually care about upstream protocol differences

#### `backend/app/harness/tools/*`

Provide:

- tool registry
- tool execution
- profile-level tool exposure
- policy checks before execution

### 6.2 Existing Files to Refactor

#### `backend/app/routes/coding.py`

Current status:

- route
- session
- pipeline orchestration
- intent handling
- SSE formatting
- model adaptation
- IDE URL generation

Target:

- remain as transport adapter
- call `HarnessManager` with `coding_profile`
- keep external API shape compatible in Phase 1

#### `backend/app/routes/chat.py`

Target:

- `generate-config` becomes transport adapter for `builder_profile`
- no direct phased generation orchestration in route layer

#### `backend/app/config_assembler.py`

Target:

- keep generation logic
- expose as builder tool / builder domain service
- remove direct dependency from route layer over time

#### `backend/app/incremental_executor.py`

Target:

- become reusable builder/platform execution service
- feed progress into unified event bus

#### `backend/app/coding/vibe_agent.py`

Target:

- migrate core loop into `coding_profile`
- keep file temporarily as legacy wrapper
- eventually shrink to compatibility shim or delete

#### `backend/app/coding/tools.py`

Target:

- split into tool registry + executor + policy
- move generic coding tools into `harness/tools/coding_tools.py`

#### `frontend/src/views/ChatPage.vue`

Target:

- keep the three-tab product structure
- consume unified harness events through `harnessEventAdapter`
- no longer parse multiple backend-specific event dialects inline

#### `frontend/src/views/CodingPage.vue`

Target:

- move event parsing into adapter
- keep UI interaction stable during migration

#### `frontend/src/api/coding.ts`

Target:

- keep compatibility API
- gradually call generic harness APIs underneath

#### `backend/app/routes/requirements.py`

Target:

- remain as transport adapter for `requirements_profile`
- call `HarnessManager` with `requirements_profile`
- keep external API shape compatible in Phase 1

#### `frontend/src/views/RequirementsPage.vue`

Target:

- consume unified harness events through `harnessEventAdapter`
- move session management into harness thread lifecycle
- keep UI interaction stable during migration

#### `frontend/src/api/conversation.ts`

Target:

- keep old conversation API
- later bridge thread metadata and conversation metadata when needed


## 7. Data Model Proposal

We should keep existing tables:

- `conversations`
- `messages`
- `applications`
- `projects`
- `change_plans`
- `document_versions`

Then add new harness tables.

### 7.1 `harness_threads`

Purpose:

- top-level durable session for all three modes

Suggested fields:

- `id`
- `tenant_id`
- `user_id`
- `conversation_id`
- `application_id`
- `project_id`
- `workspace_id`
- `mode` (`builder/platform/coding/requirements`)
- `profile`
- `title`
- `status`
- `metadata_json`
- `created_at`
- `updated_at`

### 7.2 `harness_turns`

Purpose:

- one unit of work initiated by user input

Suggested fields:

- `id`
- `thread_id`
- `input_text`
- `input_json`
- `model_name`
- `status`
- `started_at`
- `completed_at`
- `summary`

### 7.3 `harness_items`

Purpose:

- atomic units inside one turn

Examples:

- user message
- assistant delta
- tool call
- tool result
- approval request
- artifact reference

Suggested fields:

- `id`
- `turn_id`
- `seq`
- `kind`
- `status`
- `name`
- `payload_json`
- `started_at`
- `completed_at`

### 7.4 `harness_artifacts`

Purpose:

- store result objects worth showing, replaying, or auditing

Examples:

- config diff
- screenshots
- preview URL
- build package
- logs
- generated code diff

Suggested fields:

- `id`
- `thread_id`
- `turn_id`
- `item_id`
- `artifact_type`
- `title`
- `uri`
- `content_text`
- `metadata_json`
- `created_at`

### 7.5 `harness_approvals`

Purpose:

- persist high-risk action approvals

Suggested fields:

- `id`
- `thread_id`
- `turn_id`
- `item_id`
- `approval_type`
- `reason`
- `request_json`
- `decision`
- `decided_by`
- `decided_at`
- `created_at`


## 8. Internal Event Protocol

Internal event protocol should be standardized as:

- `thread.started`
- `turn.started`
- `item.started`
- `item.delta`
- `item.completed`
- `approval.requested`
- `approval.resolved`
- `turn.completed`
- `turn.failed`
- `thread.completed`

Examples of item kinds:

- `user_message`
- `assistant_message`
- `tool_call`
- `tool_result`
- `approval`
- `artifact`
- `summary`

This internal protocol should not be exposed raw to old UIs immediately.

Instead:

- backend provides compatibility event adaptation
- frontend also provides compatibility event adaptation

This allows phased migration without breaking `ChatPage` and `CodingPage`.


## 9. API Proposal

### 9.1 Core Harness API

#### `POST /harness/threads`

Create a new thread.

Input:

- `mode`
- `profile`
- `conversation_id?`
- `application_id?`
- `project_id?`
- `workspace_id?`
- `title?`

#### `GET /harness/threads/{thread_id}`

Return thread status and latest runtime state.

#### `POST /harness/threads/{thread_id}/turns`

Start a new turn.

Input:

- `input_text`
- `input_json?`
- `stream=true|false`

#### `GET /harness/threads/{thread_id}/events`

SSE or replay endpoint.

Optional:

- `after_seq`

#### `GET /harness/threads/{thread_id}/artifacts`

Fetch thread artifacts.

#### `POST /harness/approvals/{approval_id}/decide`

Input:

- `decision = allow | deny`
- `note?`

### 9.2 Compatibility APIs

#### Existing builder APIs

Keep them alive, but internally dispatch to `builder_profile`.

#### Existing coding APIs

Keep them alive, but internally dispatch to `coding_profile`.

#### New platform operator APIs

Add a dedicated entry for `platform_profile` over time.


## 10. Migration Strategy

### Phase 1: Build Harness Core

Goals:

- add `backend/app/harness/`
- introduce new DB tables
- define unified contracts and events
- keep all existing product entry points unchanged

Output:

- minimum viable Harness Core

### Phase 2: Migrate Intelligent Coding First

Reason:

- it is already the closest to a true harness runtime
- it already has workspace, tools, loop, SSE, and model routing

Tasks:

- wrap current coding flow into `coding_profile`
- route `auto-pipeline` through `HarnessManager`
- move Codex `/responses` logic into model adapter
- split coding tools from direct route usage

Output:

- Coding Mode running on Harness Core

### Phase 2.5: Model Adapter Unification

Reason:

- this is the most painful current issue
- different modules use different API formats (Anthropic native vs OpenAI-compatible)
- environment variable conflicts between `ANTHROPIC_*` and `VIBE_AGENT_*` cause silent failures
- must be resolved before migrating additional profiles

Tasks:

- build unified model adapter layer in `harness/models/`
- abstract away Anthropic native, OpenAI-compatible, and proxy (jieko.ai) differences
- centralize API key and endpoint routing
- eliminate env var conflicts across modules

Output:

- single model routing layer used by all profiles

### Phase 3: Migrate Intelligent Builder

Tasks:

- wrap phased config generation into `builder_profile`
- wrap incremental execution into builder toolchain
- unify progress events into harness event model

Output:

- Builder Mode running on Harness Core

### Phase 4: Introduce Platform Operator Mode

Tasks:

- add platform read tools
- let AI inspect existing app / forms / fields / processes
- keep iframe as fallback UI

Output:

- initial Assisted Builder harness integration

### Phase 4.5: Migrate Requirements Analysis

Tasks:

- wrap conversational requirements gathering into `requirements_profile`
- migrate session management into harness thread lifecycle
- connect document generation as requirements toolchain
- adapt `requirements.py` route to call Harness Core

Output:

- Requirements Mode running on Harness Core

### Phase 5: Add Platform Write and Approval

Tasks:

- platform mutation tools
- approval checkpoints
- browser automation for unsupported API operations

Output:

- real Platform Operator Mode begins replacing iframe-only workflow

### Phase 6: Frontend Protocol Unification

Tasks:

- add `harnessEventAdapter`
- reduce inline event branching in `ChatPage` and `CodingPage`
- allow all three tabs to share a runtime event model

Output:

- unified frontend runtime protocol


## 11. Suggested 12-Week Timeline

### Week 1-2

- create `backend/app/harness/` skeleton
- define contracts, manager, events, session store
- create DB migrations for harness tables

### Week 3

- build SSE event adapter and replay support
- add frontend `harness.ts` and `harnessEventAdapter.ts`
- keep old UIs unchanged

### Week 4-5

- migrate coding orchestration into `coding_profile`
- adapt `coding.py` to call Harness Core
- split coding tool runtime
- add policy for shell / publish / debug
- store coding artifacts

### Week 6

- build unified model adapter layer
- abstract away Anthropic native, OpenAI-compatible, and proxy differences
- centralize API key and endpoint routing
- eliminate env var conflicts across modules

### Week 7-8

- migrate builder phased generation into `builder_profile`
- hook builder events into unified event protocol
- migrate incremental execution and builder artifacts
- connect builder route compatibility layer

### Week 9

- migrate requirements gathering into `requirements_profile`
- adapt `requirements.py` route to call Harness Core
- connect document generation as requirements toolchain

### Week 10

- build `platform_profile` read-only capabilities
- support inspection of current low-code platform state

### Week 11

- add approvals and first platform write capabilities
- introduce browser automation for unsupported API operations

### Week 12

- frontend protocol unification via `harnessEventAdapter`
- finalize observability and replay
- produce acceptance review for the four modes


## 12. Acceptance Criteria

The migration is considered successful when:

- Intelligent Builder, Assisted Builder, Intelligent Coding, and Requirements Analysis all run on the same Harness Core
- all four modes share the same thread / turn / item lifecycle
- model routing is centralized
- approvals are supported for high-risk actions
- artifacts can be replayed and audited
- existing product entry points remain available
- Assisted Builder is no longer only an `iframe`, but already has platform tools under Harness Core


## 13. Key Risks

### Risk 1: Too much at once

Mitigation:

- do not rewrite all four areas together
- migrate Coding first, then model adapters, Builder third, Requirements fourth, Platform last

### Risk 2: Frontend churn

Mitigation:

- keep current pages and tabs
- migrate protocol underneath them first

### Risk 3: Assisted Builder remains stuck in transition

Mitigation:

- explicitly define Platform Operator Mode milestones
- treat `iframe` only as a temporary UI fallback

### Risk 4: Duplicate state during migration

Mitigation:

- keep `Conversation` and `Message` as compatibility entities
- introduce harness tables as runtime state source

### Risk 5: Model adapter fragmentation

Different modules currently use different API formats (Anthropic native vs OpenAI-compatible via jieko.ai proxy), causing environment variable conflicts (`ANTHROPIC_*` vs `VIBE_AGENT_*`) and silent failures when configuration is mismatched.

Mitigation:

- prioritize model adapter unification early (Phase 2.5)
- build a single model routing layer that abstracts provider differences
- centralize all API key and endpoint configuration
- add health-check validation on startup to catch misconfiguration


## 14. Final Recommendation

`apaas-builder-ai` should be positioned internally as:

**one unified Harness Core with four business runtime profiles**

rather than:

**four separate AI features patched together**

This gives the project a stable architecture for:

- future IDE evolution
- future multi-agent collaboration
- platform operator automation
- shared observability
- safer execution and approvals
- lower long-term maintenance cost

