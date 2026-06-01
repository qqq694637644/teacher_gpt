import json
from pathlib import Path
from typing import Any

from app.core.config import Settings, get_settings
from app.core.errors import BookNotFoundError


class JsonStore:
    """Small JSON/file based storage layer.

    This is intentionally simple for MVP deployments. It can be replaced by
    PostgreSQL + object storage later without changing the external API shape.
    """

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def book_dir(self, book_id: str) -> Path:
        return self.settings.books_dir / self._safe_id(book_id)

    def ensure_book_dir(self, book_id: str) -> Path:
        path = self.book_dir(book_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def require_book_dir(self, book_id: str) -> Path:
        path = self.book_dir(book_id)
        if not path.exists():
            raise BookNotFoundError(f"Book not found: {book_id}")
        return path

    def load_json(self, book_id: str, relative_path: str, default: Any | None = None) -> Any:
        path = self.require_book_dir(book_id) / relative_path
        if not path.exists():
            if default is not None:
                return default
            raise FileNotFoundError(str(path))
        return json.loads(path.read_text(encoding="utf-8"))

    def save_json(self, book_id: str, relative_path: str, data: Any) -> Path:
        path = self.ensure_book_dir(book_id) / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def list_books(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        self.settings.books_dir.mkdir(parents=True, exist_ok=True)
        for path in sorted(self.settings.books_dir.iterdir()):
            if not path.is_dir():
                continue
            meta_path = path / "book_meta.json"
            if meta_path.exists():
                try:
                    result.append(json.loads(meta_path.read_text(encoding="utf-8")))
                except json.JSONDecodeError:
                    result.append({"book_id": path.name, "title": None})
            else:
                result.append({"book_id": path.name, "title": None})
        return result

    @staticmethod
    def _safe_id(value: str) -> str:
        value = value.strip().replace("/", "_").replace("\\", "_")
        if not value or value in {".", ".."}:
            raise ValueError("Invalid id")
        return value
