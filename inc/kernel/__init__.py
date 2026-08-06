"""Technical runtime kernel.

Kernel packages own only mechanisms without business meaning (database,
durable events, workflow/tasks runtime, boot registries, observability,
errors, security primitives, time). Importing any kernel package must have
no side effects.
"""
