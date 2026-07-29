from __future__ import annotations

from collections.abc import Iterable

from app.models.locator import (
    CompiledLocatorIndex,
    PageRetrievalStep,
    SectionLocator,
)
from app.models.manifest import (
    BookManifest,
    LearningUnitManifest,
    ManifestRetrievalStep,
    PrintedSectionManifest,
)


class LocatorIndexCompiler:
    """Compile an ordered, reviewed manifest into the strict runtime index.

    Project learning-unit ids are generated only here. The manifest cannot provide
    them, so sibling order and tree depth are the sole numbering inputs.
    """

    def compile(self, manifest: BookManifest) -> CompiledLocatorIndex:
        sections: dict[str, SectionLocator] = {}
        printed_ids = {item.printed_section_id for item in manifest.printed_sections}

        for printed in manifest.printed_sections:
            locator = self._compile_printed_section(manifest, printed)
            self._insert_unique(sections, locator)

        for printed in manifest.printed_sections:
            self._validate_sibling_order(printed.learning_units)
            for ordinal, unit in enumerate(printed.learning_units, start=1):
                section_id = f"{printed.printed_section_id}.{ordinal}"
                self._compile_learning_unit_tree(
                    manifest=manifest,
                    printed=printed,
                    unit=unit,
                    section_id=section_id,
                    parent_section_id=printed.printed_section_id,
                    expected_source_level=1,
                    sections=sections,
                    printed_ids=printed_ids,
                )

        return CompiledLocatorIndex(
            data_version="3",
            index_status="complete",
            book=manifest.book,
            pages=manifest.pages,
            page_classifications=manifest.page_classifications,
            sections=sections,
        )

    def _compile_printed_section(
        self,
        manifest: BookManifest,
        printed: PrintedSectionManifest,
    ) -> SectionLocator:
        return SectionLocator(
            data_version="3",
            book_id=manifest.book.book_id,
            section_kind="printed",
            section_id=printed.printed_section_id,
            printed_section_id=printed.printed_section_id,
            parent_section_id=printed.parent_printed_section_id,
            title=printed.title,
            source_heading=printed.source_heading,
            source_heading_numbered=True,
            source_location=printed.source_location,
            source_level=0,
            hierarchy_depth=len(printed.printed_section_id.split(".")),
            page_range=printed.page_range,
            outline=printed.outline,
            retrieval_plan=self._compile_plan(printed.retrieval_plan),
        )

    def _compile_learning_unit_tree(
        self,
        *,
        manifest: BookManifest,
        printed: PrintedSectionManifest,
        unit: LearningUnitManifest,
        section_id: str,
        parent_section_id: str,
        expected_source_level: int,
        sections: dict[str, SectionLocator],
        printed_ids: set[str],
    ) -> None:
        if unit.source_level != expected_source_level:
            raise ValueError(
                f"learning unit {unit.title!r} has source_level={unit.source_level}; "
                f"expected {expected_source_level}"
            )
        if section_id in printed_ids:
            raise ValueError(
                f"generated learning-unit id {section_id} conflicts with a printed section id"
            )

        locator = SectionLocator(
            data_version="3",
            book_id=manifest.book.book_id,
            section_kind="learning_unit",
            section_id=section_id,
            printed_section_id=printed.printed_section_id,
            parent_section_id=parent_section_id,
            title=unit.title,
            source_heading=unit.source_heading,
            source_heading_numbered=False,
            source_location=unit.source_location,
            source_level=unit.source_level,
            hierarchy_depth=len(section_id.split(".")),
            page_range=unit.page_range,
            outline=unit.outline,
            retrieval_plan=self._compile_plan(unit.retrieval_plan),
        )
        self._insert_unique(sections, locator)

        self._validate_sibling_order(unit.children)
        for ordinal, child in enumerate(unit.children, start=1):
            self._compile_learning_unit_tree(
                manifest=manifest,
                printed=printed,
                unit=child,
                section_id=f"{section_id}.{ordinal}",
                parent_section_id=section_id,
                expected_source_level=expected_source_level + 1,
                sections=sections,
                printed_ids=printed_ids,
            )

    @staticmethod
    def _compile_plan(
        source_steps: list[ManifestRetrievalStep],
    ) -> list[PageRetrievalStep]:
        steps: list[PageRetrievalStep] = []
        total = len(source_steps)
        for index, step in enumerate(source_steps):
            if total == 1:
                role = "single"
            elif index == 0:
                role = "start"
            elif index == total - 1:
                role = "end"
            else:
                role = "body"
            steps.append(
                PageRetrievalStep(
                    sequence=index + 1,
                    page_role=role,
                    page=step.page,
                    content_window=step.content_window,
                    queries=step.queries,
                    required_evidence=step.required_evidence,
                    coverage=step.coverage,
                )
            )
        return steps

    @staticmethod
    def _insert_unique(sections: dict[str, SectionLocator], locator: SectionLocator) -> None:
        if locator.section_id in sections:
            raise ValueError(f"duplicate compiled section id: {locator.section_id}")
        sections[locator.section_id] = locator

    @staticmethod
    def _validate_sibling_order(units: Iterable[LearningUnitManifest]) -> None:
        previous: tuple[int, float, float] | None = None
        for unit in units:
            x0, y0, _x1, _y1 = unit.source_location.bbox
            current = (unit.source_location.page.pdf_page_index, y0, x0)
            if previous is not None and current < previous:
                raise ValueError("learning-unit siblings are not in PDF appearance order")
            previous = current
