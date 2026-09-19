# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Sidhartha Mitra, SidLabs Online LLP. See NOTICE.
"""Care timeline over the horizon.

``predict_care`` answers "if nothing new is recorded, what will this plan ask
for, month by month, over the next 24 months?". It re-runs the engine at each
whole month in the window using only what is known today, then records every
point where an action appears, changes state or drops out.

That is a deterministic projection of rule-supported care. It predicts no
outcome and no probability. An observation that expires inside the window
shows up as a ``verify`` event, because that is exactly what the engine will
ask for once it goes stale.
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, replace
from typing import Any

from .compare import state_of
from .engine import MAX_HORIZON_MONTHS, evaluate_plan, validate_horizon
from .evidence import EvidencePack
from .history import PatientHistory
from .plan import Action, CarePlan


@dataclass(frozen=True, slots=True)
class TimelineEvent:
    age_months: float
    action_id: str
    rule_id: str
    state: str
    """``review``, ``due``, ``scheduled``, ``verify``, or ``ends`` when it drops out of the plan."""
    previous_state: str | None
    action: str
    evidence_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "age_months": self.age_months,
            "action_id": self.action_id,
            "rule_id": self.rule_id,
            "state": self.state,
            "previous_state": self.previous_state,
            "action": self.action,
            "evidence_ids": list(self.evidence_ids),
        }


@dataclass(frozen=True, slots=True)
class CareTimeline:
    start_age_months: float
    end_age_months: float
    pack_id: str
    pack_sha256: str
    events: tuple[TimelineEvent, ...]
    snapshots: tuple[tuple[float, CarePlan], ...]
    excluded_future_records: int = 0
    """Records dated after the start age. They are ignored, and counted here so nobody wonders."""
    risk_probability: None = None

    def __iter__(self) -> Iterator[TimelineEvent]:
        return iter(self.events)

    def at(self, age_months: float) -> CarePlan:
        """Projected plan in force at ``age_months`` (the latest snapshot not after it)."""
        chosen = None
        for age, plan in self.snapshots:
            if age <= age_months:
                chosen = plan
        if chosen is None:
            raise KeyError(f"{age_months} is before the timeline start")
        return chosen

    def for_action(self, action_id: str) -> list[TimelineEvent]:
        return [e for e in self.events if e.action_id == action_id]

    def to_rows(self) -> list[dict[str, Any]]:
        """Flat rows, ready for ``pandas.DataFrame(timeline.to_rows())``."""
        return [e.to_dict() for e in self.events]

    def to_dict(self) -> dict[str, Any]:
        return {
            "start_age_months": self.start_age_months,
            "end_age_months": self.end_age_months,
            "pack_id": self.pack_id,
            "pack_sha256": self.pack_sha256,
            "excluded_future_records": self.excluded_future_records,
            "risk_probability": None,
            "events": self.to_rows(),
        }


def _grid(start: float, end: float) -> list[float]:
    ages = [start]
    month = math.floor(start) + 1
    while month <= end:
        ages.append(float(month))
        month += 1
    return ages


def _event(age: float, a: Action, state: str, previous: str | None) -> TimelineEvent:
    return TimelineEvent(
        age_months=age,
        action_id=a.action_id,
        rule_id=a.rule_id,
        state=state,
        previous_state=previous,
        action=a.action,
        evidence_ids=tuple(str(e.get("id", "")) for e in a.evidence),
    )


def predict_care(
    history: PatientHistory | Mapping[str, Any],
    pack: EvidencePack | Mapping[str, Any] | None = None,
    horizon_months: float = MAX_HORIZON_MONTHS,
) -> CareTimeline:
    """Month-by-month projection of the care plan, assuming no new records arrive."""
    history = PatientHistory.coerce(history)
    pack = EvidencePack.coerce(pack)
    horizon = validate_horizon(horizon_months)
    start = history.age_months
    end = start + horizon
    # Freeze what is known today. Records dated after the start age must not
    # leak into later snapshots, or the projection would see its own future.
    known = replace(
        history,
        observations=tuple(o for o in history.observations if o.is_visible_at(start)),
        completions=tuple(c for c in history.completions if c.recorded_at_months <= start),
    )
    excluded = len(history.observations) + len(history.completions) - len(known.observations) - len(known.completions)
    history = known

    snapshots: list[tuple[float, CarePlan]] = []
    events: list[TimelineEvent] = []
    current: dict[str, tuple[str, Action]] = {}
    for age in _grid(start, end):
        plan = evaluate_plan(history.at_age(age), pack, horizon_months=max(end - age, 1.0))
        snapshots.append((age, plan))
        now = {a.action_id: (state_of(a), a) for a in plan.all_actions if a.due_age_months <= end}
        if age == start:
            # Opening state: everything the plan holds today, including future slots.
            events += [_event(start, a, state, None) for state, a in now.values()]
            current = now
            continue
        for action_id, (state, a) in now.items():
            before = current.get(action_id)
            if before is None:
                events.append(_event(age, a, state, None))
            elif before[0] != state:
                events.append(_event(age, a, state, before[0]))
        for action_id, (state, a) in current.items():
            if action_id not in now:
                events.append(_event(age, a, "ends", state))
        current = now

    events.sort(key=lambda e: (e.age_months, e.action_id, e.state))
    return CareTimeline(start, end, pack.id, pack.sha256, tuple(events), tuple(snapshots), excluded)
