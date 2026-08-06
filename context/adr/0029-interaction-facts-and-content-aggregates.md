# ADR-0029: Interaction facts and content aggregate counters

Status: accepted for 0.1.0

## Decision

User likes and ratings are facts in an `interactions` relation owned by the interaction component. The relation has `user_id`, polymorphic target identity, kind, optional numeric value, timestamps, and a uniqueness constraint per user/target/kind. The user table and content JSONB are not behavior stores.

The content row stores only rebuildable aggregates: `view_count`, `like_count`, `rating_sum`, and `rating_count`. The former administrator-editable `rating` field is removed. User average rating is derived from sum/count.

Interaction writes publish a registered event. The API wiring connects the event to content aggregate maintenance, and a reconciliation task can repair eventual-consistency drift. Cross-module synchronous table writes are forbidden.

## Consequences

- `GET /api/v1/me/interactions` can page the current user's history without exposing other users.
- Aggregates may be briefly eventually consistent; command responses return the actor's new state.
- The rating scale must be fixed in the interaction specification before the migration (recommended: integer 1–5).
