from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.core.errors import SectionNotFoundError
from app.models.schemas import SectionPack
from app.services.storage import JsonStore


class SectionService:
    def __init__(self, store: JsonStore | None = None):
        self.store = store or JsonStore()

    def resolve_section_id(self, book_id: str, section_id: str) -> tuple[str, bool]:
        aliases = self.store.load_json(book_id, "section_aliases.json", default={})
        if section_id in aliases:
            return str(aliases[section_id]), True
        return section_id, False

    def get_section(
        self,
        book_id: str,
        section_id: str,
        *,
        text_offset: int = 0,
        text_limit: int | None = None,
    ) -> SectionPack:
        resolved_id, was_alias = self.resolve_section_id(book_id, section_id)
        try:
            raw = self.store.load_json(book_id, f"section_packs/{resolved_id}.json")
        except FileNotFoundError as exc:
            raise SectionNotFoundError(section_id) from exc
        pack_data = deepcopy(raw)
        pack_data["resolved_section_id"] = resolved_id
        if was_alias:
            pack_data["section_id"] = section_id
            pack_data["section_type"] = "alias"
            pack_data.setdefault("warnings", []).append(
                f"Section id {section_id} is configured as an alias of {resolved_id}."
            )
        self._apply_text_window(pack_data, text_offset=text_offset, text_limit=text_limit)
        return SectionPack(**pack_data)

    def get_raw_section_map(self, book_id: str) -> dict:
        return self.store.load_json(book_id, "section_map.json", default={})

    def _apply_text_window(
        self,
        pack: dict[str, Any],
        *,
        text_offset: int,
        text_limit: int | None,
    ) -> None:
        text_blocks = pack.get("text_blocks", [])
        total_chars = self._text_blocks_len(text_blocks)
        safe_offset = min(max(text_offset, 0), total_chars)

        if text_limit is None:
            returned_chars = max(0, total_chars - safe_offset)
            next_offset = None
            is_truncated = safe_offset > 0
            sliced_blocks = self._slice_text_blocks(text_blocks, safe_offset, returned_chars)
        else:
            safe_limit = max(text_limit, 1)
            returned_chars = min(safe_limit, max(0, total_chars - safe_offset))
            next_offset = safe_offset + returned_chars if safe_offset + returned_chars < total_chars else None
            is_truncated = next_offset is not None or safe_offset > 0
            sliced_blocks = self._slice_text_blocks(text_blocks, safe_offset, returned_chars)

        pack["text_blocks"] = sliced_blocks
        pack["content"] = {
            "content_status": "partial" if is_truncated else "complete",
            "is_truncated": is_truncated,
            "text_offset": safe_offset,
            "text_limit": text_limit,
            "total_chars": total_chars,
            "returned_chars": returned_chars,
            "next_offset": next_offset,
        }

        if is_truncated:
            if next_offset is not None:
                warning = f"This section text is partial. Use text_offset={next_offset} to continue."
            else:
                warning = (
                    f"This section text starts at text_offset={safe_offset}; earlier text was omitted."
                )
            pack.setdefault("warnings", []).append(warning)

    @staticmethod
    def _text_blocks_len(text_blocks: list[dict[str, Any]]) -> int:
        return sum(len(str(block.get("text") or "")) for block in text_blocks)

    @staticmethod
    def _slice_text_blocks(
        text_blocks: list[dict[str, Any]],
        text_offset: int,
        text_limit: int,
    ) -> list[dict[str, Any]]:
        if text_limit <= 0:
            return []
        result: list[dict[str, Any]] = []
        cursor = 0
        remaining = text_limit
        for block in text_blocks:
            text = str(block.get("text") or "")
            block_start = cursor
            block_end = cursor + len(text)
            cursor = block_end
            if block_end <= text_offset:
                continue
            if block_start >= text_offset + text_limit:
                break
            local_start = max(0, text_offset - block_start)
            take = min(len(text) - local_start, remaining)
            if take <= 0:
                continue
            sliced = deepcopy(block)
            sliced["text"] = text[local_start : local_start + take]
            result.append(sliced)
            remaining -= take
            if remaining <= 0:
                break
        return result

