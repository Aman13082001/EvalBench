from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
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
    # Runs per user per day that may use the server's own provider key.
    # Runs made with a user-supplied key are not counted. 0 disables the
    # server key for non-admins entirely.
    daily_run_cap: int = 20
    # Server-key runs per day across every user. The per-user cap guards
    # the key against one greedy account; this guards it against many —
    # registration is free, and five hundred accounts at 20 each is the
    # whole free tier gone before lunch. 0 = no instance-wide cap.
    daily_run_cap_total: int = 200
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
