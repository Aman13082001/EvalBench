# EvalBench Playground (web)

A Next.js front end for the public playground: write an eval suite, run it
against a hosted model with your own API key, see the scored report.

## Local dev

```bash
cp .env.local.example .env.local        # NEXT_PUBLIC_API_URL=http://localhost:8000
npm install
npm run dev                             # http://localhost:3005
```

Needs the EvalBench API running (`docker compose up -d api` from the repo
root). The API's `CORS_ORIGINS` already includes `http://localhost:3005`.

## What it does

- `/` — landing, checks the API is reachable and lists hosted providers.
- `/run` — YAML editor + a bring-your-own-key field. Parses the suite
  client-side, `POST`s to `/playground/run`, renders `components/Results`:
  pass rate with bootstrap CI, avg score, cost, latency, per-category and
  per-assertion-type rollups, and a card per test with its assertion
  breakdown and the raw response.
- `/run?id=<run_id>` — a 24-hour permalink to a past run.

## Deploy

Vercel (or any static/Node host). Set `NEXT_PUBLIC_API_URL` to the
deployed API and add that API's origin to its `CORS_ORIGINS`.
