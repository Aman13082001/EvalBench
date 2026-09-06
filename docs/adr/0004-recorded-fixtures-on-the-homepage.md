# 4. The homepage demo is a recording, not a live call

**Status:** accepted · **Date:** 2026-09

## Context

The homepage should demonstrate EvalBench in about ten seconds. The
obvious version runs a real evaluation when the page loads.

## Decision

The homepage animation replays a recorded run, captured by
`scripts/capture_hero.py` into `web/lib/fixtures/hero-run.json`. The page
says so in the caption: *a real evaluation, recorded*.

## Rationale

A live call on page load would need a provider key. The only options are
shipping ours (a public endpoint spending our money, trivially abusable)
or asking a first-time visitor for theirs before they know what the
product does. Both are worse than a recording.

A recording is also instant, works offline, and cannot fail in front of a
visitor — a demo that sometimes shows a rate-limit error is worse than no
demo.

The honesty cost is real, so it is paid explicitly: the fixture comes from
an actual run against `openai/gpt-oss-20b`, the caption says it is a
recording, and the live path is one click away at `/run`.

## Consequences

- The fixture goes stale if assertion output shapes change. Regenerating
  it is one command.
- The demo shows one specific result, including a `faithfulness` failure.
  That was kept deliberately — it demonstrates the tool catching a real
  hallucination, which is more informative than six green ticks.
