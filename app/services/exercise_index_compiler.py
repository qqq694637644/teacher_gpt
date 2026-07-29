from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from app.models.exercise import (
    ChapterExerciseSummary,
    CompiledExerciseIndex,
    ExerciseLocator,
    ExerciseReferenceTarget,
)
from app.models.exercise_manifest import ExerciseManifest, ExerciseManifestNode
from app.models.locator import (
    CompiledLocatorIndex,
    ContentWindow,
    EvidenceRequirement,
    PageCoverage,
    PageRetrievalStep,
)
from app.models.manifest import ManifestRetrievalStep

ReferencePlanMap = dict[tuple[str, str], list[PageRetrievalStep]]


@dataclass(frozen=True)
class ReferencePlanStats:
    raw_reference_step_count: int = 0
    pruned_context_reference_count: int = 0
    duplicate_reference_page_count: int = 0
    deduplicated_reference_step_count: int = 0


class ExerciseIndexCompiler:
    """Compile a reviewed exercise manifest into the strict runtime index."""

    def __init__(self) -> None:
        self.reference_plan_stats = ReferencePlanStats()

    def compile(
        self,
        manifest: ExerciseManifest,
        section_index: CompiledLocatorIndex,
        reference_plans: ReferencePlanMap | None = None,
    ) -> CompiledExerciseIndex:
        if manifest.book != section_index.book:
            raise ValueError("exercise manifest book metadata does not match section index")
        if manifest.pages != section_index.pages:
            raise ValueError("exercise manifest pages do not match section index")

        resolved_plans = reference_plans or {}
        raw_reference_step_count = 0
        pruned_context_reference_count = 0
        duplicate_reference_page_count = 0
        deduplicated_reference_step_count = 0
        preliminary: dict[str, ExerciseLocator] = {}
        nodes: dict[str, ExerciseManifestNode] = {}
        for node in manifest.exercises:
            locator = ExerciseLocator(
                book_id=manifest.book.book_id,
                exercise_id=node.exercise_id,
                chapter_id=node.chapter_id,
                exercise_number=node.exercise_number,
                starred=node.starred,
                source_order=node.source_order,
                problem_page_range=node.problem_page_range,
                problem_retrieval_plan=self._compile_plan(node.problem_retrieval_plan),
                reference_retrieval_plan=[],
                reference_targets=[],
            )
            if locator.exercise_id in preliminary:
                raise ValueError(f"duplicate compiled exercise id: {locator.exercise_id}")
            preliminary[locator.exercise_id] = locator
            nodes[locator.exercise_id] = node

        exercises: dict[str, ExerciseLocator] = {}
        for exercise_id, locator in preliminary.items():
            targets: list[ExerciseReferenceTarget] = []
            for spec in nodes[exercise_id].reference_specs:
                if spec.kind == "section":
                    try:
                        plan = section_index.sections[spec.target_id].retrieval_plan
                    except KeyError as exc:
                        raise ValueError(
                            f"exercise {exercise_id} references missing section {spec.target_id}"
                        ) from exc
                elif spec.kind == "exercise":
                    try:
                        plan = preliminary[spec.target_id].problem_retrieval_plan
                    except KeyError as exc:
                        raise ValueError(
                            f"exercise {exercise_id} references missing exercise {spec.target_id}"
                        ) from exc
                else:
                    key = (spec.kind, spec.target_id)
                    try:
                        plan = resolved_plans[key]
                    except KeyError as exc:
                        raise ValueError(
                            f"exercise {exercise_id} references unresolved {spec.kind} "
                            f"{spec.target_id}"
                        ) from exc
                targets.append(
                    ExerciseReferenceTarget(
                        kind=spec.kind,
                        target_id=spec.target_id,
                        reason=spec.reason,
                        retrieval_plan=list(plan),
                    )
                )
            raw_reference_step_count += sum(len(target.retrieval_plan) for target in targets)
            duplicate_reference_page_count += self._duplicate_page_count(targets)
            optimized_targets, pruned_count = self._prune_context_sections(targets)
            pruned_context_reference_count += pruned_count
            aggregate_plan = self._merge_reference_targets(optimized_targets)
            deduplicated_reference_step_count += len(aggregate_plan)
            exercises[exercise_id] = ExerciseLocator.model_validate(
                {
                    **locator.model_dump(mode="json"),
                    "reference_retrieval_plan": [
                        step.model_dump(mode="json") for step in aggregate_plan
                    ],
                    "reference_targets": [target.model_dump(mode="json") for target in targets],
                }
            )

        self.reference_plan_stats = ReferencePlanStats(
            raw_reference_step_count=raw_reference_step_count,
            pruned_context_reference_count=pruned_context_reference_count,
            duplicate_reference_page_count=duplicate_reference_page_count,
            deduplicated_reference_step_count=deduplicated_reference_step_count,
        )

        grouped: dict[str, list[ExerciseLocator]] = defaultdict(list)
        for locator in exercises.values():
            grouped[locator.chapter_id].append(locator)

        chapters: dict[str, ChapterExerciseSummary] = {}
        for chapter_id, locators in grouped.items():
            ordered = sorted(locators, key=lambda item: item.source_order)
            exercise_ids = [item.exercise_id for item in ordered]
            chapters[chapter_id] = ChapterExerciseSummary(
                book_id=manifest.book.book_id,
                chapter_id=chapter_id,
                exercise_ids=exercise_ids,
                first_exercise=exercise_ids[0],
                last_exercise=exercise_ids[-1],
                exercise_count=len(exercise_ids),
            )

        return CompiledExerciseIndex(
            index_status="complete",
            book=manifest.book,
            pages=manifest.pages,
            chapters=chapters,
            exercises=exercises,
        )

    @staticmethod
    def _compile_plan(source_steps: list[ManifestRetrievalStep]) -> list[PageRetrievalStep]:
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
    def _target_chapter(target: ExerciseReferenceTarget) -> str:
        if target.kind == "equation":
            return target.target_id.split("-", 1)[0]
        return target.target_id.split(".", 1)[0]

    @classmethod
    def _prune_context_sections(
        cls,
        targets: list[ExerciseReferenceTarget],
    ) -> tuple[list[ExerciseReferenceTarget], int]:
        precise_targets = [target for target in targets if target.kind != "section"]
        if not precise_targets:
            return targets, 0

        pruned = 0
        kept: list[ExerciseReferenceTarget] = []
        for target in targets:
            if target.kind != "section":
                kept.append(target)
                continue
            section_pages = {step.page.pdf_page_index for step in target.retrieval_plan}
            precise_pages_inside: set[int] = set()
            for precise in precise_targets:
                precise_pages = {step.page.pdf_page_index for step in precise.retrieval_plan}
                if (
                    cls._target_chapter(precise) == cls._target_chapter(target)
                    and precise_pages <= section_pages
                ):
                    precise_pages_inside.update(precise_pages)
            if precise_pages_inside:
                pruned += 1
                kept.append(
                    target.model_copy(
                        update={
                            "retrieval_plan": [
                                step
                                for step in target.retrieval_plan
                                if step.page.pdf_page_index in precise_pages_inside
                            ]
                        }
                    )
                )
                continue
            kept.append(target)
        return kept, pruned

    @staticmethod
    def _duplicate_page_count(targets: list[ExerciseReferenceTarget]) -> int:
        pages = [step.page.pdf_page_index for target in targets for step in target.retrieval_plan]
        return len(pages) - len(set(pages))

    @classmethod
    def _merge_reference_targets(
        cls,
        targets: list[ExerciseReferenceTarget],
    ) -> list[PageRetrievalStep]:
        by_page: dict[int, list[PageRetrievalStep]] = defaultdict(list)
        for target in targets:
            for step in target.retrieval_plan:
                by_page[step.page.pdf_page_index].append(step)

        merged: list[PageRetrievalStep] = []
        for sequence, page_index in enumerate(sorted(by_page), start=1):
            source_steps = by_page[page_index]
            first = source_steps[0]
            merged.append(
                PageRetrievalStep(
                    sequence=sequence,
                    page_role="single",
                    page=first.page,
                    content_window=ContentWindow(),
                    queries=cls._merged_queries(source_steps),
                    required_evidence=cls._merged_evidence(source_steps),
                    coverage=cls._merged_coverage(source_steps),
                )
            )
        return merged

    @staticmethod
    def _merged_queries(steps: list[PageRetrievalStep]) -> list[str]:
        queries: list[str] = []
        for step in steps:
            for query in step.queries:
                if query not in queries:
                    queries.append(query)
                if len(queries) == 4:
                    return queries
        return queries

    @staticmethod
    def _merged_evidence(steps: list[PageRetrievalStep]) -> list[EvidenceRequirement]:
        page = steps[0].page
        evidence: list[EvidenceRequirement] = [
            EvidenceRequirement(
                kind="printed_page_equals",
                value=page.printed_page_label,
                verification_mode="visual_required",
            )
        ]
        seen = {(evidence[0].kind, evidence[0].value, evidence[0].verification_mode)}
        for step in steps:
            for item in step.required_evidence:
                key = (item.kind, item.value, item.verification_mode)
                if item.kind == "printed_page_equals" or key in seen:
                    continue
                seen.add(key)
                evidence.append(item)
        return evidence

    @staticmethod
    def _merged_coverage(steps: list[PageRetrievalStep]) -> PageCoverage:
        return PageCoverage(
            subheadings=list(
                dict.fromkeys(heading for step in steps for heading in step.coverage.subheadings)
            ),
            figure_ids=list(
                dict.fromkeys(item for step in steps for item in step.coverage.figure_ids)
            ),
            equation_ids=list(
                dict.fromkeys(item for step in steps for item in step.coverage.equation_ids)
            ),
            example_ids=list(
                dict.fromkeys(item for step in steps for item in step.coverage.example_ids)
            ),
            table_ids=list(
                dict.fromkeys(item for step in steps for item in step.coverage.table_ids)
            ),
        )
