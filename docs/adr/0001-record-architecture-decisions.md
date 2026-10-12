# 1. Record architecture decisions

- **Status:** Accepted
- **Date:** 2026-10-12

## Context

Pit Wall is built across several repos over many sprints. Decisions about tools,
structure and trade-offs are easy to forget, and a reviewer reading the code later
cannot see why something was done a certain way.

## Decision

Every significant architecture decision is recorded as an Architecture Decision Record
(ADR) in `docs/adr/`, using the format in [`template.md`](template.md), as described by
[Michael Nygard](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions).

- Files are numbered in order: `NNNN-short-title.md`.
- An accepted ADR is never edited to change its decision. A new ADR supersedes it,
  and the old one's status changes to "Superseded by ADR-NNNN".
- An ADR is written in the same pull request as the change it explains.

## Consequences

- The reasoning behind the design is versioned next to the code.
- Writing an ADR takes a few minutes per decision.
