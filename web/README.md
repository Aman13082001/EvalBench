# EvalBench web

The Next.js front end. Public pages explain the instrument; everything
that runs a model is behind a free account.

## Local dev

```bash
cp .env.local.example .env.local        # NEXT_PUBLIC_API_URL=http://localhost:8000
npm install
npm run dev                             # http://localhost:3005
```

Needs the EvalBench API running (`docker compose up -d api` from the repo
root). The API's `CORS_ORIGINS` already includes `http://localhost:3005`.

## Pages

- `/` — the architecture, animated stage by stage; why it exists; what it
  checks; the research behind it. Sign-in opens in place.
- `/research` — the power study. Ends with a link to the example.
- `/example` — a recorded two-model comparison with every check expanded.
- `/workbench` — the first page after sign-in: run a benchmark against a
  model (your key or the server's, capped daily), build a benchmark from
  a form, compare two models.
- `/suites`, `/suites/[id]`, `/runs/[id]`, `/compare` — benchmarks, run
  history, baselines, and reports.
- `/dashboard` — the provisioned Grafana dashboard, embedded.
- `/admin` — users and instance stats.

`lib/explain.ts` mirrors `evalbench/explain.py`; a test fails if the two
drift.

## Deploy

Vercel (or any static/Node host). Set `NEXT_PUBLIC_API_URL` to the
deployed API and add that API's origin to its `CORS_ORIGINS`.
