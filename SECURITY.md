# Security

What EvalBench protects, how, and what it does not yet. Every claim
below points at the code that makes it true and the test that keeps it
true. The last section is a dated log; add to it whenever security
work lands.

This document is public on purpose. The code is public, so the design
is already readable by anyone who cares to; a design that is only safe
while nobody knows it was never safe. What must stay secret is the
`.env` file — `SECRET_KEY`, the admin password, provider keys — and
that is git-ignored and checked to have never been committed.

---

## Threat model

Who is on the other side, and what they are after:

| who | wants | the line that stops them |
|---|---|---|
| a stranger with a browser | someone else's benchmarks, runs, keys | every data endpoint requires a user; every query is scoped to that user |
| a visitor who pasted a provider key | their key, back | it is never written to the database, and it leaves Redis within hours |
| a visitor who typed a URL | the internal network — Redis, Mongo, cloud metadata | the worker refuses to connect anywhere that is not the public internet, and checks *at connect time* |
| anyone | the server's own provider keys, or its daily budget | server keys go only to the providers they belong to; hosted runs are capped per user per day |
| a script | to knock the service over | per-endpoint rate limits; a reaper for runs whose worker died |

Not in scope: the safety of the *models under test*. EvalBench ships an
adversarial suite (`evalbench/security/`) that grades whether a model
refuses harmful prompts. That is a feature of the instrument, not a
defence of it, and it is documented in the README.

---

## What is in place

### 1. Every data endpoint requires a user

`evalbench/api/deps.py` — `get_current_user` accepts a JWT (bearer)
or an `X-API-Key` header, nothing else. Passwords are bcrypt-hashed
(`evalbench/api/auth.py`). Tokens expire (`TOKEN_EXPIRE_MINUTES`,
default seven days).

Kept true by `tests/test_auth_coverage.py`: it enumerates every route
and asserts each one 401s without a user, except the three health
probes (and the Prometheus `/metrics` scrape target, which exposes
counters, never data). A new endpoint that forgets
`Depends(get_current_user)` fails the suite.

### 2. Every query is scoped to the caller

A user sees only their own suites and runs; an admin sees all. The
scoping is a filter, not a check after the fact — `owner_filter(user)`
goes into the Mongo query, and writes use `mine(user)`, which is strict
even for admins (`evalbench/api/deps.py`).

Kept true by `tests/test_ownership_coverage.py`, which is structural:
it parses the AST of every route handler, finds the ones that touch
owned collections, and asserts each one calls a guard. A handler that
queries `db.suites` without `owner_filter` fails the suite before it
ships. The two exemptions (the startup reaper, the admin aggregation)
are listed in the test with their reasons.

A request for someone else's resource returns **404, not 403**. The
API never confirms that an id it will not serve exists; an attacker
enumerating ids learns nothing from the difference. Deactivated
accounts are refused at authentication.

Admin pages are hidden in the nav for non-admins and, separately, the
admin endpoints check the role server-side (`get_current_admin`). The
nav is a courtesy; the endpoint is the control. Verified on the live
stack with a throwaway account on 2026-09-17.

### 3. The API refuses to boot on placeholder secrets

`evalbench/api/main.py` — `_check_secrets()`. If `SECRET_KEY`, the
admin password or the admin API key are still the values shipped in
`.env.example`, the process exits with a message naming them. Local
development sets `EVALBENCH_ALLOW_INSECURE=1` (docker-compose does);
a real deployment must not.

Accounts are unique at the database, not just at the application:
`users.username` and `users.api_key` have unique indexes created at
startup (`ensure_unique_index`), so two concurrent registrations
cannot both succeed. `tests/test_unique_accounts.py`.

### 4. A visitor's provider key never persists

The run form lets someone use their own Groq/OpenAI key. Where that
key may exist, and for how long, is the tightest rule in the codebase:

- **Never in Mongo.** The run document records that a caller key was
  used, not the key. `tests/test_byo_run.py`, `tests/test_run_keys.py`.
