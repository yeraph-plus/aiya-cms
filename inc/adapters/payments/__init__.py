"""Payment provider adapters.

Each implementation owns its SDK, credentials, timeout, webhook verification
and provider-error normalization. The manifest chooses exactly one provider
for the payments Port; ``cms_dev`` is the only profile that uses the fake
provider.
"""
