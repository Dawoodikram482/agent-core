# 2. Use poethepoet as the task runner

- **Status:** Accepted
- **Date:** 2026-10-12

## Context

The system design called for `make` targets (setup, lint, test, run). Development
happens on Windows, where `make` is not installed by default, while CI runs on Linux.
Shell-specific scripts (`.sh` or `.ps1`) would mean keeping two versions in sync.

## Decision

Tasks are defined once in `pyproject.toml` under `[tool.poe.tasks]` and run with
[poethepoet](https://poethepoet.natn.io/): `uv run poe <task>`.

poethepoet is a dev dependency, so `uv sync` installs it and nothing else is needed.

## Alternatives considered

- **make:** standard on Linux and macOS, but needs an extra install on Windows.
- **just:** cross-platform, but a separate binary to install outside the Python toolchain.
- **nox / tox:** built for testing across several Python versions; heavier than needed.

## Consequences

- The same commands work on Windows, macOS, Linux and in CI.
- Every task is listed with `uv run poe` (no arguments).
- Supersedes the "`make` targets" line in the Pit Wall system design document.
