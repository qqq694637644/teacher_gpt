from app.models.locator import HealthResponse, SectionLocator
from app.repositories.locator_repository import LocatorRepository


class LocatorService:
    def __init__(self, repository: LocatorRepository):
        self.repository = repository

    def health(self) -> HealthResponse:
        index = self.repository.index
        return HealthResponse(
            book_id=index.book.book_id,
            section_count=len(index.sections),
            page_count=index.book.page_count,
        )

    def get_section(self, section_id: str) -> SectionLocator:
        return self.repository.get_section(section_id)
