export const EXAMPLE_SUITE = `name: Quick Capability Check
description: >-
  Four quick checks — a fact, a sum, a JSON shape, a definition — to see
  a model answer and a benchmark report in under a minute.
provider: groq
model: openai/gpt-oss-20b
evaluator: icontains
temperature: 0.0
samples: 1

tests:
  - name: capital
    category: knowledge
    prompt: "What is the capital of Japan? One word."
    expected: "Tokyo"

  - name: arithmetic
    category: math
    prompt: "What is 128 divided by 4? Number only."
    expected: "32"

  - name: json-output
    category: format
    prompt: 'Return a JSON object {"lang": "Python", "year": 1991}. JSON only.'
    assert:
      - type: json-schema
        value: { type: object, required: [lang, year] }
      - type: icontains
        value: python
      - type: latency
        max_ms: 12000

  - name: definition
    category: knowledge
    prompt: "In one sentence, what is a hash map?"
    assert:
      - type: semantic
        value: "A data structure mapping keys to values via a hash function for average O(1) lookup."
        threshold: 0.45
`;
