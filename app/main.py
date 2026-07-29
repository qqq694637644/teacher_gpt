import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse

from app.api.routes import router
from app.core.config import Settings, get_settings
from app.core.errors import SectionNotFoundError
from app.core.security import api_key_fingerprint
from app.repositories.locator_repository import LocatorRepository

logger = logging.getLogger("uvicorn.error")


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = resolved_settings
        env_file_path = Path(".env").resolve()
        logger.info(
            "API auth configuration: require_api_key=%s api_key_loaded=%s "
            "api_key_is_default=%s api_key_length=%s api_key=%s "
            "api_key_fingerprint=%s "
            "env_file=%s env_file_exists=%s",
            resolved_settings.require_api_key,
            bool(resolved_settings.api_key),
            resolved_settings.api_key == "change-me",
            len(resolved_settings.api_key),
            resolved_settings.api_key,
            api_key_fingerprint(resolved_settings.api_key),
            env_file_path,
            env_file_path.is_file(),
        )
        app.state.locator_repository = LocatorRepository.load(resolved_settings.locator_index_path)
        yield

    app = FastAPI(
        title="Teacher GPT Locator API",
        version="3.0.0",
        description=(
            "Strict one-book GPT Action API. It returns page-by-page retrieval plans "
            "for the original PDF and never returns textbook content."
        ),
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["GET"],
        allow_headers=["Authorization", "X-API-Key", "Content-Type"],
    )
    app.include_router(router)

    @app.exception_handler(SectionNotFoundError)
    async def section_not_found_handler(
        request: Request, exc: SectionNotFoundError
    ) -> JSONResponse:
        section_id = exc.args[0] if exc.args else ""
        return JSONResponse(
            status_code=404,
            content={
                "error_code": "SECTION_NOT_FOUND",
                "detail": f"Section id does not exist: {section_id}",
            },
        )

    @app.get("/", include_in_schema=False)
    async def root() -> RedirectResponse:
        return RedirectResponse(url="/docs")

    return app


app = create_app()
