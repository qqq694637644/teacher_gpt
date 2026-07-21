from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from app.core.errors import LocatorIndexLoadError, SectionNotFoundError
from app.models.locator import CompiledLocatorIndex, SectionLocator


class LocatorRepository:
    def __init__(self, index: CompiledLocatorIndex):
        self.index = index

    @classmethod
    def load(cls, path: Path) -> LocatorRepository:
        if not path.is_file():
            raise LocatorIndexLoadError(f"Compiled locator index not found: {path}")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LocatorIndexLoadError(f"Cannot read compiled locator index: {path}") from exc
        try:
            index = CompiledLocatorIndex.model_validate(raw)
        except ValidationError as exc:
            raise LocatorIndexLoadError(f"Compiled locator index is invalid: {exc}") from exc
        return cls(index)

    def get_section(self, section_id: str) -> SectionLocator:
        try:
            return self.index.sections[section_id]
        except KeyError as exc:
            raise SectionNotFoundError(section_id) from exc
