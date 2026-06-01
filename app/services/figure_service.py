from copy import deepcopy

from app.core.errors import FigureNotFoundError
from app.models.schemas import FigureResponse
from app.services.assets import AssetService
from app.services.storage import JsonStore


class FigureService:
    def __init__(self, store: JsonStore | None = None, assets: AssetService | None = None):
        self.store = store or JsonStore()
        self.assets = assets or AssetService(store=self.store)

    def get_figure(self, book_id: str, figure_id: str) -> FigureResponse:
        normalized = self._normalize_figure_id(figure_id)
        figure_map = self.store.load_json(book_id, "figure_map.json", default={})
        if normalized not in figure_map:
            raise FigureNotFoundError(figure_id)
        data = deepcopy(figure_map[normalized])
        page_number = data.get("page_number")
        if page_number:
            data["page_image_url"] = self.assets.page_image_url(book_id, int(page_number))
        data["image_url"] = self.assets.figure_image_url(book_id, data.get("image_path"))
        data["book_id"] = book_id
        return FigureResponse(**data)

    @staticmethod
    def _normalize_figure_id(value: str) -> str:
        return value.strip().replace("Figure", "").replace("FIGURE", "").replace("Fig.", "").replace("Fig", "").strip()
