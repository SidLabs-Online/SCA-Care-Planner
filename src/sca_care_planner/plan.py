# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Sidhartha Mitra, SidLabs Online LLP. See NOTICE.
"""Output types and the workflow priority.

The priority of an action is the lexicographic key

    P(a) = (c_a, -d_a)

where ``c_a`` is the workflow class (3 current review, 2 due care, 1 future
scheduled care) and ``d_a`` is the target age in months. Sort descending on
``P``; ties fall back to the action id so output order is stable.

These are workflow labels. They are not risk probabilities, severity scores or
emergency urgency levels.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import IntEnum
from typing import Any, Literal

ActionStatus = Literal["candidate_for_clinician_review", "verify_before_recommending"]


class PriorityClass(IntEnum):
    """``c_a`` in the priority formula."""

    SCHEDULED = 1
    DUE = 2
    REVIEW = 3

    @property
    def label(self) -> str:
        return {3: "review", 2: "due", 1: "scheduled"}[self.value]

    @classmethod
    def from_label(cls, label: str) -> PriorityClass:
        return {"review": cls.REVIEW, "due": cls.DUE, "scheduled": cls.SCHEDULED}[label]


def priority_key(priority: PriorityClass, due_age_months: float) -> tuple[int, float]:
    """``P(a) = (c_a, -d_a)``. Larger sorts first."""
    return (int(priority), -due_age_months)


@dataclass(frozen=True, slots=True)
class Action:
    """One care candidate, always carrying the evidence and rule that produced it."""

    action_id: str
    rule_id: str
    rule_version: str
    domain: str
    action: str
    reason: str
    priority: PriorityClass
    due_age_months: float
    due_in_months: float
    overdue_months: float
    status: ActionStatus
    evidence: tuple[dict[str, Any], ...]
    rule_review_status: str
    observations_used: tuple[dict[str, Any], ...] = ()
    missing: tuple[str, ...] = ()

    @property
    def key(self) -> tuple[int, float]:
        return priority_key(self.priority, self.due_age_months)

    @property
    def needs_information(self) -> bool:
        return self.status == "verify_before_recommending"

    def sort_key(self) -> tuple[int, float, str]:
        return (-int(self.priority), self.due_age_months, self.action_id)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "action_id": self.action_id,
            "domain": self.domain,
            "action": self.action,
            "due_age_months": self.due_age_months,
            "due_in_months": self.due_in_months,
            "overdue_months": self.overdue_months,
            "priority_class": self.priority.label,
            "priority_key": list(self.key),
            "rule_id": self.rule_id,
            "rule_version": self.rule_version,
            "evidence": [dict(e) for e in self.evidence],
            "rule_review_status": self.rule_review_status,
            "reason": self.reason,
            "observations_used": [dict(o) for o in self.observations_used],
            "status": self.status,
        }
        if self.missing:
            out["missing"] = list(self.missing)
        return out


@dataclass(frozen=True, slots=True)
class Question:
    """A missing fact, ranked by Q(f) = (max c_a over blocked actions, number blocked)."""

    field: str
    affected_action_ids: tuple[str, ...]
    potential_priority: int

    @property
    def affected_count(self) -> int:
        return len(self.affected_action_ids)

    def sort_key(self) -> tuple[int, int, str]:
        return (-self.potential_priority, -self.affected_count, self.field)

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "affected_action_ids": list(self.affected_action_ids),
            "potential_priority": self.potential_priority,
            "affected_count": self.affected_count,
        }


@dataclass(frozen=True, slots=True)
class TraceEntry:
    """Why a rule or slot produced nothing. Read this first when debugging."""

    subject: str
    result: str
    is_slot: bool = False

    def to_dict(self) -> dict[str, str]:
        return {("action_id" if self.is_slot else "rule_id"): self.subject, "result": self.result}


@dataclass(frozen=True, slots=True)
class Withheld:
    rule_id: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CarePlan:
    """The engine's full answer for one history, one pack and one horizon."""

    age_months: float
    pack_id: str
    pack_version: str
    pack_sha256: str
    evidence_review_date: str
    scope_notes: str
    requested_horizon_months: float
    requested_end_age_months: float
    seed_pack_end_age_months: float
    actions: tuple[Action, ...] = ()
    needs_information: tuple[Action, ...] = ()
    questions: tuple[Question, ...] = ()
    withheld: tuple[Withheld, ...] = ()
    trace: tuple[TraceEntry, ...] = ()
    warnings: tuple[str, ...] = ()
    status: str = "research_prototype"
    clinical_validation: str = "not_performed"
    complete_care_coverage: bool = False
    risk_probability: None = field(default=None)
    risk_probability_status: str = "not_estimated"

    @property
    def all_actions(self) -> tuple[Action, ...]:
        """Supported candidates first, then those waiting on information."""
        return self.actions + self.needs_information

    def action(self, action_id: str) -> Action:
        for item in self.all_actions:
            if item.action_id == action_id:
                return item
        raise KeyError(action_id)

    def ids(self, which: Literal["actions", "needs_information", "all"] = "all") -> list[str]:
        items = self.all_actions if which == "all" else getattr(self, which)
        return [a.action_id for a in items]

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready form. Key names match the 0.1 prototype output."""
        return {
            "status": self.status,
            "pack_id": self.pack_id,
            "pack_version": self.pack_version,
            "pack_sha256": self.pack_sha256,
            "evidence_review_date": self.evidence_review_date,
            "clinical_validation": self.clinical_validation,
            "complete_care_coverage": self.complete_care_coverage,
            "scope_notes": self.scope_notes,
            "age_months": self.age_months,
            "requested_horizon_months": self.requested_horizon_months,
            "requested_end_age_months": self.requested_end_age_months,
            "seed_pack_end_age_months": self.seed_pack_end_age_months,
            "risk_probability": self.risk_probability,
            "risk_probability_status": self.risk_probability_status,
            "actions": [a.to_dict() for a in self.actions],
            "needs_information": [a.to_dict() for a in self.needs_information],
            "questions": [q.to_dict() for q in self.questions],
            "withheld": [w.to_dict() for w in self.withheld],
            "trace": [t.to_dict() for t in self.trace],
            "warnings": list(self.warnings),
        }
