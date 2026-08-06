# Module / interaction (0.1.0 slice)

## Scope

The initial slice supports authenticated content likes and user ratings, plus the current user's paginated history. Favorites, follows, reports, notifications, and comment reactions remain future work.

## Persistence

`interactions` stores one current relation per `(user_id, target_type, target_id, kind)`. It is relational data, not a JSONB array. The target is validated through an explicit composition-root resolver because modules cannot import one another.

## API shape

- `PUT/DELETE /api/v1/interactions/content/{content_id}/like`
- `PUT/DELETE /api/v1/interactions/content/{content_id}/rating`
- `GET /api/v1/me/interactions?kind=like|rating&page=...`

All write operations require an authenticated user. History is limited to the current user. Administrative cross-user access requires a separately registered capability.

## Events and aggregates

The interaction component publishes `interaction.changed` after commit. API wiring connects it to content aggregate maintenance. Content keeps `like_count`, `rating_sum`, and `rating_count`; interaction rows remain the source of truth and support reconciliation.

## Errors and tests

Tests cover duplicate idempotency, unlike/unrate, rating bounds, concurrent updates, target-not-found, private history, capability failures, event failure isolation, and aggregate reconciliation.
