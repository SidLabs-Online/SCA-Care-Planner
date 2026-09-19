"""Engine behaviour. The first 19 tests are the 0.1 prototype suite, ported one to one."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from conftest import child, done, obs
from sca_care_planner import HistoryError, PatientHistory, PriorityClass, evaluate_plan


def test_missing_concern_is_unknown_not_normal() -> None:
    plan = evaluate_plan(child())
    assert "developmental_concern_review" in plan.ids("needs_information")
    assert "developmental_concern_review" not in plan.ids("actions")


def test_explicit_absence_does_not_trigger() -> None:
    plan = evaluate_plan(child(observations=[obs("developmental_concern", False)]))
    assert "developmental_concern_review" not in plan.ids()


def test_current_concern_precedes_scheduled_screen() -> None:
    plan = evaluate_plan(child(observations=[obs("developmental_concern", True)]))
    assert plan.actions[0].action_id == "developmental_concern_review"


def test_completed_screen_does_not_suppress_new_concern() -> None:
    plan = evaluate_plan(
        child(observations=[obs("developmental_concern", True)], completions=[done("developmental_screen:18", 18)])
    )
    assert "developmental_concern_review" in plan.ids()
    assert "developmental_screen:18" not in plan.ids()


def test_unknown_completion_does_not_assert_missed_care() -> None:
    plan = evaluate_plan(child())
    assert "autism_screen:18" in plan.ids("needs_information")
    assert "autism_screen:18" not in plan.ids("actions")


def test_explicitly_missed_screen_is_due() -> None:
    plan = evaluate_plan(child(completions=[done("autism_screen:18", 22, "not_done")]))
    action = plan.action("autism_screen:18")
    assert action.priority is PriorityClass.DUE
    assert action.overdue_months == 4


def test_boundary_and_horizon() -> None:
    plan = evaluate_plan(child(17), horizon_months=1)
    assert "autism_screen:18" in plan.ids("actions")
    assert "autism_screen:24" not in plan.ids("actions")
    assert "autism_screen:18" in evaluate_plan(child(18), horizon_months=1).ids("needs_information")


def test_no_future_information_leakage() -> None:
    plan = evaluate_plan(child(observations=[obs("developmental_concern", True, 23, 24)]))
    assert "developmental_concern_review" not in plan.ids("actions")
    assert any("Future observations" in w for w in plan.warnings)


@pytest.mark.parametrize(
    "observations",
    [
        [obs("developmental_concern", True), obs("developmental_concern", False)],
        [obs("developmental_concern", True, 20, 21)],
    ],
    ids=["conflicting", "stale"],
)
def test_conflicting_and_stale_observations_are_unknown(observations: list[dict[str, Any]]) -> None:
    assert "developmental_concern_review" in evaluate_plan(child(observations=observations)).ids("needs_information")


def test_confirmed_report_required_for_sca_rule() -> None:
    plan = evaluate_plan(
        child(karyotype_status="screen_positive", observations=[obs("developmental_followup_plan_in_place", False)])
    )
    assert "xxy_support_plan_review" not in plan.ids("actions")
    assert plan.withheld
    assert plan.questions[0].field == "confirmation_of_existing_genetic_report"


def test_unknown_variant_does_not_inherit_xxy_rules() -> None:
    plan = evaluate_plan(child(karyotype="45,X/46,XX"))
    assert not any("support_plan" in i for i in plan.ids())
    assert any("No SCA-specific coverage" in w for w in plan.warnings)


def test_legacy_score_has_no_effect_on_priorities() -> None:
    a = evaluate_plan(child(legacy_n_score=0)).actions
    assert a == evaluate_plan(child(legacy_n_score=5)).actions
    assert "legacy_n_score is not interpreted by this seed pack" in evaluate_plan(child(legacy_n_score=5)).warnings


def test_probabilities_are_unavailable_and_sources_present() -> None:
    plan = evaluate_plan(child())
    assert plan.risk_probability is None
    assert plan.to_dict()["risk_probability"] is None
    assert all(a.evidence and a.rule_version for a in plan.all_actions)


def test_jurisdiction_and_age_limits() -> None:
    assert evaluate_plan(child(jurisdiction="IN")).actions == ()
    assert evaluate_plan(child(73)).actions == ()
    assert evaluate_plan(child(60)).seed_pack_end_age_months == 72
    assert evaluate_plan(child(60)).complete_care_coverage is False


@pytest.mark.parametrize("age", [float("nan"), float("inf"), -1, True, "22", None])
def test_invalid_age_rejected(age: object) -> None:
    with pytest.raises(ValueError, match="age_months"):
        evaluate_plan(child(age))  # type: ignore[arg-type]


@pytest.mark.parametrize("horizon", [0, 25, -1])
def test_invalid_horizon_rejected(horizon: float) -> None:
    with pytest.raises(ValueError, match="horizon_months"):
        evaluate_plan(child(), horizon_months=horizon)


def test_old_screen_slots_do_not_create_duplicate_catchup() -> None:
    plan = evaluate_plan(child(31))
    slots = [a.action_id for a in plan.needs_information if a.rule_id == "developmental_screen"]
    assert slots == ["developmental_screen:30"]


def test_early_screen_does_not_complete_a_later_age_slot() -> None:
    with pytest.raises(HistoryError, match="early screening"):
        evaluate_plan(child(completions=[done("autism_screen:18", 9)]))


def test_deterministic_and_input_not_mutated() -> None:
    history = child(observations=[obs("developmental_concern", True)])
    before = copy.deepcopy(history)
    assert evaluate_plan(history) == evaluate_plan(history)
    assert history == before


def test_evidence_change_changes_pack_fingerprint(pack_dict: dict[str, Any]) -> None:
    old = evaluate_plan(child(), pack_dict).pack_sha256
    pack_dict["version"] = "0.1.1"
    assert old != evaluate_plan(child(), pack_dict).pack_sha256


# New in 0.2 -------------------------------------------------------------------


def test_accepts_typed_history_and_dict_equally() -> None:
    raw = child(observations=[obs("developmental_concern", True)])
    assert evaluate_plan(PatientHistory.from_dict(raw)) == evaluate_plan(raw)


@pytest.mark.parametrize(
    ("patch", "field"),
    [
        ({"observations": [{"key": "x", "value": "yes", "observed_at_months": 1, "valid_until_months": 1}]}, "value"),
        ({"observations": [obs("x", True, 5, 4)]}, "observations[0]"),
        ({"observations": [{**obs("x", True), "source": ""}]}, "observations[0].source"),
        ({"completions": [{**done("a", 1), "status": "maybe"}]}, "completions[0].status"),
        ({"completions": [{**done("a", 1), "action_id": None}]}, "completions[0].action_id"),
    ],
)
def test_errors_name_the_offending_field(patch: dict[str, Any], field: str) -> None:
    with pytest.raises(HistoryError) as info:
        evaluate_plan(child(**patch))
    assert info.value.field is not None
    assert field in info.value.field


def test_priority_key_matches_formula() -> None:
    plan = evaluate_plan(child(observations=[obs("developmental_concern", True)]))
    for a in plan.all_actions:
        assert a.key == (int(a.priority), -a.due_age_months)
    keys = [a.key for a in plan.actions]
    assert keys == sorted(keys, reverse=True)


def test_questions_ranked_by_priority_then_count() -> None:
    plan = evaluate_plan(child())
    ranks = [(q.potential_priority, q.affected_count) for q in plan.questions]
    assert ranks == sorted(ranks, reverse=True)


def test_trace_explains_silence() -> None:
    plan = evaluate_plan(child(40))
    results = {t.subject: t.result for t in plan.trace}
    assert results["developmental_screen"] == "outside_age_range"


def test_to_dict_keeps_prototype_keys() -> None:
    keys = set(evaluate_plan(child()).to_dict())
    assert {"actions", "needs_information", "questions", "withheld", "trace", "warnings", "pack_sha256"} <= keys
