from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request

from app.core.security import require_api_key
from app.models.exercise import (
    CHAPTER_ID_PATTERN,
    EXERCISE_ID_PATTERN,
    ChapterExerciseSummary,
    ExerciseLocator,
)
from app.models.locator import (
    ExerciseCatalogUnavailableResponse,
    ExerciseNotFoundResponse,
    HealthResponse,
    SectionLocator,
    SectionNotFoundResponse,
)
from app.services.locator_service import LocatorService

router = APIRouter()


def locator_service(request: Request) -> LocatorService:
    return LocatorService(
        request.app.state.locator_repository,
        getattr(request.app.state, "exercise_repository", None),
    )


@router.get(
    "/health",
    response_model=HealthResponse,
    tags=["system"],
    operation_id="healthCheck",
)
async def health(
    service: Annotated[LocatorService, Depends(locator_service)],
) -> HealthResponse:
    return service.health()


@router.get(
    "/gpt/section-locators/{section_id}",
    response_model=SectionLocator,
    responses={
        404: {"model": SectionNotFoundResponse, "description": "Section id does not exist."}
    },
    tags=["gpt"],
    dependencies=[Depends(require_api_key)],
    operation_id="gptGetSectionLocator",
)
async def get_section_locator(
    section_id: str,
    service: Annotated[LocatorService, Depends(locator_service)],
) -> SectionLocator:
    return service.get_section(section_id)


@router.get(
    "/gpt/exercise-locators/{exercise_id}",
    response_model=ExerciseLocator,
    responses={
        404: {
            "model": ExerciseNotFoundResponse,
            "description": "Exercise id does not exist.",
        },
        503: {
            "model": ExerciseCatalogUnavailableResponse,
            "description": "Exercise catalog has not been configured.",
        },
    },
    tags=["gpt"],
    dependencies=[Depends(require_api_key)],
    operation_id="gptGetExerciseLocator",
)
async def get_exercise_locator(
    exercise_id: Annotated[str, Path(pattern=EXERCISE_ID_PATTERN)],
    service: Annotated[LocatorService, Depends(locator_service)],
) -> ExerciseLocator:
    return service.get_exercise(exercise_id)


@router.get(
    "/gpt/chapters/{chapter_id}/exercises",
    response_model=ChapterExerciseSummary,
    responses={
        404: {
            "model": ExerciseNotFoundResponse,
            "description": "Chapter has no exercise catalog entry.",
        },
        503: {
            "model": ExerciseCatalogUnavailableResponse,
            "description": "Exercise catalog has not been configured.",
        },
    },
    tags=["gpt"],
    dependencies=[Depends(require_api_key)],
    operation_id="gptListChapterExercises",
)
async def list_chapter_exercises(
    chapter_id: Annotated[str, Path(pattern=CHAPTER_ID_PATTERN)],
    service: Annotated[LocatorService, Depends(locator_service)],
) -> ChapterExerciseSummary:
    return service.list_chapter_exercises(chapter_id)
