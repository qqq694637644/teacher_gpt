from __future__ import annotations

from collections import defaultdict

from app.models.exercise import (
    ChapterExerciseSummary,
    CompiledExerciseIndex,
    ExerciseLocator,
    ExerciseReferenceTarget,
)
from app.models.exercise_manifest import ExerciseManifest, ExerciseManifestNode
from app.models.locator import CompiledLocatorIndex, PageRetrievalStep
from app.models.manifest import ManifestRetrievalStep

ReferencePlanMap = dict[tuple[str, str], list[PageRetrievalStep]]


class ExerciseIndexCompiler:
    """Compile a reviewed exercise manifest into the strict runtime index."""

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
            exercises[exercise_id] = ExerciseLocator.model_validate(
                {
                    **locator.model_dump(mode="json"),
                    "reference_targets": [target.model_dump(mode="json") for target in targets],
                }
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
