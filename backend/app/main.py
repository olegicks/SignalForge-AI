"""FastAPI application: `uvicorn app.main:app`."""

import logging
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from app.api.ask import router as ask_router
from app.api.routes import router
from core.config import get_settings

logger = logging.getLogger("app")

CACHE_MAX_AGE_SECONDS = 300

DESCRIPTION = (
    "Read-only API for SignalForge AI, a research prototype that turns daily news into "
    "scored stock signals and tracks how they perform. Not investment advice."
)


async def catch_unhandled_errors(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Turn crashes into a JSON 500 *inside* the CORS middleware.

    Starlette's own 500 handler sits outside every middleware, so its responses have no CORS
    headers and the browser reports them as a network failure instead of a server error.
    """
    try:
        return await call_next(request)
    except Exception:
        logger.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})


async def add_cache_headers(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Data changes once a day, so let browsers and CDNs reuse successful reads briefly."""
    response = await call_next(request)
    if request.method == "GET" and response.status_code == 200 and request.url.path != "/health":
        response.headers.setdefault("Cache-Control", f"public, max-age={CACHE_MAX_AGE_SECONDS}")
    return response


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="SignalForge AI API", version="0.1.0", description=DESCRIPTION)
    # Middleware added last runs first, so CORS wraps everything, including the error handler.
    app.middleware("http")(catch_unhandled_errors)
    app.middleware("http")(add_cache_headers)
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    # POST is allowed for POST /ask, the only write endpoint; every other route only has GET
    # handlers, so POST to them still gets 405 (tested in test_ask.py).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    app.include_router(router)
    app.include_router(ask_router)

    @app.get("/", include_in_schema=False)
    def root() -> dict[str, str]:
        return {"name": "SignalForge AI API", "docs": "/docs", "health": "/health"}

    return app


app = create_app()
