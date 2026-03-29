import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.api.deps import AccessContext, get_access_context
from app.api.routes_admin import router as admin_router
from app.api.routes_alerts import router as alerts_router
from app.api.routes_auth import router as auth_router
from app.api.routes_billing import router as billing_router
from app.api.routes_search_logs import router as search_logs_router
from app.api.search_quota import evaluate_search_start, record_search_completed
from app.config import settings, vehicle_category_enabled
from app.db.account_store import get_account_store
from app.services.active_searches import cancel_active_search, register_active_search, unregister_active_search
from app.services.orchestrator import stream_search
from app.services.scrape_logging import build_correlation_id, create_scrape_run_recorder
from app.sse import sse_pack

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
    max_dealerships: int | None = Query(default=None, ge=1, le=30),
    max_pages_per_dealer: int | None = Query(
        default=None,
        ge=1,
        le=50,
    ),
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
        radius_miles=eff_radius,
        requested_max_dealerships=eff_max_d,
        requested_max_pages_per_dealer=eff_pages,
        user_id=ctx.user_id,
        anon_key=ctx.anon_key,
    )
    quota = evaluate_search_start(ctx, store)
    if not quota.allowed:
        recorder.event(
            event_type="quota_blocked",
            phase="quota",
            level="warning",
            message=quota.message,
            payload={},
        )
        recorder.finalize(
            ok=False,
            status="quota_blocked",
            summary={
                "ok": False,
                "status": "quota_blocked",
                "correlation_id": correlation_id,
                "error_message": quota.message,
            },
            economics={},
            error_message=quota.message,
        )

        async def denied() -> AsyncIterator[bytes]:
            yield sse_pack("search_error", {"message": quota.message, "phase": "quota", "correlation_id": correlation_id}).encode("utf-8")
            yield sse_pack("done", {"ok": False, "status": "quota_blocked", "correlation_id": correlation_id}).encode(
                "utf-8"
            )

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
            async for chunk in stream_search(
                location=location,
                make=make.strip(),
                model=model.strip(),
                vehicle_category=vehicle_category,
                vehicle_condition=vehicle_condition,
                radius_miles=eff_radius,
                inventory_scope=eff_inventory_scope,
                max_dealerships=eff_max_d,
                max_pages_per_dealer=eff_pages,
                outcome_holder=outcome,
                correlation_id=correlation_id,
                recorder=recorder,
            ):
                yield chunk.encode("utf-8")
        except asyncio.CancelledError:
            if not recorder.finalized:
                recorder.event(
                    event_type="search_canceled",
                    phase="http",
                    level="warning",
                    message="Search canceled by user.",
                    payload={"correlation_id": correlation_id},
                )
                recorder.finalize(
                    ok=False,
                    status="canceled",
                    summary={
                        "ok": False,
                        "status": "canceled",
                        "correlation_id": correlation_id,
                        "error_message": "Search canceled by user.",
                    },
                    economics={},
                    error_message="Search canceled by user.",
                )
            raise
        finally:
            if current_task is not None:
                unregister_active_search(correlation_id, current_task)
            if not recorder.finalized:
                recorder.event(
                    event_type="stream_closed",
                    phase="http",
                    level="warning",
                    message="Search stream closed before scraper finalized.",
                    payload={},
                )
                recorder.finalize(
                    ok=False,
                    status="failed",
                    summary={
                        "ok": False,
                        "status": "failed",
                        "correlation_id": correlation_id,
                        "error_message": "Search stream closed before completion.",
                    },
                    economics={},
                    error_message="Search stream closed before completion.",
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
app.include_router(search_logs_router)

# Mount twice so the same deployment works locally (/health) and on Vercel Services
# whether the platform forwards the `/server` prefix or strips it to root paths.
app.include_router(router)
app.include_router(router, prefix="/server")
app.include_router(auth_router, prefix="/server")
app.include_router(admin_router, prefix="/server")
app.include_router(billing_router, prefix="/server")
app.include_router(alerts_router, prefix="/server")
app.include_router(search_logs_router, prefix="/server")
