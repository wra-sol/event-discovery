from __future__ import annotations

import json
import logging
import os
import secrets
import sqlite3
from collections.abc import Generator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Annotated, Any

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlite3 import Connection
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from . import pg_auth
from .auth_db import (
    apply_auth_migrations,
    create_account_with_user,
    fetch_user_by_id,
    open_auth_connection,
    verify_user_password,
)
from .crawl_runner import start_crawl_job
from .rate_limit import check_rate_limit, client_key
from .settings_env import (
    agent_api_token,
    allow_ephemeral_session_secret,
    cors_allow_origins,
    crawl_api_token,
    database_url,
    is_production,
)
from .paths import (
    account_discovery_db_path,
    auth_db_path,
    maybe_migrate_legacy_flat_discovery_db,
    resolve_data_root,
)
from .pipeline import load_config, migrate_database_only, run
from .repository import (
    EventListFilters,
    allocate_unique_source_key,
    count_discovered_events,
    create_website,
    delete_website,
    fetch_website_source_for_crawl,
    get_crawl_job,
    get_discovery_settings_bundle,
    insert_crawl_job,
    list_crawl_jobs,
    list_discovered_events,
    list_event_sources,
    list_websites,
    merge_site_preferences_into_cfg,
    open_connection,
    patch_discovery_settings,
    patch_website,
    reorder_websites,
    set_all_websites_enabled,
    update_event_review,
)
from .source_discovery import discover_source_proposal, pick_type_and_config_for_website
from .source_validation import validate_website_type_and_config
from .website_config_schema import website_source_types_payload

log = logging.getLogger(__name__)

_EVENT_SORT_KEYS = frozenset({"relevance", "start_at", "title", "source", "reviewed"})
_EVENT_ORDER_VALUES = frozenset({"asc", "desc"})


def _normalize_events_as_of(as_of: str | None) -> str | None:
    s = (as_of or "").strip()[:10]
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        return s
    return None

PACKAGE_DIR = Path(__file__).resolve().parent
STATIC_DIR = PACKAGE_DIR / "static"


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        rid = secrets.token_hex(8)
        request.state.request_id = rid
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response


@contextmanager
def _auth_conn(request: Request):
    if getattr(request.app.state, "use_postgres_auth", False):
        dsn = request.app.state.pg_dsn
        with pg_auth.connect(dsn) as conn:
            yield conn
    else:
        conn = open_auth_connection(request.app.state.auth_db_path)
        try:
            yield conn
        finally:
            conn.close()


def _fetch_user_by_id(request: Request, conn: Any, user_id: int) -> dict[str, Any] | None:
    if getattr(request.app.state, "use_postgres_auth", False):
        return pg_auth.fetch_user_by_id(conn, user_id)
    return fetch_user_by_id(conn, user_id)


def _verify_user_password(
    request: Request, conn: Any, email: str, password: str
) -> dict[str, Any] | None:
    if getattr(request.app.state, "use_postgres_auth", False):
        return pg_auth.verify_user_password(conn, email, password)
    return verify_user_password(conn, email, password)


def _create_account_with_user(
    request: Request,
    conn: Any,
    *,
    account_name: str,
    email: str,
    password: str,
) -> tuple[int, int]:
    if getattr(request.app.state, "use_postgres_auth", False):
        return pg_auth.create_account_with_user(
            conn,
            account_name=account_name,
            email=email,
            password=password,
        )
    return create_account_with_user(
        conn,
        account_name=account_name,
        email=email,
        password=password,
    )


def _auth_rate_limit(
    request: Request,
    *,
    prefix: str,
    max_events: int,
    window_seconds: float,
) -> None:
    ip = client_key(
        lambda h: request.headers.get(h) or "",
        request.client.host if request.client else "",
    )
    key = f"{prefix}:{ip}"
    allowed, retry_after = check_rate_limit(
        key, max_events=max_events, window_seconds=window_seconds
    )
    if not allowed:
        ra = int(retry_after or 1) + 1
        raise HTTPException(
            status_code=429,
            detail="Too many attempts. Try again later.",
            headers={"Retry-After": str(ra)},
        )


def _auth_disabled() -> bool:
    return os.environ.get("EVENT_DISCOVERY_DISABLE_AUTH", "").lower() in ("1", "true", "yes")


