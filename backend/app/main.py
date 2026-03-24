import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.services.orchestrator import stream_search

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/search/stream")
async def search_stream(
    location: str = Query(..., min_length=2),
    make: str = Query(""),
    model: str = Query(""),
    coverage_mode: str = Query("standard"),
    inventory_scope: str = Query("all"),
    max_dealerships: int | None = Query(default=None, ge=1, le=30),
    max_pages_per_dealer: int | None = Query(default=None, ge=1, le=5),
) -> StreamingResponse:
    async def body() -> AsyncIterator[bytes]:
        async for chunk in stream_search(
            location=location,
            make=make.strip(),
            model=model.strip(),
            coverage_mode=coverage_mode,
            inventory_scope=inventory_scope,
            max_dealerships=max_dealerships,
            max_pages_per_dealer=max_pages_per_dealer,
        ):
            yield chunk.encode("utf-8")

    return StreamingResponse(
        body(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


app = FastAPI(title="Motorscrape API", version="0.1.0")

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

# Mount twice so the same deployment works locally (/health) and on Vercel Services
# whether the platform forwards the `/server` prefix or strips it to root paths.
app.include_router(router)
app.include_router(router, prefix="/server")
