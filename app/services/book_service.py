from app.models.schemas import BookMeta, TocItem, TocResponse
from app.services.storage import JsonStore


class BookService:
    def __init__(self, store: JsonStore | None = None):
        self.store = store or JsonStore()

    def list_books(self) -> list[BookMeta]:
        return [BookMeta(**item) for item in self.store.list_books()]

    def get_meta(self, book_id: str) -> BookMeta:
        return BookMeta(**self.store.load_json(book_id, "book_meta.json"))

    def get_toc(self, book_id: str) -> TocResponse:
        meta = self.get_meta(book_id)
        toc = self.store.load_json(book_id, "toc.json", default={"items": []})
        return TocResponse(
            book_id=book_id,
            title=meta.title,
            items=[self._to_toc_item(item) for item in toc.get("items", [])],
        )

    @staticmethod
    def _to_toc_item(item: dict) -> TocItem:
        return TocItem(
            section_id=item["section_id"],
            title=item.get("title") or "",
            level=item.get("level") or 1,
            page_start=item.get("page_start"),
            page_end=item.get("page_end"),
            children=[],
        )
