from __future__ import annotations

from app.models.exercise import (
    ChapterExerciseSummary,
    CompiledExerciseIndex,
    ExerciseLocator,
    ExerciseReferenceTarget,
)
from app.models.exercise_manifest import (
    ExerciseManifest,
    ExerciseManifestNode,
    ExerciseReferenceSpec,
)
from app.models.locator import (
    BookMetadata,
    BoundaryAnchor,
    ContentWindow,
    EvidenceRequirement,
    HeadingLocation,
    PageClassification,
    PageCoverage,
    PageRange,
    PageReference,
    PageRetrievalStep,
)
from app.models.manifest import (
    BookManifest,
    LearningUnitManifest,
    ManifestRetrievalStep,
    PrintedSectionManifest,
)

PAGES = [
    PageReference(
        pdf_page_index=index, pdf_page_number=index + 1, printed_page_label=str(98 + index)
    )
    for index in range(4)
]


def page_range(start: int, end: int) -> PageRange:
    return PageRange(
        pdf_page_index_start=start,
        pdf_page_index_end=end,
        pdf_page_number_start=start + 1,
        pdf_page_number_end=end + 1,
        printed_page_start=PAGES[start].printed_page_label,
        printed_page_end=PAGES[end].printed_page_label,
    )


def step(index: int, *, heading: str = "Heading") -> ManifestRetrievalStep:
    page = PAGES[index]
    return ManifestRetrievalStep(
        page=page,
        content_window=ContentWindow(),
        queries=[
            f"+({heading}) +(printed page {page.printed_page_label}) --QDF=0",
            f"{heading} page {page.printed_page_label} --QDF=0",
        ],
        required_evidence=[
            EvidenceRequirement(
                kind="printed_page_equals",
                value=page.printed_page_label,
                verification_mode="visual_required",
            ),
            EvidenceRequirement(
                kind="contains_heading",
                value=heading,
                verification_mode="visual_required",
            ),
        ],
        coverage=PageCoverage(subheadings=[heading]),
    )


def _with_boundaries(units: list[LearningUnitManifest]) -> list[LearningUnitManifest]:
    linked: list[LearningUnitManifest] = []
    for index, unit_item in enumerate(units):
        next_item = units[index + 1] if index + 1 < len(units) else None
        steps = list(unit_item.retrieval_plan)

        first_raw = steps[0].model_dump(mode="json")
        first_raw["content_window"]["start_at"] = {
            "kind": "heading",
            "value": unit_item.source_heading,
        }
        steps[0] = ManifestRetrievalStep.model_validate(first_raw)

        if (
            next_item is not None
            and unit_item.page_range.pdf_page_index_end == next_item.page_range.pdf_page_index_start
        ):
            last_raw = steps[-1].model_dump(mode="json")
            last_raw["content_window"]["end_before"] = {
                "kind": "heading",
                "value": next_item.source_heading,
            }
            last_raw["required_evidence"].append(
                {
                    "kind": "contains_heading",
                    "value": next_item.source_heading,
                    "verification_mode": "visual_required",
                }
            )
            steps[-1] = ManifestRetrievalStep.model_validate(last_raw)

        linked.append(
            unit_item.model_copy(
                update={
                    "retrieval_plan": steps,
                    "children": _with_boundaries(list(unit_item.children)),
                }
            )
        )
    return linked


def unit(
    title: str,
    index: int,
    *,
    source_level: int = 1,
    children: list[LearningUnitManifest] | None = None,
    y: float = 100.0,
    end_index: int | None = None,
) -> LearningUnitManifest:
    end = index if end_index is None else end_index
    return LearningUnitManifest(
        title=title,
        source_heading=title,
        source_location=HeadingLocation(
            page=PAGES[index],
            bbox=(120.0, y, 320.0, y + 12.0),
        ),
        source_level=source_level,
        page_range=page_range(index, end),
        outline=[],
        retrieval_plan=[step(page_index, heading=title) for page_index in range(index, end + 1)],
        children=children or [],
    )


