# Deploying EvalBench

Written for whoever is putting this on the internet — including future
me at midnight, which is why every step says what it is for and what
goes wrong when it is skipped.

There are two ways to run EvalBench in public, and they want different
things from you:

- **The hosted demo** — three free tiers, `$0`, one afternoon. A
  visitor signs in, runs a benchmark, reads a report. This is what the
  rest of this document describes.
- **A real deployment** — `docker compose up` on a machine you own, with
  the queue, the worker, Prometheus and Grafana. That is the README's
  Quickstart, and nothing here replaces it.

---

## What the hosted demo is, and is not

The free tiers give you one small container. So the hosted instance runs
**`JOB_BACKEND=inline`**: a run executes inside the web process on
FastAPI's background tasks, not on a Redis queue with a separate worker.
Everything a visitor can see still works — runs, scoring, statistics,
baselines, the dashboard — but:

| | local compose | hosted demo |
|---|---|---|
| job backend | Redis + RQ worker | inline, in-process |
| concurrency | `--scale worker=2` and up | one run at a time, effectively |
| Prometheus / Grafana | yes | no (`NEXT_PUBLIC_GRAFANA_URL` unset hides it) |
| Ollama / local models | yes | no — hosted providers only |
| cold start | none | ~30s after the Space sleeps |

Say this on the site rather than letting someone discover it. A demo
that quietly drops half the architecture is worse than one that names
what it left behind.

---

## The shape of it

```
visitor's browser
      │  https
      ▼
Next.js frontend  ──►  FastAPI backend  ──►  Groq / Gemini / OpenRouter
  Vercel (free)        HF Spaces (free)         (your keys, server side)
                              │
                              ▼
                   MongoDB Atlas M0 (free)
```

Three services, three free tiers. **The backend is a public URL**: its
address is in the frontend's JavaScript, so anyone can call it directly
without visiting your site. That is normal and it is why every endpoint
requires a token and every run is capped — see *What protects the key*
below.

---

## 1. The database — MongoDB Atlas M0

