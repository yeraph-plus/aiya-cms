# ADR-0030: Unified list-query contract and search boundary

- Status: accepted
- Date: 2026-08-06
- Decision owner: project maintainers
- Related: `context/architecture/02-data-boundaries.md`, `context/adr/0009-jsonb-discipline.md`, `context/modules/content.md`, `context/modules/taxonomy.md`, `context/modules/comment.md`, `context/kernel/identity.md`

> ADR-0032 changes the ownership of content, taxonomy and comment base implementations to kernel; this ADR's query semantics and search boundary remain unchanged.

## Context

The first M2 implementation exposed list queries independently. Content already
supports pagination, status, taxonomy ids, keyword matching and SQL ordering,
while terms still returns an unpaged list and comments/users do not expose a
complete ordering contract. Taxonomy list operations also accept an unknown
`type_name` and return an empty result instead of reporting the invalid scope.

The application is still in the initial design phase, so this decision is a
breaking contract change. No legacy query fields, response shapes or methods
need to remain compatible.

The system also needs a future full-text search boundary. Meilisearch is an
external infrastructure dependency and is deliberately not implemented in
this change.

## Decision

### 1. Per-owner query DTOs, one semantic contract

Content, taxonomy, comments and identity each keep their own query DTO and
repository implementation. No business-specific shared query service is added
to the kernel or between modules.

Every paged list uses:

- `page` (default 1, minimum 1) and `size` (default 20, maximum 100).
- `q` as a case-insensitive literal contains query. `%`, `_` and `\\` are
  escaped before `ILIKE`; they are not user-controlled SQL wildcards.
- An explicit `sort` allow-list and `order=asc|desc`; arbitrary SQL column names
  are rejected by request validation.
- All independent filters combine with `AND`. Multiple fields searched by `q`
  combine with `OR`.
- Every result ordering appends the native `id` as a deterministic tie-breaker.
  Nullable sort columns use `NULLS LAST`.

JSONB fields, long body text as a sort key, and UUID foreign keys as public sort
keys are not exposed as generic query parameters. JSONB filtering continues to
follow ADR-0009.

### 2. Resource-specific query fields

- Content: `terms`, `status`, `owner_id`, date ranges, and SQL ordering over
  title/slug/status/published and the real counter/timestamp columns. The
  current SQL keyword query remains title + slug contains matching.
- Taxonomy: `group`, exact `slug`, date ranges, and keyword matching over name +
  slug. The response is `Page[TermRead]`, and `TermRead` includes timestamps.
- Comment moderation: existing status/target/author/date filters plus
  `q=content` and an explicit sort allow-list. The public target-scoped thread
  endpoint remains a thread reader rather than a global search endpoint.
- Users: existing status/role filters plus date ranges, keyword matching over
  username/email/display name, and explicit SQL ordering.

### 3. Taxonomy scope and content composition

Every `/terms/{type_name}` operation validates the registered content type
before reading or writing. An unknown type is a taxonomy 404 error; a known type
with an undeclared group remains a taxonomy 422 error. Validation crosses the
module boundary only through callbacks supplied by API wiring.

Content remains isolated by the URL `type_name`; a multi-type content query is
not designed. The `terms` expression is:

```text
terms=category:news,category:tech,tags:python
```

which means `(category=news OR category=tech) AND tags=python`, restricted to
the content type in the URL. Malformed expressions are validation errors;
unknown but syntactically valid slugs produce an empty result.

### 4. UUIDv7

All primary and relationship UUIDs remain PostgreSQL native `uuid` values.
UUIDv7 occupies the same 16 bytes as UUIDv4 and is suitable for equality
lookups, joins, B-tree indexes and stable pagination tie-breaking. The contract
does not convert UUIDs to text or expose UUID columns as arbitrary sort keys.
Composite indexes are added only for measured default/filter paths; every
allowed sort field does not automatically receive an index.

### 5. Future search module

Meilisearch is registered as a future `search` module decision only:

- The search module will own its configuration, client adapter, index mapping
  and rebuild operation.
- Meilisearch will be provided as an external, version-pinned container; the
  application will not embed or install the search engine.
- Content, taxonomy, comment and identity will not import the search module.
  API wiring may inject typed search/resolver callbacks when the feature is
  implemented.
- Search results will carry ordered ids/scores; owning SQL repositories will
  still apply type, visibility, permission, status and taxonomy constraints.
- Indexes are rebuildable. Event delivery, outage fallback, consistency and
  reindex commands require a later implementation specification.

This change keeps `q` as simple SQL filtering. It does not claim full-text
search or silently change result ranking.

## Alternatives

| Option | Advantages | Disadvantages | Decision |
|---|---|---|---|
| One generic query service in kernel | Less DTO repetition | Leaks business fields across module boundaries and weakens ownership | Rejected |
| Arbitrary field/filter names | Appears flexible | Unsafe SQL surface, unstable OpenAPI, poor indexability | Rejected |
| PostgreSQL full-text search now | No external service | Couples the first milestone to ranking/index lifecycle decisions | Rejected |
| External Meilisearch now | Better search quality | Adds infrastructure and consistency scope before the contract is stable | Deferred |

## Consequences

### Positive

- OpenAPI exposes predictable pagination, keyword, filtering and ordering shapes.
- Taxonomy cannot silently cross an invalid content type.
- Content + taxonomy semantics are testable without introducing multi-type joins.
- UUIDv7 remains efficient and does not create a text-storage overhead.
- A future search implementation has a clear module and composition-root boundary.

### Negative / cost

- Four owners maintain separate allow-lists and repository queries.
- `ILIKE '%q%'` is intentionally a simple early-stage query and may require a
  later search backend or targeted database indexes at scale.
- Changing terms from a list to `Page[TermRead]` requires OpenAPI and admin
  client regeneration.

### Escape hatch

If SQL keyword queries become a measured bottleneck, add the search module and
its ADR-backed index/rebuild contract. Do not broaden JSONB filtering or accept
raw SQL sort fields as an interim workaround.
