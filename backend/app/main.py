"""FastAPI application: `uvicorn app.main:app`."""

import logging
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router
from core.config import get_settings

logger = logging.getLogger("app")

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


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="SignalForge AI API", version="0.1.0", description=DESCRIPTION)
    # Middleware added last runs first, so CORS wraps the error handler.
    app.middleware("http")(catch_unhandled_errors)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET"],
        allow_headers=["*"],
    )
    app.include_router(router)

    @app.get("/", include_in_schema=False)
    def root() -> dict[str, str]:
        return {"name": "SignalForge AI API", "docs": "/docs", "health": "/health"}

    return app


app = create_app()
