# product_agent

The FACTORY stage between **Analysis and Architecture**. It turns the Analyst's *requirements* into a
**product/experience definition** so the delivered app is a coherent product for a real user — not an
index of the internal modules that were built.

## Why it exists

Without this stage the UI falls out of the technical decomposition: the Architect splits requirements
into services/entities, the Builder generates one page per service plus a link index, and the "homepage"
is a bullet list of module names with no user, no roles, and no journey. The product_agent fixes the
causality — `requirements → product → architecture → build` — by defining the experience first.

## What it produces

`product/product_spec.json` (+ a human-readable `product/product_brief.md`), committed via reqoach:

- **personas** — the distinct user roles (e.g. an owner/admin vs an end customer), with goals.
- **surfaces** — public vs authenticated areas, each for a set of personas.
- **screens** — the screen map, framed as USER TASKS, each mapped to requirement ids; one is the landing.
- **journeys** — the primary end-to-end user journeys.
- **navigation** — per-surface nav; **landing_screen** — the primary user's entry (usually public).

## Who consumes it

- The **Architect** — must design services/entities/auth to support these journeys and roles.
- The **Builder-frontend** — generates the homepage (the landing experience + navigation) and the pages
  from the SCREEN MAP, not from service names.

## Endpoints

- `POST /projects/{pid}/product:run` → `{job_id}`
- `GET /jobs/{job_id}` → status snapshot (`result` = the product manifest)
- `GET /health`

## Run

```bash
cd compose && docker compose up -d --build
```

Host-networked on `:7809`; reads `requirements/`, writes `product/`, reaches the model on `localhost:8500`.
Registered on the domain proxy at `/product/`. Generic — the only input is the requirements, so it
generalises to any app the FACTORY builds.
