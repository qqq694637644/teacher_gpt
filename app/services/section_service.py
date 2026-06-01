from __future__ import annotations

from copy import deepcopy

from app.core.errors import SectionNotFoundError
from app.models.schemas import SectionPack, SourcePage
from app.services.assets import AssetService
from app.services.storage import JsonStore


class SectionService:
    def __init__(self, store: JsonStore | None = None, assets: AssetService | None = None):
        self.store = store or JsonStore()
        self.assets = assets or AssetService(store=self.store)

    def resolve_section_id(self, book_id: str, section_id: str) -> tuple[str, bool]:
        aliases = self.store.load_json(book_id, "section_aliases.json", default={})
        if section_id in aliases:
            return str(aliases[section_id]), True
        return section_id, False

    def get_section(self, book_id: str, section_id: str) -> SectionPack:
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
        self._enrich_urls(book_id, pack_data)
        return SectionPack(**pack_data)

    def get_raw_section_map(self, book_id: str) -> dict:
        return self.store.load_json(book_id, "section_map.json", default={})

    def _enrich_urls(self, book_id: str, pack: dict) -> None:
        source_pages = []
        for page in pack.get("source_pages", []):
            page_number = int(page.get("page_number") or 0)
            source_pages.append(
                SourcePage(
                    page_index=page_number - 1,
                    page_number=page_number,
                    image_url=self.assets.page_image_url(book_id, page_number),
                ).model_dump()
            )
        pack["source_pages"] = source_pages
        for fig in pack.get("figures", []):
            page_number = fig.get("page_number")
            if page_number:
                fig["page_image_url"] = self.assets.page_image_url(book_id, int(page_number))
            fig["image_url"] = self.assets.figure_image_url(book_id, fig.get("image_path"))
