from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Neon. DATABASE_URL is the pooled string (host contains "-pooler") used at runtime.
    # DIRECT_DATABASE_URL is the unpooled one, used only by Alembic migrations.
    database_url: str
    direct_database_url: str | None = None
    # Upstash, TLS form: rediss://default:<password>@<host>.upstash.io:6379
    redis_url: str

    cors_origins: str = "http://localhost:3000"
    # Optional regex for origins that change per deploy, e.g. Vercel preview URLs:
    #   ^https://magnitude(-[a-z0-9-]+)?\.vercel\.app$
    cors_origin_regex: str | None = None
    rate_limit_per_minute: int = 120
    signup_limit_per_hour: int = 10
    session_limit_per_minute: int = 30
    profile_cache_seconds: int = 30
    log_level: str = "INFO"

    # Clerk sign-in (optional). Set CLERK_PUBLISHABLE_KEY (a public value; the same one the frontend uses) and signed-in
    # browsers can authenticate with their session token. CLERK_ISSUER / CLERK_JWKS_URL override what it implies.
    clerk_publishable_key: str | None = None
    clerk_issuer: str | None = None
    clerk_jwks_url: str | None = None

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]