def complete_manifest() -> BookManifest:
    set_children = [
        unit("Basic Set Operations", 1, source_level=2, y=210.0),
        unit("Logical Operations", 1, source_level=2, y=310.0),
    ]
    spatial_children = [
        unit("Single-Pixel Operations", 2, source_level=2, y=110.0),
        unit("Neighborhood Operations", 2, source_level=2, y=210.0),
        unit("Geometric Transformations", 2, source_level=2, y=310.0),
        unit("Image Registration", 3, source_level=2, y=110.0),
    ]
    learning_units = _with_boundaries(
        [
            unit("Elementwise versus Matrix Operations", 0, y=100.0),
            unit("Linear versus Nonlinear Operations", 0, y=200.0),
            unit("Arithmetic Operations", 1, y=100.0),
            unit("Set and Logical Operations", 1, children=set_children, y=200.0),
            unit("Spatial Operations", 2, children=spatial_children, end_index=3),
            unit("Vector and Matrix Operations", 3, y=100.0),
            unit("Image Transforms", 3, y=200.0),
            unit("Image Intensities as Random Variables", 3, y=300.0),
        ]
    )
    chapter = PrintedSectionManifest(
        printed_section_id="2",
        title="Digital Image Fundamentals",
        source_heading="2 DIGITAL IMAGE FUNDAMENTALS",
        source_location=HeadingLocation(page=PAGES[0], bbox=(120.0, 20.0, 350.0, 32.0)),
        page_range=page_range(0, 3),
        retrieval_plan=[
            step(index, heading="2 DIGITAL IMAGE FUNDAMENTALS" if index == 0 else "Chapter 2")
            for index in range(4)
        ],
    )
    printed = PrintedSectionManifest(
        printed_section_id="2.6",
        parent_printed_section_id="2",
        title="Introduction to the Basic Mathematical Tools Used in Digital Image Processing",
        source_heading=(
            "2.6 INTRODUCTION TO THE BASIC MATHEMATICAL TOOLS USED IN DIGITAL IMAGE PROCESSING"
        ),
        source_location=HeadingLocation(page=PAGES[0], bbox=(120.0, 40.0, 500.0, 52.0)),
        page_range=page_range(0, 3),
        outline=["Spatial Operations"],
        retrieval_plan=[
            step(
                index,
                heading=(
                    "2.6 INTRODUCTION TO THE BASIC MATHEMATICAL TOOLS USED IN DIGITAL IMAGE PROCESSING"
                    if index == 0
                    else "Section 2.6"
                ),
            )
            for index in range(4)
        ],
        learning_units=learning_units,
    )
    return BookManifest(
        data_version="3",
        index_status="complete",
        book=BookMetadata(
            book_id="dip4e",
            title="Digital Image Processing, 4e",
            author="Rafael C. Gonzalez",
            pdf_filename="Digital Image ProcessingRafael.pdf",
            pdf_sha256="0" * 64,
            page_count=len(PAGES),
        ),
        pages=PAGES,
        page_classifications=[
            PageClassification(page=page, category="body", reason="test fixture") for page in PAGES
        ],
        printed_sections=[chapter, printed],
    )


def exercise_step(
    exercise_id: str,
    index: int,
    *,
    sequence: int = 1,
    page_role: str = "single",
    end_before: str | None = None,
) -> PageRetrievalStep:
    page = PAGES[index]
    evidence = [
        EvidenceRequirement(
            kind="printed_page_equals",
            value=page.printed_page_label,
            verification_mode="visual_required",
        ),
        EvidenceRequirement(
            kind="contains_exercise",
            value=exercise_id,
            verification_mode="visual_required",
        ),
    ]
    end_anchor = None
    if end_before is not None:
        end_anchor = BoundaryAnchor(kind="exercise", value=end_before)
        evidence.append(
            EvidenceRequirement(
                kind="contains_exercise",
                value=end_before,
                verification_mode="visual_required",
            )
        )
    return PageRetrievalStep(
        sequence=sequence,
        page_role=page_role,
        page=page,
        content_window=ContentWindow(
            start_at=BoundaryAnchor(kind="exercise", value=exercise_id),
            end_before=end_anchor,
        ),
        queries=[
            f"+({exercise_id}) +(printed page {page.printed_page_label}) --QDF=0",
            f"exercise {exercise_id} page {page.printed_page_label} --QDF=0",
        ],
        required_evidence=evidence,
        coverage=PageCoverage(),
    )