- **In Redis, encrypted, for at most six hours.** It used to travel as
  an RQ job argument, and RQ keeps failed jobs' arguments for a year —
  measured on the live stack, a failed job's TTL was 31,108,291
  seconds. Now `evalbench/runkeys.py` writes it under its own name,
  Fernet-encrypted with a key derived from `SECRET_KEY`, with a TTL;
  the job carries only the run id; the worker reads and deletes it the
  moment the run cannot need it again. The TTL is the guarantee and
  the delete is a courtesy.
- **Never to a provider it was not meant for.** A key is sent as a
  bearer to the provider the run named, and to nothing else.

The UI says all of this next to the field, and says the CLI is the
better path for real work — there the key never leaves the machine.

### 5. The server's keys go only where they belong

`configured_providers()` (`evalbench/core/providers/__init__.py`)
lists the providers this instance actually holds a key for; the picker
offers only those on the server's key, and the run endpoint refuses a
server-key run for anything else with a message saying so. A custom
endpoint (below) is never given a server key by construction — it is
not in the preset table at all.

Hosted runs on the server's key are capped per user per day
(`DAILY_RUN_CAP`, default 20), shown before the run, not discovered as
a 429 after it. Runs on a caller's own key, on local providers, on
supplied answers, or on a custom endpoint do not count.

### 6. Custom endpoints: the server will not be a proxy

A run can name its own OpenAI-compatible URL. That means the worker
makes HTTP requests to an address a stranger typed — server-side
request forgery unless it is made not to be. `evalbench/core/endpoint.py`,
`tests/test_endpoint_url.py` (57 cases):

- **The URL is checked at submission.** https only; a host and nothing
  else (no `user:pass@` — `https://api.groq.com@10.0.0.1/` reads as
  Groq and dials 10.0.0.1; no query string); and *every* address the
  host resolves to must be public. Loopback, RFC 1918, link-local
  (169.254.169.254 is where cloud credentials live), CGNAT, multicast,
  and their IPv6 equivalents including v4-mapped addresses are all
  refused, spelled out rather than left to the interpreter's changing
  idea of "private". Refused as a 400 with the reason.
- **The check happens again inside the connection.** A hostname can
  resolve to a public address when checked and to `127.0.0.1` when
  dialled; the attacker controls the record and its TTL. So
  `PinnedBackend` sits at the socket layer: it resolves the name,
  checks every answer, and opens the socket to the address it just
  approved. There is no second resolution to rebind. TLS still
  verifies against the hostname — confirmed live over a pinned IPv6
  address.
- **Redirects are never followed** (a public host answering
  `302 → http://10.0.0.1/` is the other half of every SSRF write-up),
  an `HTTP_PROXY` in the environment cannot route around the pin, and
  a response is cut off past 8 MB rather than held in memory.
- **A refusal never says what an internal name resolved to.** On a
  public instance that would be a DNS oracle: submit `redis`, `mongo`,
  `vault`, read back the network map one request at a time.
- `ALLOW_PRIVATE_ENDPOINTS=true` relaxes this for an operator whose
  EvalBench and model server share a LAN. It defaults off and is
  documented as never-on-a-public-deployment.

Verified on the live stack: `https://redis:6379/v1` refused from inside
the Docker network; Groq's own endpoint accepted and run as a custom
endpoint with a caller key, which was absent from the run document and
gone from Redis afterwards.

### 7. Abuse limits

- Per-endpoint rate limits via slowapi (`10/minute` on run submission,
  `20/minute` on adoption).
- Per-provider concurrency ceilings sized to free tiers, and a shared
  backoff on 429 so four workers do not race a shut door
  (`evalbench/core/providers/openai_compat.py`, `tests/test_rate_limits.py`).
- A reaper for runs whose worker died mid-run, so a stuck job cannot
  hold a "running" state forever (`evalbench/reaper.py`).

### 8. Input handling

