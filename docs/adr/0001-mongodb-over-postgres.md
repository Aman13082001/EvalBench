# 1. MongoDB over PostgreSQL

**Status:** accepted · **Date:** 2026-08

## Context

EvalBench stores two things: suite definitions and run results. A suite is
a nested document — tests, each with an arbitrary list of assertions whose
shape varies by type (`json-schema` carries a schema object, `latency`
carries a millisecond budget, `llm-rubric` carries prose). A run result is
a suite snapshot plus per-test outcomes plus per-assertion outcomes.

## Decision

Use MongoDB, storing suites and runs as documents.

## Rationale

The assertion system is deliberately open — new types get added without a
migration. In a relational schema that is either a `jsonb` column (in
which case the relational guarantees buy nothing for the part that
changes) or a table per assertion type (which turns adding a type into a
migration and a join).

Reads are overwhelmingly "fetch one run and everything under it", which is
a single document read. There are no cross-entity joins in the product.

## Consequences

- No schema enforcement at the database. Mitigated by Pydantic validating
  every document on the way in and out.
- No transactions across collections. Not needed: a run is written by one
  worker, and the only multi-document operation is the startup reaper,
  which is idempotent.
- Indexes are explicit rather than implied by foreign keys — created in
  the app lifespan (`_ensure_indexes`).

## Alternatives

**PostgreSQL with `jsonb`.** Would work, and would be the better call if
EvalBench grew reporting that aggregates across suites and users. Worth
revisiting if analytics become a product surface rather than a Grafana
dashboard.