def _signup_allowed() -> bool:
    """
    Public sign-up is on by default when auth is required.
    Set EVENT_DISCOVERY_ALLOW_SIGNUP to 0, false, no, or off to disable.
    """
    raw = os.environ.get("EVENT_DISCOVERY_ALLOW_SIGNUP", "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _default_account_name_from_email(email: str) -> str:
    local = email.strip().split("@", 1)[0].strip()
    return local or "My account"


_SIGNUP_PASSWORD_MIN_LEN = 8
_SIGNUP_PASSWORD_MAX_LEN = 72


_SESSION_SECRET_FALLBACK: str | None = None


def _session_secret() -> str:
    global _SESSION_SECRET_FALLBACK
    if _auth_disabled():
        return os.environ.get("EVENTS_SESSION_SECRET") or "dev-not-for-production-auth-disabled"
    env = os.environ.get("EVENTS_SESSION_SECRET") or os.environ.get("DISCOVERY_SESSION_SECRET")
    if env and len(env) >= 16:
        return env
    if is_production() and not allow_ephemeral_session_secret():
        raise RuntimeError(
            "EVENTS_SESSION_SECRET (or DISCOVERY_SESSION_SECRET) must be set to at least 16 "
            "characters when EVENT_DISCOVERY_ENV=production (or set "
            "EVENT_DISCOVERY_ALLOW_EPHEMERAL_SESSION=1 only for local debugging)."
        )
    if _SESSION_SECRET_FALLBACK is None:
        _SESSION_SECRET_FALLBACK = secrets.token_hex(32)
        log.warning(
            "EVENTS_SESSION_SECRET unset; using an ephemeral secret (sessions reset when the "
            "process restarts). Set EVENTS_SESSION_SECRET for production."
        )
    return _SESSION_SECRET_FALLBACK


@asynccontextmanager
async def lifespan(app: FastAPI):
    data_root = resolve_data_root()
    app.state.data_root = data_root
    cfg = load_config(os.environ.get("EVENT_DISCOVERY_CONFIG"))
    maybe_migrate_legacy_flat_discovery_db(data_root, cfg)
    dsn = database_url()
    if dsn:
        pg_auth.apply_auth_migrations_pg(dsn)
        app.state.use_postgres_auth = True
        app.state.pg_dsn = dsn
        app.state.auth_db_path = auth_db_path(data_root)
        log.info("Auth backend: PostgreSQL (DATABASE_URL)")
    else:
        app.state.use_postgres_auth = False
        app.state.pg_dsn = None
        auth_path = auth_db_path(data_root)
        apply_auth_migrations(auth_path)
        app.state.auth_db_path = auth_path
        log.info("Auth backend: SQLite at %s", auth_path)
    prepared_account_dbs: set[int] = set()
    app.state.prepared_account_dbs = prepared_account_dbs
    if _auth_disabled():
        db_path = account_discovery_db_path(data_root, 1, cfg=cfg)
        migrate_database_only(
            config_path=os.environ.get("EVENT_DISCOVERY_CONFIG"),
            output_dir=data_root,
            database_path=db_path,
        )
        app.state.prepared_account_dbs.add(1)
        log.info(
            "Events web UI: auth disabled; using account 1 DB at %s",
            db_path,
        )
    else:
        log.info("Events web UI data root %s (auth required)", data_root)
    yield


app = FastAPI(title="Event discovery", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=_session_secret(),
    max_age=14 * 24 * 3600,
    same_site="lax",
    https_only=os.environ.get("EVENTS_SESSION_HTTPS_ONLY", "").lower()
    in ("1", "true", "yes"),
)
app.add_middleware(RequestIdMiddleware)
_cors = cors_allow_origins()
if _cors:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if not is_production() else [],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.get("/health")
def health() -> dict[str, Any]:
    """Railway / load balancer probe; must not require auth."""
    try:
        from importlib.metadata import version as pkg_version

        ver = pkg_version("event-discovery")
    except Exception:
        ver = "0.1.0"
    return {"status": "ok", "version": ver}


def require_user(request: Request) -> dict[str, Any]:
    if _auth_disabled():
        return {"id": 0, "account_id": 1, "email": "dev@local"}
    user_id = request.session.get("user_id")
    if user_id is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    with _auth_conn(request) as conn:
        user = _fetch_user_by_id(request, conn, int(user_id))
    if user is None:
        request.session.clear()
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def _timing_safe_equal_str(expected: str, candidate: str) -> bool:
    """Compare two strings in constant time (bytes); handles unequal lengths."""
    exp_b = expected.encode("utf-8")
    cand_b = candidate.encode("utf-8")
    if len(cand_b) != len(exp_b):
        secrets.compare_digest(exp_b, exp_b)
        return False
    return secrets.compare_digest(cand_b, exp_b)


def require_user_or_crawl_api(request: Request) -> dict[str, Any]:
    """
    Session user, or Bearer EVENTS_CRAWL_API_TOKEN with X-Crawl-Account-Id for crawl routes.
    When auth is disabled, only session-style dev user applies (token is ignored).
    """
    if _auth_disabled():
        return require_user(request)

    auth_header = (request.headers.get("Authorization") or "").strip()
    if auth_header.lower().startswith("bearer "):
        configured = crawl_api_token()
        got = auth_header[7:].strip()
        if not configured:
            raise HTTPException(
                status_code=503,
                detail="Crawl API token is not configured (EVENTS_CRAWL_API_TOKEN)",
            )
        if not _timing_safe_equal_str(configured, got):
            raise HTTPException(status_code=401, detail="Invalid crawl API token")
        raw_account = (request.headers.get("X-Crawl-Account-Id") or "").strip()
        if not raw_account.isdigit():
            raise HTTPException(
                status_code=400,
                detail="X-Crawl-Account-Id must be a positive integer account id",
            )
        account_id = int(raw_account)
        if account_id < 1:
            raise HTTPException(
                status_code=400,
                detail="X-Crawl-Account-Id must be >= 1",
            )
        log.info("Crawl API token auth for account_id=%s", account_id)
        return {"id": 0, "account_id": account_id, "email": "crawl-api@internal"}

    return require_user(request)


def _account_id_from_header(request: Request, header_name: str) -> int:
    raw_account = (request.headers.get(header_name) or "").strip()
    if not raw_account.isdigit():
        raise HTTPException(
            status_code=400,
            detail=f"{header_name} must be a positive integer account id",
        )
    account_id = int(raw_account)
    if account_id < 1:
        raise HTTPException(status_code=400, detail=f"{header_name} must be >= 1")
    return account_id


def _agent_api_user_from_bearer(request: Request) -> dict[str, Any] | None:
    auth_header = (request.headers.get("Authorization") or "").strip()
    if not auth_header.lower().startswith("bearer "):
        return None
    configured = agent_api_token()
    got = auth_header[7:].strip()
    if not configured:
        raise HTTPException(
            status_code=503,
            detail="Agent API token is not configured (EVENTS_AGENT_API_TOKEN)",
        )
    if not _timing_safe_equal_str(configured, got):
        raise HTTPException(status_code=401, detail="Invalid agent API token")
    account_id = _account_id_from_header(request, "X-Agent-Account-Id")
    log.info("Agent API token auth for account_id=%s", account_id)
    return {"id": 0, "account_id": account_id, "email": "agent-api@internal"}


def require_user_or_agent_api(request: Request) -> dict[str, Any]:
    """
    Session user, or Bearer EVENTS_AGENT_API_TOKEN with X-Agent-Account-Id.
    This broader machine credential is intended for agents managing sources/settings.
    """
    if _auth_disabled():
        return require_user(request)

    agent_user = _agent_api_user_from_bearer(request)
    if agent_user is not None:
        return agent_user

    return require_user(request)


def require_user_or_agent_or_crawl_api(request: Request) -> dict[str, Any]:
    """Automation run accepts both broad agent tokens and narrow crawl tokens."""
    if _auth_disabled():
        return require_user(request)
    auth_header = (request.headers.get("Authorization") or "").strip()
    if auth_header.lower().startswith("bearer "):
        got = auth_header[7:].strip()
        configured_agent = agent_api_token()
        if configured_agent and _timing_safe_equal_str(configured_agent, got):
            account_id = _account_id_from_header(request, "X-Agent-Account-Id")
            return {"id": 0, "account_id": account_id, "email": "agent-api@internal"}
        configured_crawl = crawl_api_token()
        if configured_crawl and _timing_safe_equal_str(configured_crawl, got):
            account_id = _account_id_from_header(request, "X-Crawl-Account-Id")
            return {"id": 0, "account_id": account_id, "email": "crawl-api@internal"}
        if configured_agent is None and configured_crawl is None:
            raise HTTPException(
                status_code=503,
                detail="No agent or crawl API token is configured",
            )
        raise HTTPException(status_code=401, detail="Invalid API token")
    return require_user(request)


def ensure_account_db_ready(request: Request, account_id: int) -> Path:
    aid = int(account_id)
    prepared: set[int] = request.app.state.prepared_account_dbs
    if aid in prepared:
        cfg = load_config(os.environ.get("EVENT_DISCOVERY_CONFIG"))
        return account_discovery_db_path(request.app.state.data_root, aid, cfg=cfg)
    cfg = load_config(os.environ.get("EVENT_DISCOVERY_CONFIG"))
    db_path = account_discovery_db_path(request.app.state.data_root, aid, cfg=cfg)
    migrate_database_only(
        config_path=os.environ.get("EVENT_DISCOVERY_CONFIG"),
        output_dir=request.app.state.data_root,
        database_path=db_path,
    )
    prepared.add(aid)
    log.info("Prepared discovery DB for account %s at %s", aid, db_path)
    return db_path


def get_db(
    request: Request,
    user: Annotated[dict[str, Any], Depends(require_user)],
) -> Generator[Connection, None, None]:
    db_path = ensure_account_db_ready(request, int(user["account_id"]))
    conn = open_connection(db_path)
    try:
        yield conn
    finally:
        conn.close()


def get_db_crawl(
    request: Request,
    user: Annotated[dict[str, Any], Depends(require_user_or_crawl_api)],
) -> Generator[Connection, None, None]:
    """Like get_db but allows machine Bearer token for crawl job routes."""
    db_path = ensure_account_db_ready(request, int(user["account_id"]))
    conn = open_connection(db_path)
    try:
        yield conn
    finally:
        conn.close()


def get_db_agent(
    request: Request,
    user: Annotated[dict[str, Any], Depends(require_user_or_agent_api)],
) -> Generator[Connection, None, None]:
    """Like get_db but allows the broader agent Bearer token for source/settings routes."""
    db_path = ensure_account_db_ready(request, int(user["account_id"]))
    conn = open_connection(db_path)
    try:
        yield conn
    finally:
        conn.close()


def _require_writes_allowed(request: Request) -> None:
    if os.environ.get("EVENTS_WEB_READ_ONLY", "").lower() in ("1", "true", "yes"):
        raise HTTPException(status_code=403, detail="Server is read-only")


class EventRow(BaseModel):
    id: int
    dedupe_key: str
    title: str
    url: str
    source: str
    website_id: int | None = None
    start_at: str | None = None
    end_at: str | None = None
    venue: str | None = None
    raw_snippet: str = ""
    relevance_score: float
    relevance_reasons: list[str] = Field(default_factory=list)
    first_seen_at: str | None = None
    last_seen_at: str | None = None
    reviewed: bool = False
    rejected: bool = False
    notes: str = ""


class EventsPage(BaseModel):
    events: list[EventRow]
    total: int
    limit: int
    offset: int


class ReviewPatch(BaseModel):
    reviewed: bool | None = None
    rejected: bool | None = None
    notes: str | None = None


class ReviewState(BaseModel):
    id: int
    reviewed: bool
    rejected: bool
    notes: str


class WebConfig(BaseModel):
    read_only: bool
    auth_disabled: bool = False
    allow_signup: bool = False
    advanced_ui: bool = False


class WebsiteRow(BaseModel):
    id: int
    source_key: str
    enabled: bool
    type: str
    config: dict[str, Any] = Field(default_factory=dict)
    preferences: dict[str, Any] = Field(default_factory=dict)
    source_label: str | None = None
    display_order: int = 0
    created_at: str | None = None
    updated_at: str | None = None
    last_event_activity_at: str | None = None


class WebsitePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    config: dict[str, Any] | None = None
    type: str | None = None
    source_label: str | None = None
    preferences: dict[str, Any] | None = None

    @model_validator(mode="after")
    def at_least_one_field(self) -> WebsitePatch:
        if (
            self.enabled is None
            and self.config is None
            and self.type is None
            and self.source_label is None
            and self.preferences is None
        ):
            raise ValueError(
                "At least one of enabled, config, type, source_label, preferences must be provided"
            )
        return self


class WebsiteReorderBody(BaseModel):
    ids: list[int]


class WebsiteCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_key: str = Field(min_length=1, max_length=120)
    type: str = Field(min_length=1)
    config: dict[str, Any] = Field(default_factory=dict)
    source_label: str | None = None
    enabled: bool = False


class SourceDiscoveryBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1, max_length=2048)
    source_key: str | None = Field(default=None, max_length=120)
    source_label: str | None = Field(default=None, max_length=200)
    use_llm: bool = True


