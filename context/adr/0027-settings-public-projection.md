# ADR-0027: Strongly typed runtime settings and public projections

Status: superseded by ADR-0031 for the settings definition and persistence model; public projection boundary remains applicable

## Context

The runtime settings registry currently validates Pydantic values but exposes a generic JSON dictionary over HTTP. `site.profile` also contains both public site data and private administrator data, so exposing the entire setting value would be unsafe.

## Decision

Keep the stable setting group `site.profile`, but define it through the declarative group/field interpreter in ADR-0031. Public visibility is still explicit and never authorizes serializing private values.

The administrator API uses typed group/field metadata and a group patch route. The public API exposes a stable `GET /api/v1/public/settings` composite DTO and never returns `admin_email`, `default_registration_role`, defaults, or validation internals.

The API composition root reads settings for registration and passes an `AuthRegistrationPolicy` DTO to auth. Kernel auth does not import settings.

## Consequences

- Settings JSONB requires no table migration; old field aliases are not retained because the project is still in the initial design phase.
- Every new registered group needs a declaration and interpreter coverage; the administrator API is metadata-driven.
- OpenAPI is regenerated after route changes and is the sole administrator client contract.
