# ADR-0024: M1.10 task shell implementation

- Status: accepted
- Date: 2026-08-04
- Scope: `kernel/tasks`
- Related: ADR-0005, ADR-0011

## Context

Tasks need durable instance state without turning APScheduler's in-memory job
store into a second source of truth. They also need deterministic hook order,
idempotent starts, orphan recovery, and a narrowly scoped PostgreSQL wakeup
mechanism for long-running work.

## Decision

1. `task_instances` is the source of truth for state, payload, result, error,
   timeout and idempotency. APScheduler only schedules in-process execution;
   task classes and Cron definitions are explicitly registered at startup.
2. `BaseTask.execute()` owns the template order: `run` with `wait_for`, then
   `on_success`; failures call `rollback` once and then `on_failure`. Timeout or
   cancellation becomes `cancelled`; rollback failures are recorded on
   `TaskError.rollback_error` without hiding the primary failure.
3. `TaskScheduler.start_task()` validates the registered payload, creates a
   pending row through `TaskUnitOfWork`, and schedules one in-process runner.
   An active matching idempotency key returns the existing UUID; terminal rows
   may be retried with the same key.
4. Cron uses APScheduler 3.x `AsyncIOScheduler` with `MemoryJobStore`. Duplicate
   names are idempotently ignored, and each invocation receives
   `Principal.system_bot()`.
5. The only PostgreSQL notification channel is `aiya_task_wakeup`. Notifications
   wake in-memory waiters by UUID; `wait_wakeup()` re-reads `task_instances`
   before returning, so NOTIFY is a hint rather than data or an event bus.
6. Startup orphan reaping marks expired `running` rows as failed with reason
   `orphan`. It is safe to run repeatedly.

## Consequences

- Restarting the process loses only APScheduler job objects; code registration
  rebuilds Cron definitions and durable task rows remain inspectable.
- The shell is single-instance in this milestone; leader election and reliable
  wakeup replay remain the documented escape hatches.
- Task JSONB values are validated through `JsonBModel` base Pydantic models and
  rehydrated through the registered task class DTOs at the public boundary.

