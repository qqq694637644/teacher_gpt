from pathlib import Path
from tempfile import NamedTemporaryFile

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from app.core.config import Settings, get_settings
from app.core.errors import BookNotFoundError, FigureNotFoundError, SectionNotFoundError
from app.core.security import require_api_key
from app.models.schemas import (
    BookMeta,
    FigureResponse,
    HealthResponse,
    IngestResponse,
    PrerequisitesResponse,
    SearchResponse,
    SectionPack,
    TocResponse,
)
from app.services.book_service import BookService
from app.services.figure_service import FigureService
from app.services.pdf_ingestor import PDFIngestor
from app.services.search_service import SearchService
from app.services.section_service import SectionService

router = APIRouter()


def book_service() -> BookService:
    return BookService()


def section_service() -> SectionService:
    return SectionService()


def figure_service() -> FigureService:
    return FigureService()


def search_service() -> SearchService:
    return SearchService()


@router.get("/health", response_model=HealthResponse, tags=["system"], operation_id="healthCheck")
async def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    return HealthResponse(default_book_id=settings.default_book_id)


@router.get(
    "/books",
    response_model=list[BookMeta],
    tags=["books"],
    dependencies=[Depends(require_api_key)],
    operation_id="listBooks",
)
async def list_books(service: BookService = Depends(book_service)) -> list[BookMeta]:
    return service.list_books()


@router.get(
    "/books/{book_id}/toc",
    response_model=TocResponse,
    tags=["books"],
    dependencies=[Depends(require_api_key)],
    operation_id="getTableOfContents",
)
async def get_toc(book_id: str, service: BookService = Depends(book_service)) -> TocResponse:
    try:
        return service.get_toc(book_id)
    except BookNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get(
    "/books/{book_id}/sections/{section_id}",
    response_model=SectionPack,
    tags=["sections"],
    dependencies=[Depends(require_api_key)],
    operation_id="getSection",
)
async def get_section(
    book_id: str,
    section_id: str,
    text_offset: int = Query(
        default=0,
        ge=0,
        description="Character offset into section text_blocks for continuing a long section.",
    ),
    text_limit: int | None = Query(
        default=None,
        ge=1,
        le=50000,
        description="Maximum section text characters to return. Omit for the full stored section.",
    ),
    service: SectionService = Depends(section_service),
) -> SectionPack:
    try:
        return service.get_section(
            book_id,
            section_id,
            text_offset=text_offset,
            text_limit=text_limit,
        )
    except BookNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SectionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Section not found: {section_id}",
        ) from exc


@router.get(
    "/books/{book_id}/figures/{figure_id}",
    response_model=FigureResponse,
    tags=["figures"],
    dependencies=[Depends(require_api_key)],
    operation_id="getFigure",
)
async def get_figure(
    book_id: str,
    figure_id: str,
    service: FigureService = Depends(figure_service),
) -> FigureResponse:
    try:
        return service.get_figure(book_id, figure_id)
    except BookNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except FigureNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Figure not found: {figure_id}",
        ) from exc


@router.get(
    "/books/{book_id}/search",
    response_model=SearchResponse,
    tags=["search"],
    dependencies=[Depends(require_api_key)],
    operation_id="searchBook",
)
async def search_book(
    book_id: str,
    q: str = Query(min_length=1, description="Concept, section title, or keyword to search in the book."),
    limit: int = Query(default=8, ge=1, le=20),
    service: SearchService = Depends(search_service),
) -> SearchResponse:
    try:
        return service.search(book_id, q, limit=limit)
    except BookNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get(
    "/books/{book_id}/sections/{section_id}/prerequisites",
    response_model=PrerequisitesResponse,
    tags=["sections"],
    dependencies=[Depends(require_api_key)],
    operation_id="getPrerequisites",
)
async def get_prerequisites(
    book_id: str,
    section_id: str,
    limit: int = Query(default=5, ge=1, le=10),
    service: SearchService = Depends(search_service),
) -> PrerequisitesResponse:
    try:
        return service.prerequisites(book_id, section_id, limit=limit)
    except BookNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


