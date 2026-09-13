# Deploying EvalBench

Everything below has a free tier. Nothing here has been executed — these
are the steps, written against the configuration the repo already ships.

The stack splits in three: a **web** front end (static-ish Next.js), an
**API + worker** (Python, needs Mongo and Redis), and **managed data**.

| Piece | Suggested host | Free tier |
|---|---|---|
| `web/` | Vercel | yes |
| API + worker | Fly.io or Railway | yes (limited) |
| MongoDB | MongoDB Atlas M0 | 512 MB |
| Redis | Upstash | yes |
| Grafana + Prometheus | keep local, or Grafana Cloud | yes |

---

## 1. Data

**MongoDB Atlas** — create an M0 cluster, add a database user, allow
access from anywhere (or your host's egress IPs). Copy the connection
string; it becomes `MONGODB_URL`.

**Upstash Redis** — create a database, copy the `rediss://` URL; it
becomes `REDIS_URL`. Only needed if you run `JOB_BACKEND=rq`.

## 2. API

Generate real secrets first — the app **refuses to boot** on the shipped
placeholders (see `_check_secrets`):

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"   # SECRET_KEY
python -c "import secrets; print('eb_' + secrets.token_urlsafe(32))"  # ADMIN_API_KEY
```

Required environment:

```
MONGODB_URL=mongodb+srv://…
MONGODB_DB=evalbench
REDIS_URL=rediss://…
JOB_BACKEND=rq
SECRET_KEY=<generated>
ADMIN_USERNAME=<yours>
ADMIN_PASSWORD=<strong>
ADMIN_API_KEY=<generated>
CORS_ORIGINS=https://<your-vercel-domain>
GROQ_API_KEY=<optional, for server-side runs>
```

Do **not** set `EVALBENCH_ALLOW_INSECURE` in production — that flag exists
so local dev and CI can boot with placeholders.

The repo `Dockerfile` builds both roles. Run two processes from the same
image:

- API: `uvicorn evalbench.api.main:app --host 0.0.0.0 --port 8000`
- Worker: `python -m evalbench.worker`

**Fly.io**

```bash
fly launch --no-deploy          # generates fly.toml from the Dockerfile
fly secrets set MONGODB_URL=… REDIS_URL=… SECRET_KEY=… ADMIN_PASSWORD=… ADMIN_API_KEY=…
fly deploy
fly scale count app=1 worker=1  # if you split into two processes
```

**Railway** — new project from the repo, it detects the Dockerfile; set
the same variables under Variables, and add a second service with the
worker start command.

Health checks: `/health` (includes the database), `/live`, `/ready`.

## 3. Web

On Vercel, set the root directory to `web/` and add:

```
NEXT_PUBLIC_API_URL=https://<your-api-host>
NEXT_PUBLIC_GRAFANA_URL=https://<grafana-host>   # optional
```

Then add the resulting Vercel domain to the API's `CORS_ORIGINS` and
redeploy the API. The homepage, study and example are static, so the
site reads fine even if you stop here; running anything needs an account.

## 4. Verify

```bash
curl https://<api>/health
curl https://<api>/suites/bundled   # 401 — auth is on

EVALBENCH_API_URL=https://<api> evalbench login -u <admin>
EVALBENCH_API_URL=https://<api> evalbench run suites/ci-hosted.yaml
```

## Notes

- **Cold starts.** The API imports `sentence-transformers` for the
  `semantic` assertion, which is a heavy import. On a small instance the
  first request after a scale-to-zero will be slow. Keep one instance warm
  if that matters.
- **Grafana embedding.** `/dashboard` embeds panels, which needs
  `GF_SECURITY_ALLOW_EMBEDDING=true` on the Grafana instance. Anonymous
  viewing is enabled in the local compose for convenience — do not carry
  that into a public deployment without putting Grafana behind auth.
- **Spending the server key.** Runs on the server's key are capped per
  user per day (`DAILY_RUN_CAP`, default 20). Bring-your-own-key runs are
  not capped and the key is never stored. Admins are uncapped.
