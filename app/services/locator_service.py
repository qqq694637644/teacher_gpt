from app.core.errors import ExerciseCatalogUnavailableError
from app.models.exercise import ChapterExerciseSummary, ExerciseLocator
from app.models.locator import HealthResponse, SectionLocator
from app.repositories.exercise_repository import ExerciseRepository
from app.repositories.locator_repository import LocatorRepository


class LocatorService:
    def __init__(
        self,
        repository: LocatorRepository,
        exercise_repository: ExerciseRepository | None = None,
    ):
        self.repository = repository
        self.exercise_repository = exercise_repository

    def health(self) -> HealthResponse:
        index = self.repository.index
        return HealthResponse(
            book_id=index.book.book_id,
            section_count=len(index.sections),
            page_count=index.book.page_count,
            exercise_catalog_status=(
                "ready" if self.exercise_repository is not None else "not_configured"
            ),
            exercise_count=(
                len(self.exercise_repository.index.exercises)
                if self.exercise_repository is not None
                else 0
            ),
        )

    def get_section(self, section_id: str) -> SectionLocator:
        return self.repository.get_section(section_id)

    def get_exercise(self, exercise_id: str) -> ExerciseLocator:
        return self._exercise_repository().get_exercise(exercise_id)

    def list_chapter_exercises(self, chapter_id: str) -> ChapterExerciseSummary:
        return self._exercise_repository().list_chapter(chapter_id)

    def _exercise_repository(self) -> ExerciseRepository:
        if self.exercise_repository is None:
            raise ExerciseCatalogUnavailableError
        return self.exercise_repository
