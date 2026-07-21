from copy import deepcopy

from app.core.errors import FigureNotFoundError
from app.models.schemas import FigureResponse
from app.services.storage import JsonStore


class FigureService:
    def __init__(self, store: JsonStore | None = None):
        self.store = store or JsonStore()

    def get_figure(self, book_id: str, figure_id: str) -> FigureResponse:
        normalized = self._normalize_figure_id(figure_id)
        figure_map = self.store.load_json(book_id, "figure_map.json", default={})
        if normalized not in figure_map:
            raise FigureNotFoundError(figure_id)
        data = deepcopy(figure_map[normalized])
        data["book_id"] = book_id
        return FigureResponse(**data)

    @staticmethod
    def _normalize_figure_id(value: str) -> str:
        return value.strip().replace("Figure", "").replace("FIGURE", "").replace("Fig.", "").replace("Fig", "").strip()