# One-book endpoints for one-textbook-per-GPT deployments.
# These keep the Action schema simpler: the GPT does not need to pass book_id.
@router.get(
    "/gpt/toc",
    response_model=TocResponse,
    tags=["gpt-one-book"],
    dependencies=[Depends(require_api_key)],
    operation_id="gptGetTableOfContents",
)
async def gpt_get_toc(
    settings: Settings = Depends(get_settings),
    service: BookService = Depends(book_service),
) -> TocResponse:
    return service.get_toc(settings.default_book_id)


@router.get(
    "/gpt/sections/{section_id}",
    response_model=SectionPack,
    tags=["gpt-one-book"],
    dependencies=[Depends(require_api_key)],
    operation_id="gptGetSection",
)
async def gpt_get_section(
    section_id: str,
    text_offset: int = Query(
        default=0,
        ge=0,
        description="Character offset into section text_blocks for continuing a long section.",
    ),
    text_limit: int = Query(
        default=12000,
        ge=1,
        le=50000,
        description="Maximum section text characters to return. Use content.next_offset to continue.",
    ),
    settings: Settings = Depends(get_settings),
    service: SectionService = Depends(section_service),
) -> SectionPack:
    return service.get_section(
        settings.default_book_id,
        section_id,
        text_offset=text_offset,
        text_limit=text_limit,
    )


@router.get(
    "/gpt/figures/{figure_id}",
    response_model=FigureResponse,
    tags=["gpt-one-book"],
    dependencies=[Depends(require_api_key)],
    operation_id="gptGetFigure",
)
async def gpt_get_figure(
    figure_id: str,
    settings: Settings = Depends(get_settings),
    service: FigureService = Depends(figure_service),
) -> FigureResponse:
    return service.get_figure(settings.default_book_id, figure_id)


@router.get(
    "/gpt/search",
    response_model=SearchResponse,
    tags=["gpt-one-book"],
    dependencies=[Depends(require_api_key)],
    operation_id="gptSearchBook",
)
async def gpt_search(
    q: str = Query(min_length=1),
    limit: int = Query(default=8, ge=1, le=20),
    settings: Settings = Depends(get_settings),
    service: SearchService = Depends(search_service),
) -> SearchResponse:
    return service.search(settings.default_book_id, q, limit=limit)


@router.get(
    "/gpt/sections/{section_id}/prerequisites",
    response_model=PrerequisitesResponse,
    tags=["gpt-one-book"],
    dependencies=[Depends(require_api_key)],
    operation_id="gptGetPrerequisites",
)
async def gpt_get_prerequisites(
    section_id: str,
    limit: int = Query(default=5, ge=1, le=10),
    settings: Settings = Depends(get_settings),
    service: SearchService = Depends(search_service),
) -> PrerequisitesResponse:
    return service.prerequisites(settings.default_book_id, section_id, limit=limit)


@router.post(
    "/admin/books/upload",
    response_model=IngestResponse,
    tags=["admin"],
    dependencies=[Depends(require_api_key)],
    operation_id="uploadAndIngestBook",
)
async def upload_and_ingest_book(
    book_id: str = Query(description="Stable id, e.g. dip4e"),
    title: str | None = Query(default=None),
    author: str | None = Query(default=None),
    overwrite: bool = Query(default=False),
    file: UploadFile = File(...),
) -> IngestResponse:
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only PDF files are supported.")
    with NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp_path = Path(tmp.name)
        while chunk := await file.read(1024 * 1024):
            tmp.write(chunk)
    try:
        result = PDFIngestor().ingest(
            book_id=book_id,
            pdf_path=tmp_path,
            title=title,
            author=author,
            overwrite=overwrite,
        )
        return IngestResponse(**result)
    finally:
        tmp_path.unlink(missing_ok=True)
