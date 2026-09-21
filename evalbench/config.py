from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    def __repr__(self) -> str:
        # A crash log on a hosted platform prints whatever the traceback
        # touched. If that is the settings object, this is what it sees.
        parts = []
        for name, value in self.model_dump().items():
            if value and any(s in name for s in ("key", "token", "password", "secret")):
                value = "***"
            parts.append(f"{name}={value!r}")
        return f"Settings({', '.join(parts)})"

    __str__ = __repr__

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # MongoDB
    mongodb_url: str = "mongodb://localhost:27017"
    mongodb_db: str = "evalbench"

    # Ollama
    ollama_base_url: str = "http://localhost:11434"

    # Hosted provider API keys (OpenAI-compatible). All optional — a
    # provider is only usable once its key is set.
    openai_api_key: str = ""
    groq_api_key: str = ""
    gemini_api_key: str = ""
    github_token: str = ""
    openrouter_api_key: str = ""

    # Timeouts (seconds)
    default_request_timeout: int = 120
    suite_run_timeout: int = 900

    # Redis + job queue
    redis_url: str = "redis://localhost:6379/0"
    # inline = FastAPI BackgroundTasks (default, no worker needed);
    # rq = enqueue to Redis, executed by `python -m evalbench.worker`.
    job_backend: str = "inline"

    # How often the API sweeps for runs whose worker has gone silent.
    # Only meaningful under `rq`; see evalbench/reaper.py.
    reap_interval_seconds: int = 300
    # Let a custom endpoint be plain http or a private address. For an
    # operator pointing their own EvalBench at a vLLM on their own LAN.
    # Never on a public deployment: it turns the worker into a proxy
    # into whatever network it sits on. See evalbench/core/endpoint.py.
    allow_private_endpoints: bool = False
    worker_metrics_port: int = 9100
    # The server's key is spent in calls — one per generation, one per
    # judged check — and the free tier meters calls (Groq: 1,000 a day
    # per model). So the budget is in calls, not runs: a run is anywhere
    # from 7 to 228 of them. See evalbench/budget.py. Runs made with a
    # caller's own key spend none of this. 0 switches a ceiling off.
    #
    # Per user per day: one person can take at most ~15% of the key's day.
    daily_call_cap: int = 150
    # Per instance per day, everyone together: under Groq's 1,000, with
    # headroom for the admin, who is not counted.
    daily_call_cap_total: int = 800
    # Per run: anything bigger wants the caller's own key — which is the
    # right answer for a research-sized run anyway.
    max_calls_per_run: int = 100
    # The most a request body may be. The largest honest upload — the
    # starter suite's answers at a few KB each — is well under a
    # megabyte; anything bigger is a mistake or a memory attack, and it
    # is refused before it is read.
    max_body_bytes: int = 2 * 1024 * 1024
    # Open by default so a fresh install has a way in. Closed on a public
    # deployment: the admin makes the accounts, and the server's key is
    # not on offer to whoever finds the URL.
    allow_registration: bool = True
    # Behind a reverse proxy (a PaaS, nginx) the client's address is in
    # X-Forwarded-For. Read only when told to: a client can set that
    # header itself, and a ban keyed on a header the banned can choose
    # is no ban.
    trust_proxy: bool = False

    # Authentication
    secret_key: str = "change-this-to-a-random-32-char-string"
    token_expire_minutes: int = 10080
    admin_username: str = "admin"
    admin_password: str = "change-me-in-production"
    admin_api_key: str = "eb_admin_change_me_in_production"

    # CORS
    cors_origins: str = "http://localhost:3000,http://localhost:3005"

    # Application
    log_level: str = "INFO"


settings = Settings()
