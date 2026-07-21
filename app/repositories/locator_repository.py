from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from app.core.errors import LocatorIndexLoadError, SectionNotFoundError
from app.models.locator import (
    CompiledLocatorIndex,
    CompiledLocatorIndexPackage,
    LocatorSectionShard,
    SectionLocator,
)


class LocatorRepository:
    def __init__(self, index: CompiledLocatorIndex):
        self.index = index

    @classmethod
    def load(cls, path: Path) -> LocatorRepository:
        if not path.is_file():
            raise LocatorIndexLoadError(f"Compiled locator index not found: {path}")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if "section_shards" in raw:
                package = CompiledLocatorIndexPackage.model_validate(raw)
                sections: dict[str, SectionLocator] = {}
                for shard_name in package.section_shards:
                    shard_path = path.parent / shard_name
                    shard_raw = json.loads(shard_path.read_text(encoding="utf-8"))
                    shard = LocatorSectionShard.model_validate(shard_raw)
                    duplicates = sections.keys() & shard.sections.keys()
                    if duplicates:
                        raise ValueError(
                            f"duplicate section IDs across shards: {sorted(duplicates)}"
                        )
                    sections.update(shard.sections)
                raw = {
                    **package.model_dump(mode="json", exclude={"section_shards"}),
                    "sections": {
                        section_id: locator.model_dump(mode="json")
                        for section_id, locator in sections.items()
                    },
                }
            index = CompiledLocatorIndex.model_validate(raw)
        except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
            raise LocatorIndexLoadError(f"Compiled locator index is invalid: {exc}") from exc
        return cls(index)

    def get_section(self, section_id: str) -> SectionLocator:
        try:
            return self.index.sections[section_id]
        except KeyError as exc:
            raise SectionNotFoundError(section_id) from exc
