# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Sidhartha Mitra, SidLabs Online LLP. See NOTICE.
"""The rule engine.

``evaluate_plan`` is pure: same history, same pack, same horizon, same plan.
It makes no network calls, reads no clock and never mutates its inputs.

Turn on ``logging.getLogger("sca_care_planner").setLevel(logging.DEBUG)`` to
watch each rule decision as it happens; the same decisions are kept in
``CarePlan.trace`` for later inspection.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .errors import HistoryError, SCACareError
from .evidence import EvidencePack, Rule
from .history import Completion, Observation, PatientHistory, as_months
from .plan import Action, CarePlan, PriorityClass, Question, TraceEntry, Withheld
from .truth import Truth, all_of

log = logging.getLogger("sca_care_planner")

MAX_HORIZON_MONTHS = 24.0
CONFIRMATION_FIELD = "confirmation_of_existing_genetic_report"


@dataclass(frozen=True, slots=True)
class ObservationState:
    """Current value of one feature at one age, and why."""

    value: bool | None
    field: str
    used: tuple[Observation, ...] = ()

    @property
    def truth(self) -> Truth:
        return Truth.of(self.value)


def observation_state(observations: Iterable[Observation], key: str, age: float) -> ObservationState:
    """Newest visible observation wins. A tie that disagrees, or an expired value, is unknown."""
    visible = [o for o in observations if o.key == key and o.is_visible_at(age)]
    if not visible:
        return ObservationState(None, f"observation:{key}")
    latest_time = max(o.observed_at_months for o in visible)
    latest = tuple(o for o in visible if o.observed_at_months == latest_time)
    if len({o.value for o in latest}) != 1:
        return ObservationState(None, f"conflicting_observation:{key}", latest)
    if any(o.valid_until_months < age for o in latest):
        return ObservationState(None, f"stale_observation:{key}", latest)
    return ObservationState(latest[0].value, f"observation:{key}", latest)


def completion_state(completions: Iterable[Completion], action_id: str, age: float) -> str | None:
    """``"done"``, ``"not_done"`` or ``None`` (unknown, including same-time conflicts)."""
    visible = [c for c in completions if c.action_id == action_id and c.recorded_at_months <= age]
    if not visible:
        return None
    latest_time = max(c.recorded_at_months for c in visible)
    states = {c.status for c in visible if c.recorded_at_months == latest_time}
    return states.pop() if len(states) == 1 else None


def validate_horizon(horizon_months: object) -> float:
    horizon = as_months(horizon_months, "horizon_months")
    if not 0 < horizon <= MAX_HORIZON_MONTHS:
        raise SCACareError(f"must be greater than 0 and at most {MAX_HORIZON_MONTHS:g}", field="horizon_months")
    return horizon


def _check_completions_against_pack(history: PatientHistory, pack: EvidencePack) -> None:
    slots = {rule.slot_id(m): m for rule in pack.rules if rule.kind == "schedule" for m in rule.ages_months}
    for c in history.completions:
        milestone = slots.get(c.action_id)
        if milestone is not None and c.status == "done" and c.recorded_at_months < milestone:
            raise HistoryError(
                f"'{c.action_id}' marked done at {c.recorded_at_months:g} months; "
                "early screening cannot complete a later age slot",
                field="completions",
            )


@dataclass
class _PlanBuilder:
    """Mutable scratchpad used while one plan is assembled."""

    history: PatientHistory
    pack: EvidencePack
    supported_end: float
    actions: list[Action] = field(default_factory=list)
    pending: list[Action] = field(default_factory=list)
    trace: list[TraceEntry] = field(default_factory=list)
    withheld: list[Withheld] = field(default_factory=list)
    blocked: dict[str, tuple[set[str], int]] = field(default_factory=dict)

    @property
    def age(self) -> float:
        return self.history.age_months

    def note(self, subject: str, result: str, *, slot: bool = False) -> None:
        log.debug("%s -> %s", subject, result)
        self.trace.append(TraceEntry(subject, result, slot))

    def ask(self, field_name: str, action_id: str, priority: int) -> None:
        ids, best = self.blocked.get(field_name, (set(), 0))
        ids.add(action_id)
        self.blocked[field_name] = (ids, max(best, priority))

    def emit(
        self,
        rule: Rule,
        action_id: str,
        due_age: float,
        priority: PriorityClass,
        missing: tuple[str, ...] = (),
        used: tuple[Observation, ...] = (),
    ) -> None:
        item = Action(
            action_id=action_id,
            rule_id=rule.id,
            rule_version=rule.version,
            domain=rule.domain,
            action=rule.action,
            reason=rule.reason,
            priority=priority,
            due_age_months=due_age,
            due_in_months=max(0.0, due_age - self.age),
            overdue_months=max(0.0, self.age - due_age),
            status="verify_before_recommending" if missing else "candidate_for_clinician_review",
            evidence=tuple(self.pack.evidence_for(rule)),
            rule_review_status=rule.review_status,
            observations_used=tuple(o.to_dict() for o in used),
            missing=missing,
        )
        log.debug("%s -> %s (%s)", action_id, item.status, priority.label)
        (self.pending if missing else self.actions).append(item)
        for key in missing:
            self.ask(key, action_id, int(priority))

    # Rule kinds -----------------------------------------------------------

    def observation_rule(self, rule: Rule) -> None:
        states = [observation_state(self.history.observations, c.feature, self.age) for c in rule.conditions]
        clause_truths = [
            s.truth if s.value is None else Truth.of(s.value == c.expected)
            for s, c in zip(states, rule.conditions, strict=True)
        ]
        verdict = all_of(clause_truths)
        used = tuple(o for s in states for o in s.used)
        if verdict is Truth.FALSE:
            self.note(rule.id, "trigger_explicitly_false")
        elif verdict is Truth.UNKNOWN:
            missing = tuple(s.field for s, t in zip(states, clause_truths, strict=True) if t is Truth.UNKNOWN)
            self.emit(rule, rule.id, self.age, PriorityClass.REVIEW, missing, used)
        else:
            self.emit(rule, rule.id, self.age, PriorityClass.REVIEW, used=used)

    def schedule_rule(self, rule: Rule) -> None:
        past = [m for m in rule.ages_months if m <= self.age]
        latest_past = max(past) if past else None
        for milestone in rule.ages_months:
            slot = rule.slot_id(milestone)
            if milestone < self.age and milestone != latest_past:
                self.note(slot, "older_slot_collapsed_into_latest_catch_up_review", slot=True)
                continue
            if milestone > self.supported_end:
                continue
            if milestone > self.age:
                self.emit(rule, slot, milestone, PriorityClass.SCHEDULED)
                continue
            state = completion_state(self.history.completions, slot, self.age)
            if state == "done":
                self.note(slot, "completed", slot=True)
            elif state == "not_done":
                self.emit(rule, slot, milestone, PriorityClass.DUE)
            else:
                self.emit(rule, slot, milestone, PriorityClass.DUE, (f"completion:{slot}",))

    def apply(self, rule: Rule) -> None:
        karyotype = self.history.karyotype
        if not rule.covers_age(self.age):
            self.note(rule.id, "outside_age_range")
            return
        if rule.karyotypes:
            if karyotype not in rule.karyotypes:
                self.note(rule.id, "karyotype_not_matched")
                return
            if self.history.karyotype_status != "confirmed":
                self.withheld.append(Withheld(rule.id, "The supplied karyotype has no diagnostic confirmation"))
                self.ask(CONFIRMATION_FIELD, rule.id, int(PriorityClass.REVIEW))
                log.debug("%s -> withheld pending confirmation", rule.id)
                return
        if rule.kind == "observation":
            self.observation_rule(rule)
        else:
            self.schedule_rule(rule)

    def questions(self) -> tuple[Question, ...]:
        found = [Question(k, tuple(sorted(ids)), best) for k, (ids, best) in self.blocked.items()]
        return tuple(sorted(found, key=Question.sort_key))


def evaluate_plan(
    history: PatientHistory | Mapping[str, Any],
    pack: EvidencePack | Mapping[str, Any] | None = None,
    horizon_months: float = MAX_HORIZON_MONTHS,
) -> CarePlan:
    """Turn one documented history into ranked, evidence-linked care candidates.

    Args:
        history: a :class:`PatientHistory` or the equivalent JSON mapping.
        pack: an :class:`EvidencePack`, a raw pack mapping, or ``None`` for the bundled US seed pack.
        horizon_months: look-ahead window, greater than 0 and at most 24.

    Returns:
        A :class:`CarePlan`. ``risk_probability`` is always ``None`` in 0.x.

    Raises:
        HistoryError: malformed history. PackError: malformed pack. Both subclass ``ValueError``.
    """
    history = PatientHistory.coerce(history)
    pack = EvidencePack.coerce(pack)
    horizon = validate_horizon(horizon_months)
    _check_completions_against_pack(history, pack)

    age = history.age_months
    requested_end = age + horizon
    supported_end = min(requested_end, pack.max_age_months)
    warnings: list[str] = []
    if requested_end > pack.max_age_months:
        warnings.append("Part of the requested horizon exceeds the seed pack's age coverage")
    if any(not o.is_visible_at(age) for o in history.observations) or any(
        c.recorded_at_months > age for c in history.completions
    ):
        warnings.append("Future observations/completion records were excluded from the snapshot")
    warnings += [f"{name} is not interpreted by this seed pack" for name in history.uninterpreted]

    header: dict[str, Any] = {
        "age_months": age,
        "pack_id": pack.id,
        "pack_version": pack.version,
        "pack_sha256": pack.sha256,
        "evidence_review_date": pack.review_date,
        "scope_notes": pack.scope,
        "requested_horizon_months": horizon,
        "requested_end_age_months": requested_end,
        "seed_pack_end_age_months": max(age, supported_end),
    }
    if history.jurisdiction != pack.jurisdiction:
        warnings.append("No matching jurisdiction pack; no recommendations generated")
        return CarePlan(**header, warnings=tuple(warnings))
    if age > pack.max_age_months:
        warnings.append("Current age is outside seed pack coverage; no recommendations generated")
        return CarePlan(**header, warnings=tuple(warnings))
    if history.karyotype not in pack.supported_karyotypes:
        warnings.append("No SCA-specific coverage for this karyotype; general rules only")

    builder = _PlanBuilder(history, pack, supported_end)
    for rule in pack.rules:
        builder.apply(rule)

    return CarePlan(
        **header,
        actions=tuple(sorted(builder.actions, key=Action.sort_key)),
        needs_information=tuple(sorted(builder.pending, key=Action.sort_key)),
        questions=builder.questions(),
        withheld=tuple(builder.withheld),
        trace=tuple(builder.trace),
        warnings=tuple(warnings),
    )
