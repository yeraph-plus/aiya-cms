# ADR-0022: M1.8 Auth service implementation

- Status: accepted
- Date: 2026-08-04
- Scope: `kernel/auth`

## Context

The authentication specification requires password-only registration and login,
opaque refresh tokens, refresh rotation/replay protection, login rate limiting,
and explicit `user.*` events. The service must preserve the kernel transaction
boundaries: services do not receive a SQLAlchemy session and post-commit work
must not run inside the business transaction.

## Decision

1. Registration writes the `User`, password `Identity`, and default `reader`
   role assignment in one Unit of Work. The service flushes in dependency order
   to obtain the UUID foreign keys, then commits through `UoWExecutor`.
2. Access tokens are signed JWTs. Refresh tokens are opaque random values; only
   a SHA-256 digest is persisted in `refresh_tokens`. Refresh rotates the token
   atomically by revoking the old row before creating the replacement. A replay
   or revoked token returns `AUTH_003`.
3. Failed login attempts are counted by the cache using an `auth:login` key
   composed from normalized identifier and IP. Five failures within five
   minutes return `AUTH_007`; unknown identifiers and bad passwords share
   `AUTH_001` to prevent account enumeration.
4. `user.registered`, `user.login_succeeded`, `user.login_failed`, and
   `user.password_changed` are explicitly registered on the EventBus. Auth
   publishes them only after the relevant write operation commits.
5. Login, refresh, and principal resolution re-check the current user status.
   Therefore a banned/deleted user cannot mint or rotate tokens even if an old
   refresh row has not yet been physically purged. `revoke_all_for_user` is
   exposed for identity/event integration and administrative revocation.

## Consequences

- The auth service remains independent of the API composition root; HTTP routes
  and cookie policy are implemented in M1.12 using the frozen auth DTOs.
- Refresh-token rows are append-only for issuance and explicitly revoked for
  rotation/logout, enabling replay detection and audit consumers.
- Cache availability affects only throttling; credential validation remains
  deterministic and database-backed.

