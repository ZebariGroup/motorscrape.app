import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.api.deps import AccessContext, get_access_context
from app.api.routes_auth import router as auth_router
from app.api.routes_billing import router as billing_router
from app.api.search_quota import evaluate_search_start, record_search_completed
from app.config import settings
from app.db.account_store import get_account_store
from app.services.orchestrator import stream_search
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
    vehicle_condition: Literal["all", "new", "used"] = Query("all"),
    radius_miles: int = Query(default=25, ge=5, le=250),
    inventory_scope: str = Query("all"),
    max_dealerships: int | None = Query(default=None, ge=1, le=30),
    max_pages_per_dealer: int | None = Query(
        default=None,
        ge=1,
        le=20,
    ),
) -> StreamingResponse:
    store = get_account_store(settings.accounts_db_path)
    quota = evaluate_search_start(ctx, store)
    if not quota.allowed:

        async def denied() -> AsyncIterator[bytes]:
            yield sse_pack("search_error", {"message": quota.message, "phase": "quota"}).encode("utf-8")
            yield sse_pack("done", {"ok": False}).encode("utf-8")

        return StreamingResponse(
            denied(),
            media_type="text/event-stream",
            headers=_SSE_HEADERS,
        )

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

    async def body() -> AsyncIterator[bytes]:
        try:
            async for chunk in stream_search(
                location=location,
                make=make.strip(),
                model=model.strip(),
                vehicle_condition=vehicle_condition,
                radius_miles=eff_radius,
                inventory_scope=eff_inventory_scope,
                max_dealerships=eff_max_d,
                max_pages_per_dealer=eff_pages,
                outcome_holder=outcome,
            ):
                yield chunk.encode("utf-8")
        finally:
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


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
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
    ],
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(billing_router)

# Mount twice so the same deployment works locally (/health) and on Vercel Services
# whether the platform forwards the `/server` prefix or strips it to root paths.
app.include_router(router)
app.include_router(router, prefix="/server")
app.include_router(auth_router, prefix="/server")
app.include_router(billing_router, prefix="/server")
