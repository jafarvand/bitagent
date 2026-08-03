# Project Plan Addendum — Chat-First Operating Model

This addendum extends the approved 16-week bitAgent project plan.

## Scope change

Chat is the primary management and operating interface. A user must not be required to navigate a form or menu to complete a supported workflow when the required information can be collected safely in conversation.

Dashboards, forms, and menus remain optional for discovery, visualization, administration, bulk operations, and audit review.

## Added objective

Enable authorized users to search, view, investigate, calculate, generate reports, approve, reject, pause, resume, cancel, and propose setting changes through governed multi-turn chat commands.

## Added workstream

### Conversational Command and Tool Orchestration

Deliverables:

- Natural-language intent and entity interpretation.
- Typed tool registry.
- Multi-turn slot collection and command state.
- Ambiguity resolution.
- Role, scope, policy, evidence, and risk checks.
- Action previews and explicit confirmations.
- Maker-checker and approval routing.
- Tool execution, post-state verification, rollback, and kill switch.
- Append-only command and execution audit.
- Chat-native result reporting.

## Added success criteria

- At least 90% of supported management workflows can be completed entirely through chat during pilot UAT.
- The orchestrator asks only for required missing information.
- Zero write executions occur with ambiguous targets, stale material evidence, missing authorization, or unmet approvals.
- Every material command includes an exact preview and verified outcome.
- Every command is correlated across chat, policy, approval, exchange API, verification, and audit records.

## Governance boundary

The chat model never receives unrestricted execution authority. It may select only versioned, allowlisted tools and produce typed arguments. Deterministic policy and exchange systems remain authoritative.

Direct wallet signing, balance mutation, unrestricted configuration, arbitrary SQL/shell commands, and autonomous fund movement remain out of scope.
