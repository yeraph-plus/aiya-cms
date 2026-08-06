# ADR-0028: SEO data layer and public SSR boundary

Status: accepted for 0.1.0 specification; runtime SEO rendering deferred

## Decision

The backend owns validated global SEO-related settings and future target-level SEO documents. The public frontend SSR layer owns route resolution and final HTML/XML rendering, including title, description, canonical URL, structured data, `sitemap.xml`, and `robots.txt`.

0.1.0 does not add Open Graph fields or implement the public SSR routes. The common site profile carries the indexing switch; the public settings projection carries only fields safe for the frontend.

Future content/taxonomy SEO values are stored by an SEO module in an explicit `seo_documents` relation keyed by `target_type` and `target_id`, with a Pydantic-bound JSONB model. The SEO module does not import content or taxonomy modules; target validation and read aggregation are wired by the API composition root.

## Consequences

- A client SPA cannot be treated as the SEO renderer for the public site.
- XML and HTML serialization are not duplicated in the backend API.
- Adding SEO fields later requires a new documented DTO and OpenAPI freeze.
