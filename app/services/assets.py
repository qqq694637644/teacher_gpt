from pathlib import Path

from fastapi import HTTPException, status

from app.core.config import Settings, get_settings
from app.services.storage import JsonStore


class AssetService:
    def __init__(self, settings: Settings | None = None, store: JsonStore | None = None):
        self.settings = settings or get_settings()
        self.store = store or JsonStore(self.settings)

    def page_image_url(self, book_id: str, page_number: int) -> str | None:
        record = self.page_record(book_id, page_number)
        rel = record.get("image_path") if record else None
        if not rel:
            return None
        filename = Path(rel).name
        return self.settings.make_public_url(f"/assets/books/{book_id}/pages/{filename}")

    def figure_image_url(self, book_id: str, image_path: str | None) -> str | None:
        if not image_path:
            return None
        filename = Path(image_path).name
        return self.settings.make_public_url(f"/assets/books/{book_id}/figures/{filename}")

    def page_record(self, book_id: str, page_number: int) -> dict | None:
        pages = self.store.load_json(book_id, "page_text.json", default={"pages": []}).get("pages", [])
        if page_number < 1 or page_number > len(pages):
            return None
        return pages[page_number - 1]

    def resolve_asset_path(self, book_id: str, kind: str, filename: str) -> Path:
        if kind not in {"pages", "figures"}:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset kind not found.")
        if "/" in filename or "\\" in filename or filename in {".", ".."}:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid filename.")
        path = self.store.require_book_dir(book_id) / kind / filename
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found.")
        return path
