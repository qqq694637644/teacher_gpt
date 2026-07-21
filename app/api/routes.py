from fastapi import APIRouter, Depends, Request

from app.core.security import require_api_key
from app.models.locator import ErrorResponse, HealthResponse, SectionLocator
from app.services.locator_service import LocatorService

router = APIRouter()


def locator_service(request: Request) -> LocatorService:
    return LocatorService(request.app.state.locator_repository)


@router.get(
    "/health",
    response_model=HealthResponse,
    tags=["system"],
    operation_id="healthCheck",
)
async def health(service: LocatorService = Depends(locator_service)) -> HealthResponse:
    return service.health()


@router.get(
    "/gpt/section-locators/{section_id}",
    response_model=SectionLocator,
    responses={404: {"model": ErrorResponse, "description": "Section id does not exist."}},
    tags=["gpt"],
    dependencies=[Depends(require_api_key)],
    operation_id="gptGetSectionLocator",
)
async def get_section_locator(
    section_id: str,
    service: LocatorService = Depends(locator_service),
) -> SectionLocator:
    return service.get_section(section_id)
