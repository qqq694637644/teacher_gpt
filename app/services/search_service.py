from __future__ import annotations

from app.models.schemas import PrerequisitesResponse, SearchResponse, SearchResult, SectionPack
from app.services.section_service import SectionService
from app.services.storage import JsonStore
from app.utils.text import compact_snippet, lexical_score


class SearchService:
    def __init__(self, store: JsonStore | None = None, sections: SectionService | None = None):
        self.store = store or JsonStore()
        self.sections = sections or SectionService(self.store)

    def search(self, book_id: str, query: str, limit: int = 8) -> SearchResponse:
        section_map = self.sections.get_raw_section_map(book_id)
        results: list[SearchResult] = []
        for section_id, meta in section_map.items():
            try:
                raw_pack = self.store.load_json(book_id, f"section_packs/{section_id}.json")
            except FileNotFoundError:
                continue
            pack = SectionPack.model_validate(raw_pack)
            text = "\n".join(block.text for block in pack.text_blocks)
            title = meta.get("title") or pack.title or section_id
            score = lexical_score(query, title, text)
            if score <= 0:
                continue
            results.append(
                SearchResult(
                    section_id=section_id,
                    title=title,
                    page_start=meta.get("page_start"),
                    page_end=meta.get("page_end"),
                    score=score,
                    snippet=compact_snippet(text, query),
                )
            )
        results.sort(key=lambda item: item.score, reverse=True)
        return SearchResponse(book_id=book_id, query=query, results=results[:limit])

    def prerequisites(self, book_id: str, section_id: str, limit: int = 5) -> PrerequisitesResponse:
        resolved, _ = self.sections.resolve_section_id(book_id, section_id)
        section_map = self.sections.get_raw_section_map(book_id)
        meta = section_map.get(resolved, {})
        prereq_ids = meta.get("prerequisites", [])[:limit]
        results: list[SearchResult] = []
        for sid in prereq_ids:
            item = section_map.get(sid)
            if not item:
                continue
            results.append(
                SearchResult(
                    section_id=sid,
                    title=item.get("title") or sid,
                    page_start=item.get("page_start"),
                    page_end=item.get("page_end"),
                    score=1.0,
                    snippet=None,
                )
            )
        return PrerequisitesResponse(book_id=book_id, section_id=section_id, prerequisites=results)
