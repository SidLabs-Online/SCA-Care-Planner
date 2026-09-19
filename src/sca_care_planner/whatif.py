# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Sidhartha Mitra, SidLabs Online LLP. See NOTICE.
"""Questions that could change the plan.

``what_if`` applies hypothetical answers to open questions and returns the new
plan with a diff. ``question_impact`` does that for every open question and
every possible answer, so a clinician can see which single fact matters most
before asking the family anything.

Answers are keyed by the question ``field`` exactly as the engine reports it:

* ``observation:<key>``, ``stale_observation:<key>``, ``conflicting_observation:<key>``
  take ``True`` or ``False``. The answer is recorded as a fresh observation at
  the current age and replaces any same-age observations of that key.
* ``completion:<slot_id>`` takes ``"done"``/``"not_done"`` (or ``True``/``False``).
* ``confirmation_of_existing_genetic_report`` takes ``True`` (confirmed) or ``False``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from .compare import PlanDiff, compare_plans
from .engine import CONFIRMATION_FIELD, MAX_HORIZON_MONTHS, evaluate_plan
from .errors import SCACareError
from .evidence import EvidencePack
from .history import Completion, CompletionStatus, Observation, PatientHistory
from .plan import CarePlan

Answer = bool | str
WHAT_IF_SOURCE = "what_if_hypothetical"


def apply_answer(history: PatientHistory, field: str, answer: Answer) -> PatientHistory:
    """Return a new history with one hypothetical answer recorded at the current age."""
    age = history.age_months
    kind, _, target = field.partition(":")
    if field == CONFIRMATION_FIELD:
        return replace(history, karyotype_status="confirmed" if answer is True else "not_confirmed")
    if kind in ("observation", "stale_observation", "conflicting_observation") and target:
        if not isinstance(answer, bool):
            raise SCACareError("observation answers must be True or False", field=field)
        kept = tuple(o for o in history.observations if not (o.key == target and o.observed_at_months == age))
        new = Observation(target, answer, age, age, WHAT_IF_SOURCE)
        return replace(history, observations=(*kept, new))
    if kind == "completion" and target:
        if answer in (True, "done"):
            status: CompletionStatus = "done"
        elif answer in (False, "not_done"):
            status = "not_done"
        else:
            raise SCACareError("completion answers must be 'done', 'not_done', True or False", field=field)
        return history.with_completion(Completion(target, status, age, WHAT_IF_SOURCE))
    raise SCACareError("not a question field this version can answer", field=field)


@dataclass(frozen=True, slots=True)
class WhatIf:
    answers: Mapping[str, Answer]
    plan: CarePlan
    diff: PlanDiff

    def to_dict(self) -> dict[str, Any]:
        return {"answers": dict(self.answers), "diff": self.diff.to_dict()}


def what_if(
    history: PatientHistory | Mapping[str, Any],
    answers: Mapping[str, Answer],
    pack: EvidencePack | Mapping[str, Any] | None = None,
    horizon_months: float = MAX_HORIZON_MONTHS,
) -> WhatIf:
    """Re-run the plan with hypothetical answers and report what moves."""
    history = PatientHistory.coerce(history)
    pack = EvidencePack.coerce(pack)
    baseline = evaluate_plan(history, pack, horizon_months)
    changed = history
    for field, answer in answers.items():
        changed = apply_answer(changed, field, answer)
    plan = evaluate_plan(changed, pack, horizon_months)
    return WhatIf(dict(answers), plan, compare_plans(baseline, plan))


def _possible_answers(field: str) -> tuple[Answer, ...]:
    return ("done", "not_done") if field.startswith("completion:") else (True, False)


@dataclass(frozen=True, slots=True)
class QuestionImpact:
    field: str
    potential_priority: int
    outcomes: tuple[WhatIf, ...]

    @property
    def max_changes(self) -> int:
        """Largest number of actions any single answer would move."""
        return max((len(o.diff.changes) for o in self.outcomes), default=0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "potential_priority": self.potential_priority,
            "max_changes": self.max_changes,
            "outcomes": [o.to_dict() for o in self.outcomes],
        }


def question_impact(
    history: PatientHistory | Mapping[str, Any],
    pack: EvidencePack | Mapping[str, Any] | None = None,
    horizon_months: float = MAX_HORIZON_MONTHS,
) -> list[QuestionImpact]:
    """For every open question, the plan diff under each possible answer.

    Order follows the engine's own question ranking. No answer probabilities
    are estimated, so this is sensitivity analysis, not value of information.
    """
    history = PatientHistory.coerce(history)
    pack = EvidencePack.coerce(pack)
    plan = evaluate_plan(history, pack, horizon_months)
    return [
        QuestionImpact(
            q.field,
            q.potential_priority,
            tuple(what_if(history, {q.field: a}, pack, horizon_months) for a in _possible_answers(q.field)),
        )
        for q in plan.questions
    ]
