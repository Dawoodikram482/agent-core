# 3. agent-core is a library, not a service

- **Status:** Accepted
- **Date:** 2026-10-12

## Context

agent-core was created from python-service-template, which is shaped for HTTP services:
a FastAPI app, an entry point, a Dockerfile, and the `api`, `services`, `domain` and
`adapters` layers. agent-core is never deployed on its own. Other repos install it as a
package and import from it.

## Decision

agent-core is a plain Python library:

- No `api/` package, entry point, Dockerfile or Docker CI job.
- One module or subpackage per capability (`settings`, `observability`, and later the
  LLM gateway and the agent contract) instead of the four service layers.
- Released as Git tags (`vX.Y.Z`) that services pin, e.g.
  `agent-core @ git+https://github.com/<owner>/agent-core@v0.1.0`.

## Consequences

- Services keep the layered structure; the library stays small and flat.
- Every change that services depend on needs a new tag and a version bump.
