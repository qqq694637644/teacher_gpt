from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse

from app.api.routes import router
from app.core.errors import (
    BookNotFoundError,
    DataVersionError,
    FigureNotFoundError,
    SectionNotFoundError,
)
from app.core.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Teaching GPT Backend",
        version="0.1.0",
        description=(
            "Backend API for one-textbook-per-GPT teaching assistants. "
            "Use /gpt/* endpoints for a single-book GPT Action, or /books/{book_id}/* for multi-book use."
        ),
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)

    @app.exception_handler(BookNotFoundError)
    async def book_not_found_handler(request: Request, exc: BookNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(SectionNotFoundError)
    async def section_not_found_handler(request: Request, exc: SectionNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": f"Section not found: {exc}"})

    @app.exception_handler(FigureNotFoundError)
    async def figure_not_found_handler(request: Request, exc: FigureNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": f"Figure not found: {exc}"})

    @app.exception_handler(DataVersionError)
    async def data_version_handler(request: Request, exc: DataVersionError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.get("/", include_in_schema=False)
    async def root() -> RedirectResponse:
        return RedirectResponse(url="/docs")

    return app


app = create_app()
