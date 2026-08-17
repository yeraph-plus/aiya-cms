"""Payment provider adapters.

Each implementation owns its SDK, credentials, timeout, webhook verification
and provider-error normalization.  The composition root registers every
audited provider; Settings chooses the active provider at call time.
"""