class SourceDiscoveryResponse(BaseModel):
    recommended_type: str
    confidence: float
    suggested_config: dict[str, Any]
    source_key: str
    source_label: str
    evidence: list[str]
    caveats: list[str]
    method: str
    save_ready: bool
    validation_error: str | None = None
    discovered_url: str
    fallback_type: str | None = None
    fallback_config: dict[str, Any] | None = None


class WebsiteQuickAddBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1, max_length=2048)
    name: str = Field(min_length=1, max_length=200)
    use_llm: bool = True


class DiscoverySummaryBlock(BaseModel):
    method: str
    recommended_type: str
    save_ready: bool
    evidence: list[str]
    caveats: list[str]


class WebsiteQuickAddResponse(BaseModel):
    website: WebsiteRow
    discovery: DiscoverySummaryBlock


class CrawlJobAccepted(BaseModel):
    job_id: int
    status: str = "queued"


class CrawlJobCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = "full"


class CrawlJobRow(BaseModel):
    id: int
    kind: str
    website_id: int | None = None
    status: str
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    event_count: int | None = None
    error_message: str | None = None
    summary: dict[str, Any] = Field(default_factory=dict)


class WebsiteDeleteResponse(BaseModel):
    deleted: bool = True
    events_removed: int


class HttpSettingsBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_agent: str = ""
    delay_seconds: float = Field(gt=0, default=0.75)
    timeout_seconds: float = Field(gt=0, default=45.0)


class ScoringSettingsBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    horizon_days: int = Field(ge=0, default=120)
    positive_keywords: list[str] = Field(default_factory=list)
    ward_keywords: list[str] = Field(default_factory=list)
    negative_keywords: list[str] = Field(default_factory=list)


class EnrichmentSettingsBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    max_urls: int = Field(ge=0, default=100)


class DiscoverySettingsResponse(BaseModel):
    http: HttpSettingsBlock
    scoring: ScoringSettingsBlock
    enrichment: EnrichmentSettingsBlock


class DiscoverySettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    http: dict[str, Any] | None = None
    scoring: dict[str, Any] | None = None
    enrichment: dict[str, Any] | None = None

    @model_validator(mode="after")
    def at_least_one(self) -> DiscoverySettingsPatch:
        if self.http is None and self.scoring is None and self.enrichment is None:
            raise ValueError("At least one of http, scoring, enrichment must be set")
        return self


class WebsitesBulkEnabledBody(BaseModel):
    enabled: bool


def _merged_yaml_config() -> dict[str, Any]:
    return load_config(os.environ.get("EVENT_DISCOVERY_CONFIG"))


def _keyword_list_from_value(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [p.strip() for p in raw.split(",") if p.strip()]
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    return []


def _bundle_dict_to_discovery_response(bundle: dict[str, Any]) -> DiscoverySettingsResponse:
    http_raw = bundle.get("http") if isinstance(bundle.get("http"), dict) else {}
    sc_raw = bundle.get("scoring") if isinstance(bundle.get("scoring"), dict) else {}
    en_raw = bundle.get("enrichment") if isinstance(bundle.get("enrichment"), dict) else {}
    http_b = {
        "user_agent": str(http_raw.get("user_agent") or "").strip(),
        "delay_seconds": float(http_raw.get("delay_seconds") or 0.75),
        "timeout_seconds": float(http_raw.get("timeout_seconds") or 45.0),
    }
    sc_b = {
        "horizon_days": int(sc_raw.get("horizon_days") or 120),
        "positive_keywords": _keyword_list_from_value(sc_raw.get("positive_keywords")),
        "ward_keywords": _keyword_list_from_value(sc_raw.get("ward_keywords")),
        "negative_keywords": _keyword_list_from_value(sc_raw.get("negative_keywords")),
    }
    en_enabled = en_raw.get("enabled")
    if en_enabled is None:
        en_enabled = True
    try:
        max_urls = int(en_raw.get("max_urls") if en_raw.get("max_urls") is not None else 100)
    except (TypeError, ValueError):
        max_urls = 100
    en_b = {"enabled": bool(en_enabled), "max_urls": max(0, max_urls)}
    return DiscoverySettingsResponse(
        http=HttpSettingsBlock.model_validate(http_b),
        scoring=ScoringSettingsBlock.model_validate(sc_b),
        enrichment=EnrichmentSettingsBlock.model_validate(en_b),
    )


def _bundle_to_discovery_response(conn: Connection) -> DiscoverySettingsResponse:
    defaults = _merged_yaml_config()
    bundle = get_discovery_settings_bundle(conn, defaults)
    try:
        return _bundle_dict_to_discovery_response(bundle)
    except Exception:
        log.exception("Invalid discovery settings bundle")
        raise HTTPException(
            status_code=500,
            detail="Saved discovery settings could not be read. Try resetting advanced fields or contact support.",
        ) from None


class LoginBody(BaseModel):
    email: str
    password: str


class AuthMeResponse(BaseModel):
    email: str
    account_id: int
    auth_disabled: bool = False


class LoginResponse(BaseModel):
    email: str
    account_id: int


@app.post("/api/auth/login", response_model=LoginResponse)
def api_auth_login(request: Request, body: LoginBody) -> LoginResponse:
    if _auth_disabled():
        raise HTTPException(status_code=400, detail="Authentication is disabled on this server")
    _auth_rate_limit(
        request,
        prefix="login",
        max_events=int(os.environ.get("EVENTS_AUTH_LOGIN_MAX_ATTEMPTS", "25")),
        window_seconds=float(os.environ.get("EVENTS_AUTH_LOGIN_WINDOW_SECONDS", "300")),
    )
    with _auth_conn(request) as conn:
        user = _verify_user_password(request, conn, body.email, body.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    request.session["user_id"] = user["id"]
    return LoginResponse(email=user["email"], account_id=user["account_id"])


@app.post("/api/auth/signup", response_model=LoginResponse)
def api_auth_signup(request: Request, body: LoginBody) -> LoginResponse:
    if _auth_disabled():
        raise HTTPException(status_code=400, detail="Authentication is disabled on this server")
    _auth_rate_limit(
        request,
        prefix="signup",
        max_events=int(os.environ.get("EVENTS_AUTH_SIGNUP_MAX_ATTEMPTS", "10")),
        window_seconds=float(os.environ.get("EVENTS_AUTH_SIGNUP_WINDOW_SECONDS", "3600")),
    )
    if not _signup_allowed():
        raise HTTPException(status_code=403, detail="Sign up is not enabled on this server")
    plen = len(body.password)
    if plen < _SIGNUP_PASSWORD_MIN_LEN:
        raise HTTPException(
            status_code=422,
            detail=f"Password must be at least {_SIGNUP_PASSWORD_MIN_LEN} characters",
        )
    if plen > _SIGNUP_PASSWORD_MAX_LEN:
        raise HTTPException(
            status_code=422,
            detail=f"Password must be at most {_SIGNUP_PASSWORD_MAX_LEN} characters",
        )
    try:
        with _auth_conn(request) as conn:
            try:
                _account_id, user_id = _create_account_with_user(
                    request,
                    conn,
                    account_name=_default_account_name_from_email(body.email),
                    email=body.email,
                    password=body.password,
                )
            except ValueError as e:
                raise HTTPException(status_code=422, detail=str(e)) from e
            except sqlite3.IntegrityError:
                raise HTTPException(
                    status_code=409,
                    detail="An account with this email already exists",
                ) from None
            except Exception as e:
                if getattr(request.app.state, "use_postgres_auth", False):
                    from psycopg.errors import UniqueViolation

                    if isinstance(e, UniqueViolation):
                        raise HTTPException(
                            status_code=409,
                            detail="An account with this email already exists",
                        ) from None
                raise
    except HTTPException:
        raise
    request.session["user_id"] = user_id
    with _auth_conn(request) as conn2:
        row = _fetch_user_by_id(request, conn2, user_id)
    if row is None:
        raise HTTPException(status_code=500, detail="Sign up failed")
    return LoginResponse(email=row["email"], account_id=row["account_id"])


@app.post("/api/auth/logout")
def api_auth_logout(request: Request) -> dict[str, bool]:
    request.session.clear()
    return {"ok": True}


@app.get("/api/auth/me", response_model=AuthMeResponse)
def api_auth_me(request: Request) -> AuthMeResponse:
    if _auth_disabled():
        return AuthMeResponse(
            email="dev@local",
            account_id=1,
            auth_disabled=True,
        )
    user_id = request.session.get("user_id")
    if user_id is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    with _auth_conn(request) as conn:
        user = _fetch_user_by_id(request, conn, int(user_id))
    if user is None:
        request.session.clear()
        raise HTTPException(status_code=401, detail="Not authenticated")
    return AuthMeResponse(email=user["email"], account_id=user["account_id"])


@app.get("/api/config", response_model=WebConfig)
def api_config(user: Annotated[dict[str, Any], Depends(require_user)]) -> WebConfig:
    _ = user
    return WebConfig(
        read_only=os.environ.get("EVENTS_WEB_READ_ONLY", "").lower() in ("1", "true", "yes"),
        auth_disabled=_auth_disabled(),
        allow_signup=_signup_allowed() and not _auth_disabled(),
        advanced_ui=os.environ.get("EVENTS_UI_ADVANCED_MODE", "").lower()
        in ("1", "true", "yes"),
    )


class SignupStatusResponse(BaseModel):
    allowed: bool


@app.get("/api/auth/signup-status", response_model=SignupStatusResponse)
def api_auth_signup_status() -> SignupStatusResponse:
    return SignupStatusResponse(allowed=_signup_allowed() and not _auth_disabled())


@app.get("/api/events", response_model=EventsPage)
def api_list_events(
    conn: Annotated[Connection, Depends(get_db)],
    user: Annotated[dict[str, Any], Depends(require_user)],
    source: str | None = None,
    min_score: float | None = None,
    reviewed: bool | None = None,
    rejected: bool | None = None,
    q: str | None = None,
    start_from: str | None = None,
    start_to: str | None = None,
    website_id: int | None = None,
    sort: str = "relevance",
    order: str | None = None,
    include_past: bool = True,
    as_of: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> Any:
    _ = user
    lim = max(1, min(limit, 500))
    off = max(0, offset)
    sort_norm = sort if sort in _EVENT_SORT_KEYS else "relevance"
    order_norm = order if order in _EVENT_ORDER_VALUES else None
    as_of_norm = _normalize_events_as_of(as_of) if not include_past else None
    filters = EventListFilters(
        source=source,
        min_score=min_score,
        reviewed=reviewed,
        rejected=rejected,
        q=q,
        start_from=start_from,
        start_to=start_to,
        include_past=include_past,
        as_of_date=as_of_norm,
        website_id=website_id,
        sort=sort_norm,
        order=order_norm,
    )
    total = count_discovered_events(conn, filters)
    rows = list_discovered_events(conn, filters, limit=lim, offset=off)
    return EventsPage(
        events=[EventRow.model_validate(r) for r in rows],
        total=total,
        limit=lim,
        offset=off,
    )


@app.get("/api/sources", response_model=list[str])
def api_sources(
    conn: Annotated[Connection, Depends(get_db)],
    user: Annotated[dict[str, Any], Depends(require_user)],
) -> list[str]:
    _ = user
    return list_event_sources(conn)


@app.get("/api/discovery-settings", response_model=DiscoverySettingsResponse)
def api_discovery_settings_get(
    conn: Annotated[Connection, Depends(get_db_agent)],
    user: Annotated[dict[str, Any], Depends(require_user_or_agent_api)],
) -> DiscoverySettingsResponse:
    _ = user
    return _bundle_to_discovery_response(conn)


@app.patch("/api/discovery-settings", response_model=DiscoverySettingsResponse)
def api_discovery_settings_patch(
    request: Request,
    body: DiscoverySettingsPatch,
    conn: Annotated[Connection, Depends(get_db_agent)],
    user: Annotated[dict[str, Any], Depends(require_user_or_agent_api)],
) -> DiscoverySettingsResponse:
    _ = user
    _require_writes_allowed(request)
    defaults = _merged_yaml_config()
    bundle = get_discovery_settings_bundle(conn, defaults)

    if body.http is not None:
        if not isinstance(body.http, dict):
            raise HTTPException(status_code=422, detail="http must be an object")
        merged_h = {**bundle["http"], **body.http}
        http_try = {
            "user_agent": str(merged_h.get("user_agent") or "").strip(),
            "delay_seconds": float(merged_h.get("delay_seconds") or 0.75),
            "timeout_seconds": float(merged_h.get("timeout_seconds") or 45.0),
        }
        try:
            HttpSettingsBlock.model_validate(http_try)
        except Exception as e:
            raise HTTPException(status_code=422, detail=str(e)) from e

    if body.scoring is not None:
        if not isinstance(body.scoring, dict):
            raise HTTPException(status_code=422, detail="scoring must be an object")
        merged_s = {**bundle["scoring"], **body.scoring}
        sc_try = {
            "horizon_days": int(merged_s.get("horizon_days") or 120),
            "positive_keywords": _keyword_list_from_value(merged_s.get("positive_keywords")),
            "ward_keywords": _keyword_list_from_value(merged_s.get("ward_keywords")),
            "negative_keywords": _keyword_list_from_value(merged_s.get("negative_keywords")),
        }
        try:
            ScoringSettingsBlock.model_validate(sc_try)
        except Exception as e:
            raise HTTPException(status_code=422, detail=str(e)) from e

    if body.enrichment is not None:
        if not isinstance(body.enrichment, dict):
            raise HTTPException(status_code=422, detail="enrichment must be an object")
        merged_e = {**bundle["enrichment"], **body.enrichment}
        en_e = merged_e.get("enabled")
        if en_e is None:
            en_e = True
        try:
            max_u = int(
                merged_e.get("max_urls")
                if merged_e.get("max_urls") is not None
                else 100
            )
        except (TypeError, ValueError):
            max_u = 100
        en_try = {"enabled": bool(en_e), "max_urls": max(0, max_u)}
        try:
            EnrichmentSettingsBlock.model_validate(en_try)
        except Exception as e:
            raise HTTPException(status_code=422, detail=str(e)) from e

    patch_discovery_settings(
        conn,
        http=body.http,
        scoring=body.scoring,
        enrichment=body.enrichment,
        defaults_cfg=defaults,
    )
    return _bundle_to_discovery_response(conn)


@app.get("/api/website-source-types")
def api_website_source_types(
    user: Annotated[dict[str, Any], Depends(require_user_or_agent_api)],
) -> list[dict[str, Any]]:
    _ = user
    return website_source_types_payload()


@app.post("/api/source-discovery", response_model=SourceDiscoveryResponse)
def api_source_discovery(
    request: Request,
    body: SourceDiscoveryBody,
    user: Annotated[dict[str, Any], Depends(require_user_or_agent_api)],
) -> SourceDiscoveryResponse:
    _ = user
    _require_writes_allowed(request)
    sk = (body.source_key or "").strip() or None
    sl = (body.source_label or "").strip() or None
    try:
        out = discover_source_proposal(
            body.url.strip(),
            use_llm=body.use_llm,
            source_key=sk,
            source_label=sl,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:
        log.warning("source-discovery failed: %s", e)
        raise HTTPException(
            status_code=502,
            detail=f"Could not complete discovery: {e}",
        ) from e
    return SourceDiscoveryResponse.model_validate(out)


@app.post("/api/websites/quick-add", response_model=WebsiteQuickAddResponse)
def api_website_quick_add(
    request: Request,
    body: WebsiteQuickAddBody,
    conn: Annotated[Connection, Depends(get_db_agent)],
    user: Annotated[dict[str, Any], Depends(require_user_or_agent_api)],
) -> WebsiteQuickAddResponse:
    """
    Add a source from a display name and URL only: run discovery (rules, then optional AI),
    then insert a disabled website row ready for Re-check.
    """
    _ = user
    _require_writes_allowed(request)
    name = body.name.strip()
    url = body.url.strip()
    proposal: dict[str, Any] = {}
    try:
        proposal = discover_source_proposal(
            url,
            use_llm=body.use_llm,
            source_label=name,
        )
        site_type, cfg = pick_type_and_config_for_website(proposal)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:
        log.warning("quick-add discovery failed: %s", e)
        raise HTTPException(
            status_code=502,
            detail=f"Could not complete discovery: {e}",
        ) from e
    try:
        key = allocate_unique_source_key(conn, name)
        wid = create_website(
            conn,
            source_key=key,
            site_type=site_type,
            config=cfg,
            source_label=name,
            enabled=False,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    rows = list_websites(conn)
    for r in rows:
        if int(r["id"]) == wid:
            return WebsiteQuickAddResponse(
                website=WebsiteRow.model_validate(r),
                discovery=DiscoverySummaryBlock(
                    method=str(proposal.get("method") or "unknown"),
                    recommended_type=str(proposal.get("recommended_type") or "unknown"),
                    save_ready=bool(proposal.get("save_ready")),
                    evidence=list(proposal.get("evidence") or []),
                    caveats=list(proposal.get("caveats") or []),
                ),
            )
    raise HTTPException(status_code=500, detail="Could not load new source")


@app.get("/api/websites", response_model=list[WebsiteRow])
def api_list_websites(
    conn: Annotated[Connection, Depends(get_db_agent)],
    user: Annotated[dict[str, Any], Depends(require_user_or_agent_api)],
) -> list[WebsiteRow]:
    _ = user
    rows = list_websites(conn)
    return [WebsiteRow.model_validate(r) for r in rows]


@app.post("/api/websites", response_model=WebsiteRow)
def api_create_website(
    request: Request,
    body: WebsiteCreateBody,
    conn: Annotated[Connection, Depends(get_db_agent)],
    user: Annotated[dict[str, Any], Depends(require_user_or_agent_api)],
) -> WebsiteRow:
    _ = user
    _require_writes_allowed(request)
    try:
        validate_website_type_and_config(body.type, body.config)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    try:
        wid = create_website(
            conn,
            source_key=body.source_key,
            site_type=body.type,
            config=body.config,
            source_label=body.source_label,
            enabled=body.enabled,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    rows = list_websites(conn)
    for r in rows:
        if int(r["id"]) == wid:
            return WebsiteRow.model_validate(r)
    raise HTTPException(status_code=500, detail="Could not load new source")


@app.patch("/api/websites/bulk-enabled", response_model=list[WebsiteRow])
def api_websites_bulk_enabled(
    request: Request,
    body: WebsitesBulkEnabledBody,
    conn: Annotated[Connection, Depends(get_db_agent)],
    user: Annotated[dict[str, Any], Depends(require_user_or_agent_api)],
) -> list[WebsiteRow]:
    _ = user
    _require_writes_allowed(request)
    set_all_websites_enabled(conn, body.enabled)
    rows = list_websites(conn)
    return [WebsiteRow.model_validate(r) for r in rows]


@app.patch("/api/websites/{website_id}", response_model=WebsiteRow)
def api_patch_website(
    request: Request,
    website_id: int,
    body: WebsitePatch,
    conn: Annotated[Connection, Depends(get_db_agent)],
    user: Annotated[dict[str, Any], Depends(require_user_or_agent_api)],
) -> Any:
    _ = user
    _require_writes_allowed(request)
    if body.type is not None or body.config is not None:
        rows = list_websites(conn)
        site_row: dict[str, Any] | None = None
        for r in rows:
            if int(r["id"]) == website_id:
                site_row = r
                break
        if site_row is None:
            raise HTTPException(status_code=404, detail="Website not found")
        merged_type = body.type if body.type is not None else str(site_row["type"])
        merged_cfg = dict(site_row["config"])
        if body.config is not None:
            merged_cfg = {**merged_cfg, **body.config}
        try:
            validate_website_type_and_config(merged_type, merged_cfg)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
    if body.preferences is not None:
        if not isinstance(body.preferences, dict):
            raise HTTPException(status_code=422, detail="preferences must be an object")
        defaults = _merged_yaml_config()
        base = get_discovery_settings_bundle(conn, defaults)
        merged = merge_site_preferences_into_cfg(base, body.preferences)
        try:
            _bundle_dict_to_discovery_response(merged)
        except Exception as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
    try:
        ok = patch_website(
            conn,
            website_id,
            enabled=body.enabled,
            config=body.config,
            site_type=body.type,
            source_label=body.source_label,
            preferences=body.preferences,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not ok:
        raise HTTPException(status_code=404, detail="Website not found")
    rows = list_websites(conn)
    for r in rows:
        if int(r["id"]) == website_id:
            return WebsiteRow.model_validate(r)
    raise HTTPException(status_code=404, detail="Website not found")


@app.delete("/api/websites/{website_id}", response_model=WebsiteDeleteResponse)
def api_delete_website(
    request: Request,
    website_id: int,
    conn: Annotated[Connection, Depends(get_db_agent)],
    user: Annotated[dict[str, Any], Depends(require_user_or_agent_api)],
    delete_events: bool = False,
) -> WebsiteDeleteResponse:
    _ = user
    _require_writes_allowed(request)
    deleted, n = delete_website(conn, website_id, delete_events=delete_events)
    if not deleted:
        raise HTTPException(status_code=404, detail="Website not found")
    return WebsiteDeleteResponse(deleted=True, events_removed=n)


@app.put("/api/websites/reorder", response_model=list[WebsiteRow])
def api_reorder_websites(
    request: Request,
    body: WebsiteReorderBody,
    conn: Annotated[Connection, Depends(get_db_agent)],
    user: Annotated[dict[str, Any], Depends(require_user_or_agent_api)],
) -> Any:
    _ = user
    _require_writes_allowed(request)
    try:
        reorder_websites(conn, body.ids)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    rows = list_websites(conn)
    return [WebsiteRow.model_validate(r) for r in rows]


@app.post("/api/websites/{website_id}/test")
def api_test_website(
    request: Request,
    website_id: int,
    user: Annotated[dict[str, Any], Depends(require_user_or_agent_api)],
) -> dict[str, Any]:
    _ = user
    _require_writes_allowed(request)
    db_path = ensure_account_db_ready(request, int(user["account_id"]))
    conn = open_connection(db_path)
    try:
        row = fetch_website_source_for_crawl(conn, website_id)
    finally:
        conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Website not found")
    _, source_key, _, _ = row
    events = run(
        config_path=os.environ.get("EVENT_DISCOVERY_CONFIG"),
        output_dir=request.app.state.data_root,
        source_filter=None,
        dry_run=True,
        database_path=db_path,
        only_website_id=website_id,
    )
    sample = [
        {"title": e.title, "url": e.url, "source": e.source} for e in events[:12]
    ]
    return {
        "source_key": source_key,
        "event_count": len(events),
        "sample": sample,
        "note": "Dry run only — nothing was saved to your database.",
    }


@app.post("/api/crawl-jobs", status_code=202, response_model=CrawlJobAccepted)
def api_create_full_crawl_job(
    request: Request,
    body: CrawlJobCreateBody,
    conn: Annotated[Connection, Depends(get_db_crawl)],
    user: Annotated[dict[str, Any], Depends(require_user_or_crawl_api)],
) -> CrawlJobAccepted:
    _ = user
    _require_writes_allowed(request)
    if body.kind.strip().lower() != "full":
        raise HTTPException(status_code=422, detail='Only kind "full" is supported here')
    db_path = ensure_account_db_ready(request, int(user["account_id"]))
    job_id = insert_crawl_job(conn, kind="full", website_id=None)
    log.info(
        "Queued full crawl job_id=%s account_id=%s",
        job_id,
        int(user["account_id"]),
    )
    start_crawl_job(
        account_id=int(user["account_id"]),
        db_path=db_path,
        data_root=request.app.state.data_root,
        job_id=job_id,
        kind="full",
        website_id=None,
    )
    return CrawlJobAccepted(job_id=job_id)


@app.get("/api/crawl-jobs", response_model=list[CrawlJobRow])
def api_list_crawl_jobs(
    conn: Annotated[Connection, Depends(get_db_crawl)],
    user: Annotated[dict[str, Any], Depends(require_user_or_crawl_api)],
    limit: int = 30,
) -> list[CrawlJobRow]:
    _ = user
    rows = list_crawl_jobs(conn, limit=limit)
    out: list[CrawlJobRow] = []
    for r in rows:
        raw = r.get("summary_json") or "{}"
        try:
            summary = json.loads(raw) if isinstance(raw, str) else {}
        except json.JSONDecodeError:
            summary = {}
        if not isinstance(summary, dict):
            summary = {}
        out.append(
            CrawlJobRow(
                id=int(r["id"]),
                kind=str(r["kind"]),
                website_id=r.get("website_id"),
                status=str(r["status"]),
                created_at=r.get("created_at"),
                started_at=r.get("started_at"),
                finished_at=r.get("finished_at"),
                event_count=r.get("event_count"),
                error_message=r.get("error_message"),
                summary=summary,
            )
        )
    return out


@app.get("/api/crawl-jobs/{job_id}", response_model=CrawlJobRow)
def api_get_crawl_job(
    job_id: int,
    conn: Annotated[Connection, Depends(get_db_crawl)],
    user: Annotated[dict[str, Any], Depends(require_user_or_crawl_api)],
) -> CrawlJobRow:
    _ = user
    r = get_crawl_job(conn, job_id)
    if r is None:
        raise HTTPException(status_code=404, detail="Job not found")
    raw = r.get("summary_json") or "{}"
    try:
        summary = json.loads(raw) if isinstance(raw, str) else {}
    except json.JSONDecodeError:
        summary = {}
    if not isinstance(summary, dict):
        summary = {}
    return CrawlJobRow(
        id=int(r["id"]),
        kind=str(r["kind"]),
        website_id=r.get("website_id"),
        status=str(r["status"]),
        created_at=r.get("created_at"),
        started_at=r.get("started_at"),
        finished_at=r.get("finished_at"),
        event_count=r.get("event_count"),
        error_message=r.get("error_message"),
        summary=summary,
    )


@app.post(
    "/api/websites/{website_id}/recheck",
    status_code=202,
    response_model=CrawlJobAccepted,
)
def api_recheck_website(
    request: Request,
    website_id: int,
    conn: Annotated[Connection, Depends(get_db_crawl)],
    user: Annotated[dict[str, Any], Depends(require_user_or_crawl_api)],
) -> CrawlJobAccepted:
    _require_writes_allowed(request)
    db_path = ensure_account_db_ready(request, int(user["account_id"]))
    row = fetch_website_source_for_crawl(conn, website_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Website not found")
    try:
        job_id = insert_crawl_job(conn, kind="recheck", website_id=website_id)
    except sqlite3.IntegrityError as e:
        raise HTTPException(
            status_code=404,
            detail="Website not found or invalid for crawl job",
        ) from e
    log.info(
        "Queued recheck job_id=%s account_id=%s website_id=%s",
        job_id,
        int(user["account_id"]),
        website_id,
    )
    start_crawl_job(
        account_id=int(user["account_id"]),
        db_path=db_path,
        data_root=request.app.state.data_root,
        job_id=job_id,
        kind="recheck",
        website_id=website_id,
    )
    return CrawlJobAccepted(job_id=job_id)


@app.patch("/api/events/{event_id}/review", response_model=ReviewState)
def api_patch_review(
    request: Request,
    event_id: int,
    body: ReviewPatch,
    conn: Annotated[Connection, Depends(get_db)],
    user: Annotated[dict[str, Any], Depends(require_user)],
) -> Any:
    _ = user
    _require_writes_allowed(request)
    result = update_event_review(
        conn,
        event_id,
        reviewed=body.reviewed,
        rejected=body.rejected,
        notes=body.notes,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return ReviewState.model_validate(result)


from .automation_api import register_automation_routes

register_automation_routes(app)


if STATIC_DIR.is_dir():
    app.mount(
        "/assets",
        StaticFiles(directory=str(STATIC_DIR / "assets")),
        name="assets",
    )


@app.get("/login")
def login_page():
    page = STATIC_DIR / "login.html"
    if not page.is_file():
        raise HTTPException(
            status_code=503,
            detail="Login page not found (expected static/login.html).",
        )
    return FileResponse(page)


@app.get("/signup")
def signup_page():
    page = STATIC_DIR / "signup.html"
    if not page.is_file():
        raise HTTPException(
            status_code=503,
            detail="Sign up page not found (expected static/signup.html).",
        )
    return FileResponse(page)


@app.get("/")
def spa_index():
    index = STATIC_DIR / "index.html"
    if not index.is_file():
        raise HTTPException(
            status_code=503,
            detail="Static UI not found (expected static/index.html next to web.py).",
        )
    return FileResponse(index)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    port = int(os.environ.get("PORT", os.environ.get("EVENTS_WEB_PORT", "8000")))
    uvicorn.run(app, host="0.0.0.0", port=port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
