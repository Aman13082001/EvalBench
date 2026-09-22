# Deploying EvalBench

Written for whoever is putting this on the internet — including future
me at midnight, which is why every step says what it is for and what
goes wrong when it is skipped.

There are two ways to run EvalBench in public, and they want different
things from you:

- **The hosted demo** — three free tiers, `$0`, no credit card. A
  visitor signs in, runs a benchmark, reads a report. This is what the
  rest of this document describes.
- **A real deployment** — `docker compose up` on a machine you own, with
  the queue, the worker, Prometheus and Grafana. That is the README's
  Quickstart, and nothing here replaces it.

---

## What the hosted demo is, and is not

The free tiers give you one small container with **512 MB of RAM**. So
the hosted instance runs **`JOB_BACKEND=inline`**: a run executes inside
the web process on FastAPI's background tasks, not on a Redis queue with
a separate worker. Everything a visitor can see still works — runs,
scoring, statistics, baselines, the dashboard — but:

| | local compose | hosted demo |
|---|---|---|
| job backend | Redis + RQ worker | inline, in-process |
| concurrency | `--scale worker=2` and up | one run at a time, effectively |
| Prometheus / Grafana | yes | no (`NEXT_PUBLIC_GRAFANA_URL` unset hides it) |
| Ollama / local models | yes | no — hosted providers only |
| cold start | none | ~1 min after the instance sleeps |

Say this on the site rather than letting someone discover it. A demo
that quietly drops half the architecture is worse than one that names
what it left behind.

### It fits in 512 MB — measured

The image carries PyTorch, because the `semantic` evaluator scores with
a local MiniLM embedding model. That is the whole memory budget, so it
was measured rather than assumed, under a hard `--memory=512m` cap:

| | RSS |
|---|---|
| idle | 143 MB |
| peak, cold start through a full run | 451 MB |
| peak, twelve semantic checks scoring at once | 428 MB |
| OOM kills | none |

Three things make that fit, and all three are load-bearing:

1. **CPU-only torch.** pip's default wheel bundles the NVIDIA CUDA
   libraries — about 8 GB of GPU driver for a container with no GPU.
   The Dockerfile installs torch from `download.pytorch.org/whl/cpu`
   first, so the dependency is already satisfied. Image: 9.9 GB → 2.7 GB.
2. **The embedding import is lazy.** `sentence_transformers` is imported
   inside `_get_model()`, not at the top of `semantic.py`. Importing it
   imports torch, which costs ~120 MB the instant it loads. Idle memory
   halved.
3. **One torch thread.** `OMP_NUM_THREADS=1` — torch allocates a memory
   arena per thread, and on a 0.1-CPU instance the extra threads buy
   nothing anyway.

`tests/test_image_weight.py` asserts 1 and 2, so a later tidy-up cannot
silently undo them.

---

## The shape of it

```
visitor's browser
      │  https
      ▼
Next.js frontend  ──►  FastAPI backend  ──►  Groq / Gemini / OpenRouter
  Vercel (free)         Render (free)            (your keys, server side)
                              │
                              ▼
                   MongoDB Atlas M0 (free)
```

Three services, three free tiers, no card. **The backend is a public
URL**: its address is in the frontend's JavaScript, so anyone can call
it directly without visiting your site. That is normal, and it is why
every endpoint requires a token and every run is capped — see *What
protects the key* below.

> **Why not Hugging Face Spaces?** It used to be the obvious answer: 16 GB
> of RAM, free, Docker native. Docker Spaces now require a PRO
> subscription; only Static Spaces remain free, and a static Space cannot
> run FastAPI. Render is the closest free replacement that takes a
> Dockerfile and asks for no credit card. Check current pricing before
> you commit — this changed under us once already.

---

## 1. The database — MongoDB Atlas M0

