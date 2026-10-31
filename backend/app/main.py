"""FastAPI application: `uvicorn app.main:app`."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from core.config import get_settings

DESCRIPTION = (
    "Read-only API for SignalForge AI, a research prototype that turns daily news into "
    "scored stock signals and tracks how they perform. Not investment advice."
)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="SignalForge AI API", version="0.1.0", description=DESCRIPTION)
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
