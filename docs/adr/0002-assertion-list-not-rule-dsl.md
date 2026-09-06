# 2. An assertion list, not a rule DSL

**Status:** accepted · **Date:** 2026-08

## Context

A test needs to express "this answer is correct" in ways that vary a lot:
exact string, substring, regex, semantic similarity, JSON schema validity,
an LLM rubric, a latency budget, groundedness against retrieved context.
Some checks are cheap and local; some cost an API call.

The obvious designs are a single `evaluator` per test (what EvalBench
started with), a boolean expression language, or a flat list.

## Decision

A test carries a list of assertions. Every assertion must pass for the
test to pass. The test score is the weighted mean of assertion scores.

```yaml
assert:
  - type: json-schema
    value: { type: object, required: [name] }
  - type: icontains
    value: hopper
  - type: latency
    max_ms: 8000
```

## Rationale

**A single evaluator is too weak.** Real acceptance criteria are
conjunctive: the answer must be right *and* well-formed *and* fast enough.
Forcing one check per test either loses information or duplicates the test.

**A boolean DSL is too strong.** `OR` and `NOT` sound useful and are
almost never what you want in an acceptance check — "either correct or
fast" is not a criterion anyone means. A DSL would add a parser, a
grammar, error messages, and documentation for expressive power that
mostly enables writing confusing tests. Conjunction covers the real cases.

**Weighted mean keeps partial credit visible.** All-or-nothing pass/fail
would hide that a model is 90% of the way there; per-assertion scores let
the regression detector see gradual movement.

## Consequences

- No way to express "either of these is acceptable". If that comes up, the
  escape hatch is a `regex` with alternation, or a `llm-rubric`.
- Adding a type is a function plus a registry entry — no grammar changes.
- Back-compat is cheap: a test with no `assert` block synthesises one
  assertion from the old `evaluator`/`expected`/`threshold` fields.