- Every id is validated as an ObjectId before it reaches a query.
- Suite YAML is read with `yaml.safe_load`, never `yaml.load`.
- Supplied answers are parsed and matched against the suite server-side
  regardless of what the client checked (`evalbench/answers.py`); a row
  that matches nothing is refused by name.
- Model output is rendered as text by React, never as HTML.

### 9. Containers

Both images run as an unprivileged user (`evalbench` uid 1000 in the
API/worker image, `nextjs` uid 1001 in the web image). Every service
has a healthcheck.

---

## Known gaps

Listed so nobody has to discover them. Each has its fix.

| gap | why it matters | the fix |
|---|---|---|
| `docker-compose.yml` publishes Mongo (27017), Redis (6379), Ollama, Prometheus and Grafana on **all host interfaces**, with no authentication on Mongo or Redis | fine on a laptop; on a VPS with the compose file as-is, the database is on the internet | bind to loopback (`"127.0.0.1:27017:27017"`) or drop the `ports:` for services the browser never needs. The planned $0 deployment (Atlas + a single API container) has no such exposure |
| API keys are stored in plaintext in `users.api_key` | a database leak leaks every key | store a SHA-256 of the key and look up by hash |
| the JWT lives in `localStorage` | readable by any script that runs on the page (XSS) | an `httpOnly` cookie. Mitigated today by rendering no user-supplied HTML |
| the rate limiter is in-process | with N API replicas the limit is N× the number written | slowapi's Redis storage backend |
| the daily cap is check-then-insert | two simultaneous submissions at 19/20 both pass | count inside the insert (a conditional update) |
| no request body size cap | a very large `answers` payload costs memory before validation rejects it | a body-size limit in the ASGI server or a length check on the field |
| Grafana runs with anonymous viewer access and its shipped admin password | needed for the embedded dashboard panels; the password is not | change `GF_SECURITY_ADMIN_PASSWORD` on any deployment; keep anonymous at Viewer |
| logout is client-side only | a stolen token works until it expires (seven days) | a short-lived token with a refresh, or a revocation list |
| no password policy at registration | `password: "a"` is accepted | a minimum length; the rest is the user's business |
| no dependency audit in CI | a known-vulnerable package would not be flagged | `pip-audit` and `npm audit` as a CI step |
| `EVALBENCH_ALLOW_INSECURE=1` is set in `docker-compose.yml` | it is a development file; a deployment copied from it would boot on placeholder secrets | never carry that line into a production compose file |

---

## Reporting

This is an open-source portfolio project. If you find something, open
a GitHub issue — or, if it is something that should not be public
before it is fixed, email the address on the GitHub profile. It will be
acknowledged, fixed, and credited here.

---

## Log

Dated, newest first. When security work lands, add a line.

- **2026-09-19** — Custom endpoints with SSRF defence: URL rules,
  IP-pinned connections, no redirects, response cap, no DNS oracle in
  refusals (`2a68b86`).
- **2026-09-18** — A caller's provider key moved out of the persisted
  RQ job into an encrypted, six-hour Redis stash, deleted after the
  run; measured 360-day plaintext exposure before (`cc749b6`).
- **2026-09-17** — Providers the server holds no key for are no longer
  offered on the server's key (`45eb41c`). Unique indexes on
  `users.username` and `users.api_key` (`82410e3`). Admin isolation
  verified live with a throwaway account.
- **2026-09-16** — Shared 429 backoff across workers (`8c97c29`).
- **2026-09-12** — Own-key runs and the per-user daily cap on the
  server's key (`71897e4`).
- **2026-09-07** — Per-user ownership with the structural AST test;
  admin endpoints (`adc2146`). `evalbench reset-password` for admin
  lockout recovery (`0b50ae8`).
- **2026-09-04** — Every data endpoint requires a user, with the
  coverage test (`4b3d982`). Refuse to boot on placeholder secrets
  (`60ba731`).
- **2026-08-20** — JWT authentication and rate limiting (`c6941ce`).