1. Create a free **M0** cluster at [cloud.mongodb.com](https://cloud.mongodb.com).
2. **Database Access** → add a user with a password you generate, not one
   you invent.
3. **Network Access** → allow `0.0.0.0/0`. A Space has no fixed egress
   address, so there is nothing narrower to allow; the database password
   is the thing standing guard, which is why it must be generated.
4. Copy the connection string. It looks like
   `mongodb+srv://user:password@cluster.xxxxx.mongodb.net/`.

M0 is 512 MB. A run document is a few KB, so that is tens of thousands
of runs — far past anything a demo will do.

## 2. The backend — Hugging Face Spaces

1. **New Space** → SDK **Docker** → **Blank**. Any hardware tier; the
   free CPU one is enough.
2. Push this repository to the Space's git remote. The root `Dockerfile`
   is what builds; it reads `$PORT`, which Spaces sets to 7860, so
   nothing needs editing.
3. In the Space's **Settings → Variables and secrets**, add everything
   from *The checklist* below. Secrets there are injected as environment
   variables and are never visible in the build logs or the repo.
4. Watch the build. First boot creates the admin account from
   `ADMIN_USERNAME` / `ADMIN_PASSWORD` and builds the database indexes.

A free Space sleeps after a period with no traffic and takes ~30
seconds to wake. Nothing is lost when it sleeps — the data is in Atlas.

## 3. The frontend — Vercel

1. **Import Project** → this repository → set **Root Directory** to
   `web`.
2. Environment variable: `NEXT_PUBLIC_API_URL=https://<your-space>.hf.space`
   (no trailing slash). It is read at **build** time, so changing it
   later needs a redeploy, not just a restart.
3. Leave `NEXT_PUBLIC_GRAFANA_URL` **unset**. Unset means "there is no
   Grafana here", and the dashboard's operations section disappears
   instead of showing a broken frame.
4. Deploy, then copy the resulting URL into the backend's
   `CORS_ORIGINS` and redeploy the Space. Until you do, every request
   from the site fails in the browser with a CORS error while working
   perfectly under `curl` — the single most confusing ten minutes in
   this whole process.

---

## The checklist

Set these on the **backend** (the Space). Anything not listed keeps its
default from `evalbench/config.py`.

```bash
# Database
MONGODB_URL=mongodb+srv://user:password@cluster.xxxxx.mongodb.net/
MONGODB_DB=evalbench

# Sessions and the admin account. Generate, never invent:
#   python -c "import secrets; print(secrets.token_urlsafe(32))"
SECRET_KEY=<32+ random characters>
ADMIN_USERNAME=you@example.com
ADMIN_PASSWORD=<generated>
ADMIN_API_KEY=<generated, prefixed eb_>

# Where the frontend lives. Anything not in this list is refused by the
# browser; a trailing slash will not match.
CORS_ORIGINS=https://your-app.vercel.app

# One process, no Redis, no worker.
JOB_BACKEND=inline

# Behind a platform proxy the caller's address is in X-Forwarded-For.
# Without this every visitor looks like the proxy, so rate limits and
# IP bans apply to all of them at once — or to none.
TRUST_PROXY=true

# Your provider keys. Only the ones you actually have.
GROQ_API_KEY=...
GEMINI_API_KEY=...
OPENROUTER_API_KEY=...

# Who may create an account. true = anyone with an email address, held
# to the call budget below. false = you make the accounts by hand.
ALLOW_REGISTRATION=true

# The budget on your key, in calls. Defaults shown; see SECURITY.md.
MAX_CALLS_PER_RUN=250
DAILY_CALL_CAP=250
DAILY_CALL_CAP_TOTAL=800
```

**Do not set `EVALBENCH_ALLOW_INSECURE`.** It exists so local dev and CI
can boot with placeholder secrets. Without it the server refuses to
start while `SECRET_KEY`, `ADMIN_PASSWORD` or `ADMIN_API_KEY` is still
the shipped default — which is the behaviour you want on a public host.
If the Space fails to start with *"Refusing to start"*, read the message:
it names exactly which secret is still a placeholder.

---

## What protects the key

The provider keys are the only thing here that can cost money, so:

- They live as environment secrets on the backend. They are never in the
  repository, never in the frontend bundle, and never in an API
  response. The browser cannot see them.
- `Settings.__repr__` redacts every field whose name contains *key*,
  *token*, *password* or *secret*, so a traceback cannot print one.
- Every run declares its cost in **calls** before it is accepted, and
  three ceilings apply: per run, per user per day, and across everyone
  per day. A stranger with an account can spend `DAILY_CALL_CAP` and
  then no more.
- A visitor may use **their own key** instead; it is held for the run
  and never written to the database.
- Sign-up and sign-in are rate limited per address, bans key on the
  addresses an account actually used, and request bodies are capped.

The full account, including what is *not* solved, is in
[SECURITY.md](SECURITY.md).

---

## Verify it, before telling anyone

```bash
# The API is up and reachable from outside.
curl https://<your-space>.hf.space/health

# The admin account exists and can sign in.
curl -X POST https://<your-space>.hf.space/auth/login \
  -d "username=you@example.com&password=<ADMIN_PASSWORD>"

# The CLI works against the deployed instance, exactly as it does locally.
export EVALBENCH_API_URL=https://<your-space>.hf.space
evalbench login
evalbench run suites/demo.yaml
```

Then, in a browser: sign up as a new user, run **Capability showcase**
(10 calls), and check the report appears and the dashboard counts it.
If that works, everything between the browser and the provider works.

---

## Afterwards

- **Rotate a key** by creating the new one, setting it on the Space,
  waiting for the restart, running something small, and only then
  deleting the old one at the provider.
- **Close sign-ups** by setting `ALLOW_REGISTRATION=false`. It takes
  effect on the next restart; no code change, no redeploy of the image.
- **Ban an account** from the admin page. The ban keys on the addresses
  that account signed in from, so a new sign-up from the same address is
  refused too.
- **Watch the spend** on the provider's own dashboard. The ceilings here
  are arithmetic done before a run; the provider's counter is the truth.