def reference_step() -> PageRetrievalStep:
    page = PAGES[0]
    heading = "2.5 SOME BASIC RELATIONSHIPS BETWEEN PIXELS"
    return PageRetrievalStep(
        sequence=1,
        page_role="single",
        page=page,
        content_window=ContentWindow(
            start_at=BoundaryAnchor(kind="heading", value=heading),
        ),
        queries=[
            f"+({heading}) +(printed page {page.printed_page_label}) --QDF=0",
            f"pixel adjacency page {page.printed_page_label} --QDF=0",
        ],
        required_evidence=[
            EvidenceRequirement(
                kind="printed_page_equals",
                value=page.printed_page_label,
                verification_mode="visual_required",
            ),
            EvidenceRequirement(
                kind="contains_heading",
                value=heading,
                verification_mode="visual_required",
            ),
        ],
        coverage=PageCoverage(subheadings=[heading]),
    )


def complete_exercise_index() -> CompiledExerciseIndex:
    manifest = complete_manifest()
    exercise_214 = ExerciseLocator(
        book_id="dip4e",
        exercise_id="2.14",
        chapter_id="2",
        exercise_number=14,
        starred=True,
        source_order=1,
        problem_page_range=page_range(1, 1),
        problem_retrieval_plan=[exercise_step("2.14", 1, end_before="2.15")],
        reference_targets=[
            ExerciseReferenceTarget(
                kind="section",
                target_id="2.5",
                reason="Definitions of pixel adjacency",
                retrieval_plan=[reference_step()],
            )
        ],
    )
    exercise_215 = ExerciseLocator(
        book_id="dip4e",
        exercise_id="2.15",
        chapter_id="2",
        exercise_number=15,
        source_order=2,
        problem_page_range=page_range(1, 1),
        problem_retrieval_plan=[exercise_step("2.15", 1)],
    )
    exercise_ids = ["2.14", "2.15"]
    return CompiledExerciseIndex(
        index_status="complete",
        book=manifest.book,
        pages=PAGES,
        chapters={
            "2": ChapterExerciseSummary(
                book_id="dip4e",
                chapter_id="2",
                exercise_ids=exercise_ids,
                first_exercise=exercise_ids[0],
                last_exercise=exercise_ids[-1],
                exercise_count=len(exercise_ids),
            )
        },
        exercises={
            exercise_214.exercise_id: exercise_214,
            exercise_215.exercise_id: exercise_215,
        },
    )


def exercise_manifest_step(
    exercise_id: str,
    index: int,
    *,
    end_before: str | None = None,
) -> ManifestRetrievalStep:
    page = PAGES[index]
    evidence = [
        EvidenceRequirement(
            kind="printed_page_equals",
            value=page.printed_page_label,
            verification_mode="visual_required",
        ),
        EvidenceRequirement(
            kind="contains_exercise",
            value=exercise_id,
            verification_mode="visual_required",
        ),
    ]
    end_anchor = None
    if end_before is not None:
        end_anchor = BoundaryAnchor(kind="exercise", value=end_before)
        evidence.append(
            EvidenceRequirement(
                kind="contains_exercise",
                value=end_before,
                verification_mode="visual_required",
            )
        )
    return ManifestRetrievalStep(
        page=page,
        content_window=ContentWindow(
            start_at=BoundaryAnchor(kind="exercise", value=exercise_id),
            end_before=end_anchor,
        ),
        queries=[
            f"+({exercise_id}) +(printed page {page.printed_page_label}) --QDF=0",
            f"exercise {exercise_id} page {page.printed_page_label} --QDF=0",
        ],
        required_evidence=evidence,
        coverage=PageCoverage(),
    )


def complete_exercise_manifest() -> ExerciseManifest:
    book_manifest = complete_manifest()
    return ExerciseManifest(
        index_status="complete",
        book=book_manifest.book,
        pages=PAGES,
        exercises=[
            ExerciseManifestNode(
                exercise_id="2.14",
                chapter_id="2",
                exercise_number=14,
                starred=True,
                source_order=1,
                problem_page_range=page_range(1, 1),
                problem_retrieval_plan=[exercise_manifest_step("2.14", 1, end_before="2.15")],
                reference_specs=[
                    ExerciseReferenceSpec(
                        kind="section",
                        target_id="2.6.5",
                        reason="Definitions used by the exercise",
                    )
                ],
            ),
            ExerciseManifestNode(
                exercise_id="2.15",
                chapter_id="2",
                exercise_number=15,
                source_order=2,
                problem_page_range=page_range(1, 1),
                problem_retrieval_plan=[exercise_manifest_step("2.15", 1)],
                reference_specs=[
                    ExerciseReferenceSpec(
                        kind="exercise",
                        target_id="2.14",
                        reason="Builds on the preceding exercise",
                    )
                ],
            ),
        ],
    )