1. Create a free **M0** cluster at [cloud.mongodb.com](https://cloud.mongodb.com).
   Pick a region near your backend, not near yourself: every query is a
   round trip from the server, and **you cannot change a free cluster's
   region afterwards**.
2. **Database Access** → add a user with a generated password, not one
   you invent.
3. **Network Access** → allow `0.0.0.0/0`. A free-tier host has no fixed
   egress address, so there is nothing narrower to allow; the database
   password is the thing standing guard, which is why it must be
   generated. Leave the *temporary entry* toggle off — it expires in
   six hours and takes your deployment with it.
4. Copy the connection string and substitute the real username and
   password, angle brackets and all:
   `mongodb+srv://user:password@cluster0.xxxxx.mongodb.net/?appName=Cluster0`

M0 is 512 MB. A run document is a few KB, so that is tens of thousands
of runs — far past anything a demo will do.

## 2. The backend — Render

1. [render.com](https://render.com) → sign up with GitHub. No card.
2. **New** → **Web Service** → connect this repository.
3. Settings:
   - **Language / Runtime**: **Docker** (it finds the root `Dockerfile`)
   - **Instance type**: **Free**
   - **Region**: the one nearest your Atlas cluster
4. Add every variable from *The checklist* below under **Environment**.
5. **Create Web Service** and watch the build. The image is ~2.7 GB, so
   the first build takes a while. First boot creates the admin account
   from `ADMIN_USERNAME` / `ADMIN_PASSWORD` and builds the indexes.

Render injects `$PORT` and the image reads it, so there is nothing to
configure for the port. A free instance **sleeps after 15 minutes of
inactivity** and takes about a minute to wake; nothing is lost, the data
is in Atlas. Worth a line on the homepage rather than a visitor thinking
the site is broken.

## 3. The frontend — Vercel

1. **Import Project** → this repository → set **Root Directory** to
   `web`.
2. Environment variable: `NEXT_PUBLIC_API_URL=https://<your-service>.onrender.com`
   (no trailing slash). It is read at **build** time, so changing it
   later needs a redeploy, not just a restart.
3. Leave `NEXT_PUBLIC_GRAFANA_URL` **unset**. Unset means "there is no
   Grafana here", and the dashboard's operations section disappears
   instead of showing a broken frame.
4. Deploy, then copy the resulting URL into the backend's
   `CORS_ORIGINS` and redeploy the backend. Until you do, every request
   from the site fails in the browser with a CORS error while working
   perfectly under `curl` — the single most confusing ten minutes in
   this whole process.

---

## The checklist

Set these on the **backend**. Anything not listed keeps its default from
`evalbench/config.py`.

```bash
# Database
MONGODB_URL=mongodb+srv://user:password@cluster0.xxxxx.mongodb.net/
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

# Keep torch to one thread: it allocates a memory arena per thread, and
# on a fractional CPU the extra threads buy nothing. See the memory
# table above — this is part of why 512 MB is enough.
OMP_NUM_THREADS=1
MKL_NUM_THREADS=1
TOKENIZERS_PARALLELISM=false

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
If the service fails to start with *"Refusing to start"*, read the
message: it names exactly which secret is still a placeholder.

---

## What protects the key

The provider keys are the only thing here that can cost money, so:

- They live as environment variables on the backend. They are never in
  the repository, never in the frontend bundle, and never in an API
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
curl https://<your-service>.onrender.com/health

# The admin account exists and can sign in.
curl -X POST https://<your-service>.onrender.com/auth/login \
  -d "username=you@example.com&password=<ADMIN_PASSWORD>"

# The CLI works against the deployed instance, exactly as it does locally.
export EVALBENCH_API_URL=https://<your-service>.onrender.com
evalbench login -u you@example.com -p <ADMIN_PASSWORD>
evalbench run suites/demo.yaml
```

That last command is the real test: it replays recorded answers through
every assertion type, including the semantic one, which is what loads
the embedding model. If it completes, the memory budget holds on the
real instance and not just on the bench.

Then, in a browser: sign up as a new user, run **Capability showcase**
(10 calls), and check the report appears and the dashboard counts it.

---

## Afterwards

- **Rotate a key** by creating the new one, setting it on the backend,
  waiting for the restart, running something small, and only then
  deleting the old one at the provider.
- **Close sign-ups** by setting `ALLOW_REGISTRATION=false`. It takes
  effect on the next restart; no code change, no rebuild.
- **Ban an account** from the admin page. The ban keys on the addresses
  that account signed in from, so a new sign-up from the same address is
  refused too.
- **Watch the spend** on the provider's own dashboard. The ceilings here
  are arithmetic done before a run; the provider's counter is the truth.
- **If the instance starts OOM-restarting**, the embedding model is the
  first suspect. The fix with the most headroom is an ONNX runtime for
  MiniLM in place of torch — roughly 150 MB instead of 450 MB — at the
  cost of verifying that the scores it returns still match.
