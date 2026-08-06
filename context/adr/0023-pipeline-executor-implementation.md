# ADR-0023: M1.9 Pipeline registry and executor

- Status: accepted
- Date: 2026-08-04
- Scope: `kernel/pipeline`
- Supersedes: none (implementation of ADR-0006)

## Context

The kernel needs one explicit extension mechanism for module read aggregation
and write orchestration. Pipeline keys must be registered during wiring, steps
must run in deterministic attachment order, and write operations must share one
Unit of Work. A failed post-commit step must not turn a successful business
write into a failed response.

## Decision

1. `PipelineRegistry` stores `PipelineDef` values keyed by `PipelineKey`. It
   rejects duplicate or unknown keys and validates that every step is an async
   callable accepting exactly one `StepContext` argument. `validate_all()` is
   the startup fail-fast hook.
2. `StepContext` contains a `Principal`, Pydantic `payload`, `RequestMeta`, and
   an `ExtensionBag` that rejects non-Pydantic values. The executor installs the
   active UoW on the context only for write steps and excludes it from DTO
   serialization.
3. Read pipelines run `before → core → after` without opening a write UoW.
   Write pipelines run the same phases inside `async with uow`, commit exactly
   once after core succeeds, and only then execute after steps.
4. Before/core failures propagate and cause the UoW to roll back. Non-business
   core exceptions are wrapped as `PIPELINE_003`; existing `AppError` values
   retain their registered business code. After-step exceptions are logged and
   isolated because the primary transaction is already committed.
5. Wiring may declare a step as write-only (`pipeline_kind`, `kind`, or
   `writes=True`); attaching such a step to a read pipeline fails validation.

## Consequences

- Module code can define pipelines without importing other modules; api wiring
  remains the only composition root.
- Attachment order is the execution order, so no hidden numeric priority or
  auto-discovery mechanism is introduced.
- The executor is usable with an injected UoW factory in production and an
  isolated registry/UoW double in tests.

