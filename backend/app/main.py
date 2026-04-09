import asyncio
import logging
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse

from app.api.deps import AccessContext, get_access_context
from app.api.routes_admin import router as admin_router
from app.api.routes_alerts import router as alerts_router
from app.api.routes_auth import router as auth_router
from app.api.routes_billing import router as billing_router
from app.api.routes_saved_searches import router as saved_searches_router
from app.api.routes_search_logs import router as search_logs_router
from app.api.search_quota import evaluate_search_start, record_search_completed
from app.config import settings, vehicle_category_enabled
from app.db.account_store import get_account_store
from app.services.active_searches import cancel_active_search, register_active_search, unregister_active_search
from app.services.orchestrator import stream_search
from app.services.search_errors import SearchErrorInfo, with_search_error
from app.services.scrape_logging import build_correlation_id, create_scrape_run_recorder
from app.sse import sse_pack, stream_with_keepalive

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


@router.get("/search/stream")
async def search_stream(
    ctx: Annotated[AccessContext, Depends(get_access_context)],
    location: str = Query(..., min_length=2),
    make: str = Query(""),
    model: str = Query(""),
    correlation_id: str | None = Query(default=None, min_length=6, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"),
    vehicle_category: Literal["car", "motorcycle", "boat", "other"] = Query("car"),
    vehicle_condition: Literal["all", "new", "used"] = Query("all"),
    radius_miles: int = Query(default=25, ge=5, le=250),
    inventory_scope: str = Query("all"),
    prefer_small_dealers: bool = Query(default=False),
    max_dealerships: int | None = Query(default=None, ge=1, le=20),
    max_pages_per_dealer: int | None = Query(
        default=None,
        ge=1,
        le=50,
    ),
    market_region: Literal["us", "eu"] = Query(default="us"),
) -> StreamingResponse:
    if not vehicle_category_enabled(vehicle_category):
        raise HTTPException(status_code=400, detail=f"Vehicle category '{vehicle_category}' is not enabled.")
    lim = ctx.limits
    eff_radius = min(radius_miles, lim.max_radius_miles)
    base_max_d = max_dealerships if max_dealerships is not None else lim.max_dealerships
    eff_max_d = max(1, min(base_max_d, lim.max_dealerships))
    base_pages = max_pages_per_dealer if max_pages_per_dealer is not None else lim.max_pages_per_dealer
    eff_pages = max(1, min(base_pages, lim.max_pages_per_dealer))
    eff_inventory_scope = inventory_scope
    if not lim.inventory_scope_premium:
        eff_inventory_scope = "all"

    outcome: dict = {}
    store = get_account_store(settings.accounts_db_path)
    correlation_id = correlation_id or build_correlation_id()
    existing_run = store.get_scrape_run(correlation_id, user_id=ctx.user_id, anon_key=ctx.anon_key)
    if existing_run is not None and existing_run.status == "running":
        logger.warning("Duplicate search stream prevented for correlation_id=%s", correlation_id)
        # Tell EventSource clients to stop retrying this duplicate stream request.
        return Response(status_code=204)
    close_stale = getattr(store, "close_stale_running_scrape_runs", None)
    if callable(close_stale):
        stale_closed = close_stale(
            user_id=ctx.user_id,
            anon_key=ctx.anon_key,
            started_before_ts=time.time() - max(30, int(settings.search_startup_stale_seconds or 0)),
        )
        if stale_closed:
            logger.warning(
                "Closed %s stale startup scrape run(s) before concurrency check user_id=%s anon=%s",
                stale_closed,
                ctx.user_id,
                bool(ctx.anon_key),
            )
    running_count = store.count_running_scrape_runs(
        user_id=ctx.user_id,
        anon_key=ctx.anon_key,
        since_ts=time.time() - max(60, int(settings.search_running_window_seconds or 0)),
    )
    if running_count >= max(1, int(lim.max_concurrent_searches)):
        error = SearchErrorInfo(
            code="quota.concurrent_searches",
            message="Too many searches are already running for this account. Wait for one to finish and try again.",
            phase="quota",
            status="concurrency_blocked",
            retryable=True,
        ).with_correlation_id(correlation_id)

        async def concurrency_denied() -> AsyncIterator[bytes]:
            yield sse_pack("search_error", error.to_payload()).encode("utf-8")
            yield sse_pack(
                "done",
                {
                    "ok": False,
                    "status": "concurrency_blocked",
                    "correlation_id": correlation_id,
                    "error": error.to_summary(),
                    "error_message": error.message,
                    "error_code": error.code,
                },
            ).encode("utf-8")

        return StreamingResponse(
            concurrency_denied(),
            status_code=429,
            media_type="text/event-stream",
            headers=_SSE_HEADERS,
        )
    recorder = create_scrape_run_recorder(
        store=store,
        correlation_id=correlation_id,
        trigger_source="interactive",
        location=location,
        make=make.strip(),
        model=model.strip(),
        vehicle_category=vehicle_category,
        vehicle_condition=vehicle_condition,
        inventory_scope=eff_inventory_scope,
        prefer_small_dealers=prefer_small_dealers,
        radius_miles=eff_radius,
        requested_max_dealerships=eff_max_d,
        requested_max_pages_per_dealer=eff_pages,
        user_id=ctx.user_id,
        anon_key=ctx.anon_key,
    )
    quota = evaluate_search_start(ctx, store)
    if not quota.allowed:
        quota_error = (quota.error or SearchErrorInfo(code="quota.unknown", message=quota.message, phase="quota")).with_correlation_id(
            correlation_id
        )
        recorder.event(
            event_type="quota_blocked",
            phase="quota",
            level="warning",
            message=quota_error.message,
            payload={"error": quota_error.to_summary()},
        )
        recorder.finalize(
            ok=False,
            status="quota_blocked",
            summary=with_search_error(
                {
                    "ok": False,
                    "status": "quota_blocked",
                    "correlation_id": correlation_id,
                },
                quota_error,
            ),
            economics={},
            error_message=quota_error.message,
        )

        async def denied() -> AsyncIterator[bytes]:
            yield sse_pack("search_error", quota_error.to_payload()).encode("utf-8")
            yield sse_pack(
                "done",
                with_search_error(
                    {
                        "ok": False,
                        "status": "quota_blocked",
                        "correlation_id": correlation_id,
                    },
                    quota_error,
                ),
            ).encode("utf-8")

        return StreamingResponse(
            denied(),
            media_type="text/event-stream",
            headers=_SSE_HEADERS,
        )

    async def body() -> AsyncIterator[bytes]:
        current_task = asyncio.current_task()
        if current_task is not None:
            register_active_search(correlation_id, current_task)
        try:
            async for chunk in stream_with_keepalive(
                stream_search(
                    location=location,
                    make=make.strip(),
                    model=model.strip(),
                    vehicle_category=vehicle_category,
                    vehicle_condition=vehicle_condition,
                    radius_miles=eff_radius,
                    inventory_scope=eff_inventory_scope,
                    prefer_small_dealers=prefer_small_dealers,
                    max_dealerships=eff_max_d,
                    max_pages_per_dealer=eff_pages,
                    outcome_holder=outcome,
                    correlation_id=correlation_id,
                    recorder=recorder,
                    market_region=market_region,
                ),
                interval_s=20.0,
            ):
                yield chunk.encode("utf-8")
        except asyncio.CancelledError:
            if not recorder.finalized:
                canceled_error = SearchErrorInfo(
                    code="search.canceled",
                    message="Search canceled by user.",
                    phase="http",
                    status="canceled",
                )
                recorder.event(
                    event_type="search_canceled",
                    phase="http",
                    level="warning",
                    message=canceled_error.message,
                    payload={"correlation_id": correlation_id, "error": canceled_error.to_summary()},
                )
                recorder.finalize(
                    ok=False,
                    status="canceled",
                    summary=with_search_error(
                        {
                            "ok": False,
                            "status": "canceled",
                            "correlation_id": correlation_id,
                        },
                        canceled_error,
                    ),
                    economics={},
                    error_message=canceled_error.message,
                )
            raise
        finally:
            if current_task is not None:
                unregister_active_search(correlation_id, current_task)
            if not recorder.finalized:
                stream_closed_error = SearchErrorInfo(
                    code="stream.closed_before_completion",
                    message="Search stream closed before completion.",
                    phase="http",
                )
                recorder.event(
                    event_type="stream_closed",
                    phase="http",
                    level="warning",
                    message="Search stream closed before scraper finalized.",
                    payload={"error": stream_closed_error.to_summary()},
                )
                recorder.finalize(
                    ok=False,
                    status="failed",
                    summary=with_search_error(
                        {
                            "ok": False,
                            "status": "failed",
                            "correlation_id": correlation_id,
                        },
                        stream_closed_error,
                    ),
                    economics={},
                    error_message=stream_closed_error.message,
                )
            record_search_completed(
                ctx,
                outcome,
                counts_as_overage=quota.counts_as_overage,
                store=store,
            )

    return StreamingResponse(
        body(),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@router.get("/vehicles/premium-report")
async def get_premium_report(
    vin: str,
    ctx: Annotated[AccessContext, Depends(get_access_context)],
) -> dict:
    from app.services.marketcheck import fetch_premium_report
    
    if ctx.limits.included_premium_reports_per_month <= 0:
        raise HTTPException(
            status_code=403, 
            detail="Premium reports require a paid subscription. Please upgrade to Starter, Pro, or Max Pro."
        )
        
    # TODO: Add strict metered counting against included_premium_reports_per_month
        
    report = await fetch_premium_report(vin)
    if report is None:
        raise HTTPException(status_code=404, detail="No premium history found for this VIN.")
        
    return {"ok": True, "vin": vin, "history": report}

@router.post("/search/stop/{correlation_id}")
async def stop_search(
    correlation_id: str,
    ctx: Annotated[AccessContext, Depends(get_access_context)],
) -> dict[str, object]:
    store = get_account_store(settings.accounts_db_path)
    run = store.get_scrape_run(correlation_id, user_id=ctx.user_id, anon_key=ctx.anon_key)
    if run is None:
        raise HTTPException(status_code=404, detail="Search run not found.")
    return {
        "ok": True,
        "correlation_id": correlation_id,
        "stopped": cancel_active_search(correlation_id),
    }


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if os.environ.get("VERCEL_ENV") == "production" and not settings.session_secret:
        logger.warning("SESSION_SECRET is not set in production! Sessions and anon keys will use a weak default.")
    if os.environ.get("VERCEL_ENV") and settings.accounts_db_path.startswith("/tmp/") and not (
        settings.supabase_url and settings.supabase_service_key
    ):
        logger.warning(
            "accounts_db_path is using ephemeral /tmp storage without Supabase configured. "
            "Search logs, quotas, and saved state will be instance-local on Vercel."
        )
    yield
    try:
        from app.services.scraper import close_scraper_http_clients

        await close_scraper_http_clients()
    except Exception:
        pass
    try:
        from app.services.parser.monolith import close_openai_client

        await close_openai_client()
    except Exception:
        pass
    try:
        from app.services.playwright_fetch import shutdown_playwright

        await shutdown_playwright()
    except Exception:
        pass
    try:
        from app.services.vin_decoder import close_vin_decoder_http_client

        await close_vin_decoder_http_client()
    except Exception:
        pass
app = FastAPI(title="Motorscrape API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://motorscrape.app",
        "https://www.motorscrape.app",
    ],
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(billing_router)
app.include_router(alerts_router)
app.include_router(saved_searches_router)
app.include_router(search_logs_router)

# Mount twice so the same deployment works locally (/health) and on Vercel Services
# whether the platform forwards the `/server` prefix or strips it to root paths.
app.include_router(router)
app.include_router(router, prefix="/server")
app.include_router(auth_router, prefix="/server")
app.include_router(admin_router, prefix="/server")
app.include_router(billing_router, prefix="/server")
app.include_router(alerts_router, prefix="/server")
app.include_router(saved_searches_router, prefix="/server")
app.include_router(search_logs_router, prefix="/server")
