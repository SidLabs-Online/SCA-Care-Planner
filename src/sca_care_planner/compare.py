# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Sidhartha Mitra, SidLabs Online LLP. See NOTICE.
"""Plan diffs.

Two uses. A researcher updating an evidence pack runs the same fixtures under
the old and new pack and reads the diff. The what-if tools use the same diff
to show how one answer would move the plan.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .plan import Action, CarePlan


def state_of(action: Action) -> str:
    """Compact state label: ``review``, ``due``, ``scheduled`` or ``verify``."""
    return "verify" if action.needs_information else action.priority.label


@dataclass(frozen=True, slots=True)
class Change:
    action_id: str
    before: str | None
    after: str | None

    @property
    def kind(self) -> str:
        if self.before is None:
            return "added"
        if self.after is None:
            return "removed"
        return "changed"

    def __str__(self) -> str:
        return f"{self.action_id}: {self.before or '-'} -> {self.after or '-'}"

    def to_dict(self) -> dict[str, Any]:
        return {"action_id": self.action_id, "kind": self.kind, "before": self.before, "after": self.after}


@dataclass(frozen=True, slots=True)
class PlanDiff:
    changes: tuple[Change, ...]
    questions_resolved: tuple[str, ...]
    questions_added: tuple[str, ...]
    fingerprint_changed: bool

    @property
    def is_empty(self) -> bool:
        return not (self.changes or self.questions_resolved or self.questions_added)

    def of_kind(self, kind: str) -> list[Change]:
        return [c for c in self.changes if c.kind == kind]

    def __str__(self) -> str:
        if self.is_empty:
            return "no change"
        lines = [str(c) for c in self.changes]
        lines += [f"question resolved: {q}" for q in self.questions_resolved]
        lines += [f"question added: {q}" for q in self.questions_added]
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "changes": [c.to_dict() for c in self.changes],
            "questions_resolved": list(self.questions_resolved),
            "questions_added": list(self.questions_added),
            "fingerprint_changed": self.fingerprint_changed,
        }


def compare_plans(before: CarePlan, after: CarePlan) -> PlanDiff:
    """Action-level and question-level differences between two plans."""
    old = {a.action_id: state_of(a) for a in before.all_actions}
    new = {a.action_id: state_of(a) for a in after.all_actions}
    changes = tuple(
        Change(i, old.get(i), new.get(i)) for i in sorted(old.keys() | new.keys()) if old.get(i) != new.get(i)
    )
    q_old = {q.field for q in before.questions}
    q_new = {q.field for q in after.questions}
    return PlanDiff(
        changes=changes,
        questions_resolved=tuple(sorted(q_old - q_new)),
        questions_added=tuple(sorted(q_new - q_old)),
        fingerprint_changed=before.pack_sha256 != after.pack_sha256,
    )
