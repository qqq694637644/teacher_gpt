from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

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
    CompiledLocatorIndex,
    EvidenceRequirement,
    PageCoverage,
    PageRetrievalStep,
    query_safe_anchor,
)
from app.models.manifest import ManifestRetrievalStep

ReferencePlanMap = dict[tuple[str, str], list[PageRetrievalStep]]


@dataclass(frozen=True)
class ReferencePlanStats:
    raw_reference_step_count: int = 0
    selected_context_reference_count: int = 0
    execution_reference_step_count_before_merge: int = 0
    coalesced_reference_step_count: int = 0
    same_page_distinct_window_step_count: int = 0
    deduplicated_reference_step_count: int = 0
    transitive_exercise_dependency_count: int = 0
    max_exercise_dependency_depth: int = 0


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
        selected_context_reference_count = 0
        execution_reference_step_count_before_merge = 0
        coalesced_reference_step_count = 0
        same_page_distinct_window_step_count = 0
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

        direct_targets: dict[str, list[ExerciseReferenceTarget]] = {}
        direct_execution_targets: dict[str, list[ExerciseReferenceTarget]] = {}
        for exercise_id, locator in preliminary.items():
            targets: list[ExerciseReferenceTarget] = []
            execution_targets: list[ExerciseReferenceTarget] = []
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
                normalized_plan = self._normalize_page_plan(list(plan))
                targets.append(
                    ExerciseReferenceTarget(
                        kind=spec.kind,
                        target_id=spec.target_id,
                        reason=spec.reason,
                        selected_context_pages=spec.selected_context_pages,
                        retrieval_plan=normalized_plan,
                    )
                )
                execution_plan = self._selected_execution_plan(
                    exercise_id,
                    spec,
                    normalized_plan,
                )
                execution_targets.append(
                    ExerciseReferenceTarget(
                        kind=spec.kind,
                        target_id=spec.target_id,
                        reason=spec.reason,
                        selected_context_pages=spec.selected_context_pages,
                        retrieval_plan=execution_plan,
                    )
                )
            direct_targets[exercise_id] = targets
            direct_execution_targets[exercise_id] = execution_targets
            raw_reference_step_count += sum(len(target.retrieval_plan) for target in targets)
            selected_context_reference_count += sum(
                bool(target.selected_context_pages) for target in execution_targets
            )

        closure_memo: dict[str, tuple[list[PageRetrievalStep], set[str], int]] = {}

        def dependency_closure(
            exercise_id: str,
            visiting: tuple[str, ...] = (),
        ) -> tuple[list[PageRetrievalStep], set[str], int]:
            if exercise_id in closure_memo:
                return closure_memo[exercise_id]
            if exercise_id in visiting:
                cycle = " -> ".join((*visiting, exercise_id))
                raise ValueError(f"exercise dependency cycle detected: {cycle}")

            steps = [
                step
                for target in direct_execution_targets[exercise_id]
                for step in target.retrieval_plan
            ]
            dependency_ids: set[str] = set()
            max_depth = 0
            for target in direct_targets[exercise_id]:
                if target.kind != "exercise":
                    continue
                dependency_ids.add(target.target_id)
                child_steps, child_ids, child_depth = dependency_closure(
                    target.target_id,
                    (*visiting, exercise_id),
                )
                steps.extend(child_steps)
                dependency_ids.update(child_ids)
                max_depth = max(max_depth, child_depth + 1)
            result = (steps, dependency_ids, max_depth)
            closure_memo[exercise_id] = result
            return result

        exercises: dict[str, ExerciseLocator] = {}
        transitive_exercise_dependency_count = 0
        max_exercise_dependency_depth = 0
        for exercise_id, locator in preliminary.items():
            closure_steps, dependency_ids, dependency_depth = dependency_closure(exercise_id)
            direct_dependency_ids = {
                target.target_id
                for target in direct_targets[exercise_id]
                if target.kind == "exercise"
            }
            transitive_exercise_dependency_count += len(dependency_ids - direct_dependency_ids)
            max_exercise_dependency_depth = max(
                max_exercise_dependency_depth,
                dependency_depth,
            )
            execution_step_count = len(closure_steps)
            execution_reference_step_count_before_merge += execution_step_count
            same_page_distinct_window_step_count += (
                self._same_page_distinct_window_count_from_steps(closure_steps)
            )
            aggregate_plan = self._merge_reference_steps(closure_steps)
            coalesced_reference_step_count += execution_step_count - len(aggregate_plan)
            deduplicated_reference_step_count += len(aggregate_plan)
            exercises[exercise_id] = ExerciseLocator.model_validate(
                {
                    **locator.model_dump(mode="json"),
                    "reference_retrieval_plan": [
                        step.model_dump(mode="json") for step in aggregate_plan
                    ],
                    "reference_targets": [
                        target.model_dump(mode="json") for target in direct_targets[exercise_id]
                    ],
                }
            )

        self.reference_plan_stats = ReferencePlanStats(
            raw_reference_step_count=raw_reference_step_count,
            selected_context_reference_count=selected_context_reference_count,
            execution_reference_step_count_before_merge=(
                execution_reference_step_count_before_merge
            ),
            coalesced_reference_step_count=coalesced_reference_step_count,
            same_page_distinct_window_step_count=same_page_distinct_window_step_count,
            deduplicated_reference_step_count=deduplicated_reference_step_count,
            transitive_exercise_dependency_count=transitive_exercise_dependency_count,
            max_exercise_dependency_depth=max_exercise_dependency_depth,
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

    @classmethod
    def _compile_plan(cls, source_steps: list[ManifestRetrievalStep]) -> list[PageRetrievalStep]:
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
                    queries=cls._safe_queries(step.required_evidence, step.page.printed_page_label),
                    required_evidence=step.required_evidence,
                    coverage=step.coverage,
                )
            )
        return steps

    @classmethod
    def _normalize_page_plan(
        cls,
        source_steps: list[PageRetrievalStep],
    ) -> list[PageRetrievalStep]:
        return [
            PageRetrievalStep(
                sequence=step.sequence,
                page_role=step.page_role,
                page=step.page,
                content_window=step.content_window,
                queries=cls._safe_queries(
                    step.required_evidence,
                    step.page.printed_page_label,
                ),
                required_evidence=step.required_evidence,
                coverage=step.coverage,
            )
            for step in source_steps
        ]

    @staticmethod
    def _selected_execution_plan(
        exercise_id: str,
        spec: ExerciseReferenceSpec,
        plan: list[PageRetrievalStep],
    ) -> list[PageRetrievalStep]:
        if not spec.selected_context_pages:
            return plan
        selected = set(spec.selected_context_pages)
        available = {step.page.printed_page_label for step in plan}
        missing = sorted(selected - available)
        if missing:
            raise ValueError(
                f"exercise {exercise_id} selects pages outside section {spec.target_id}: {missing}"
            )
        return [step for step in plan if step.page.printed_page_label in selected]

    @staticmethod
    def _window_key(step: PageRetrievalStep) -> tuple[object, ...]:
        start = step.content_window.start_at
        end = step.content_window.end_before
        return (
            step.page.pdf_page_index,
            None if start is None else (start.kind, start.value),
            None if end is None else (end.kind, end.value),
        )

    @classmethod
    def _same_page_distinct_window_count(
        cls,
        targets: list[ExerciseReferenceTarget],
    ) -> int:
        return cls._same_page_distinct_window_count_from_steps(
            [step for target in targets for step in target.retrieval_plan]
        )

    @classmethod
    def _same_page_distinct_window_count_from_steps(
        cls,
        steps: list[PageRetrievalStep],
    ) -> int:
        windows_by_page: dict[int, set[tuple[object, ...]]] = defaultdict(set)
        for step in steps:
            windows_by_page[step.page.pdf_page_index].add(cls._window_key(step))
        return sum(max(0, len(windows) - 1) for windows in windows_by_page.values())

    @classmethod
    def _merge_reference_targets(
        cls,
        targets: list[ExerciseReferenceTarget],
    ) -> list[PageRetrievalStep]:
        return cls._merge_reference_steps(
            [step for target in targets for step in target.retrieval_plan]
        )

    @classmethod
    def _merge_reference_steps(
        cls,
        steps: list[PageRetrievalStep],
    ) -> list[PageRetrievalStep]:
        grouped: dict[tuple[object, ...], list[PageRetrievalStep]] = {}
        for step in steps:
            grouped.setdefault(cls._window_key(step), []).append(step)

        merged: list[PageRetrievalStep] = []
        ordered_groups = sorted(
            grouped.values(),
            key=lambda source_steps: cls._step_sort_key(source_steps[0]),
        )
        for sequence, source_steps in enumerate(ordered_groups, start=1):
            first = source_steps[0]
            evidence = cls._merged_evidence(source_steps)
            merged.append(
                PageRetrievalStep(
                    sequence=sequence,
                    page_role=first.page_role,
                    page=first.page,
                    content_window=first.content_window,
                    queries=cls._safe_queries(evidence, first.page.printed_page_label),
                    required_evidence=evidence,
                    coverage=cls._merged_coverage(source_steps),
                )
            )
        return merged

    @staticmethod
    def _step_sort_key(step: PageRetrievalStep) -> tuple[object, ...]:
        def anchor_key(anchor: object | None) -> tuple[str, str]:
            if anchor is None:
                return ("", "")
            kind = anchor.kind
            value = anchor.value
            natural_value = re.sub(
                r"\d+",
                lambda match: f"{int(match.group()):010d}",
                value.casefold(),
            )
            return (kind, natural_value)

        return (
            step.page.pdf_page_index,
            anchor_key(step.content_window.start_at),
            anchor_key(step.content_window.end_before),
        )

    @classmethod
    def _safe_queries(
        cls,
        evidence: list[EvidenceRequirement],
        page_label: str,
    ) -> list[str]:
        queries: list[str] = []
        for item in evidence:
            if item.kind == "printed_page_equals":
                continue
            query = cls._evidence_query(item, page_label)
            if query not in queries:
                queries.append(query)
        if len(queries) == 1:
            item = next(item for item in evidence if item.kind != "printed_page_equals")
            prefix = cls._evidence_prefix(item.kind)
            anchor = query_safe_anchor(item.value)
            queries.append(f"+({anchor}) +({prefix}) +(printed page {page_label}) --QDF=0")
        return queries

    @staticmethod
    def _evidence_prefix(kind: str) -> str:
        prefixes = {
            "contains_heading": "heading",
            "contains_text": "text",
            "contains_figure": "figure",
            "contains_equation": "equation",
            "contains_example": "example",
            "contains_table": "table",
            "contains_exercise": "exercise",
        }
        return prefixes[kind]

    @classmethod
    def _evidence_query(cls, evidence: EvidenceRequirement, page_label: str) -> str:
        prefix = cls._evidence_prefix(evidence.kind)
        anchor = query_safe_anchor(evidence.value)
        return f"+({prefix} {anchor}) +(printed page {page_label}) --QDF=0"

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
