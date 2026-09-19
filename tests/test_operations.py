"""predict_care, what_if, question_impact, compare_plans, make_graph, explain, CLI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from conftest import child, done, obs
from sca_care_planner import (
    SCACareError,
    compare_plans,
    evaluate_plan,
    explain_action,
    make_graph,
    predict_care,
    question_impact,
    read_history,
    summarize,
    what_if,
)
from sca_care_planner.cli import main

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "child_22_months.json"


@pytest.fixture
def example() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(EXAMPLE.read_text())
    return data


# predict_care ------------------------------------------------------------------------


def test_timeline_worked_example(example: dict[str, Any]) -> None:
    tl = predict_care(example)
    assert (tl.start_age_months, tl.end_age_months) == (22, 46)
    assert tl.risk_probability is None
    changes = {(e.action_id, e.age_months): e.state for e in tl}
    # The concern was observed at 22 and valid only at 22, so it needs re-checking at 23.
    assert changes[("developmental_concern_review", 23.0)] == "verify"
    # Autism screen at 24 turns from scheduled to "record whether it happened".
    assert changes[("autism_screen:24", 24.0)] == "verify"
    # Screening rules stop at 36 months, so open slots leave the plan at 37.
    assert changes[("developmental_screen:30", 37.0)] == "ends"


def test_timeline_snapshot_lookup(example: dict[str, Any]) -> None:
    tl = predict_care(example, horizon_months=6)
    assert tl.at(24.5).age_months == 24
    with pytest.raises(KeyError):
        tl.at(10)
    assert all(row["age_months"] <= 28 for row in tl.to_rows())


def test_timeline_uses_no_future_records(example: dict[str, Any]) -> None:
    example["completions"].append(done("autism_screen:24", 25))
    tl = predict_care(example, horizon_months=6)
    assert not any(e.action_id == "autism_screen:24" and e.state == "ends" for e in tl)
    assert tl.excluded_future_records == 1


# what_if / question_impact ------------------------------------------------------------


def test_what_if_completion_resolves_question() -> None:
    result = what_if(child(), {"completion:autism_screen:18": "done"})
    assert "completion:autism_screen:18" in result.diff.questions_resolved
    assert "autism_screen:18" not in result.plan.ids()


def test_what_if_not_done_makes_care_due() -> None:
    result = what_if(child(), {"completion:autism_screen:18": False})
    assert [str(c) for c in result.diff.changes] == ["autism_screen:18: verify -> due"]


def test_what_if_replaces_same_age_conflict() -> None:
    conflicted = child(observations=[obs("developmental_concern", True), obs("developmental_concern", False)])
    result = what_if(conflicted, {"conflicting_observation:developmental_concern": True})
    assert result.plan.action("developmental_concern_review").status == "candidate_for_clinician_review"


def test_what_if_confirmation_releases_withheld_rule() -> None:
    history = child(
        karyotype_status="screen_positive", observations=[obs("developmental_followup_plan_in_place", False)]
    )
    result = what_if(history, {"confirmation_of_existing_genetic_report": True})
    assert "xxy_support_plan_review" in result.plan.ids("actions")


@pytest.mark.parametrize(
    ("field", "answer"),
    [("observation:x", "yes"), ("completion:autism_screen:18", "maybe"), ("mystery", True)],
)
def test_what_if_rejects_bad_answers(field: str, answer: Any) -> None:
    with pytest.raises(SCACareError):
        what_if(child(), {field: answer})


def test_question_impact_covers_every_question() -> None:
    impacts = question_impact(child())
    assert [i.field for i in impacts] == [q.field for q in evaluate_plan(child()).questions]
    assert all(len(i.outcomes) == 2 and i.max_changes >= 1 for i in impacts)


def test_compare_detects_pack_change(pack_dict: dict[str, Any]) -> None:
    before = evaluate_plan(child(), pack_dict)
    pack_dict["rules"] = [r for r in pack_dict["rules"] if r["id"] != "autism_screen"]
    diff = compare_plans(before, evaluate_plan(child(), pack_dict))
    assert diff.fingerprint_changed
    assert {c.action_id for c in diff.of_kind("removed")} == {"autism_screen:18", "autism_screen:24"}
    assert str(compare_plans(before, before)) == "no change"


# make_graph ---------------------------------------------------------------------------


def test_graph_links_every_action_to_a_source(example: dict[str, Any], pack: Any) -> None:
    plan = evaluate_plan(example)
    graph = make_graph(plan, pack)
    for action_id in plan.ids():
        assert graph.why(action_id), action_id
    assert graph.why("developmental_concern_review") == ["source:AAP2020"]
    assert "observation:developmental_concern@22" in graph.neighbours("action:developmental_concern_review")


def test_graph_withheld_rule_is_blocked_by_confirmation(pack: Any) -> None:
    plan = evaluate_plan(child(karyotype_status="screen_positive"))
    graph = make_graph(plan, pack)
    assert graph.node("rule:xxy_support_plan_review").attrs["state"] == "withheld"
    assert "question:confirmation_of_existing_genetic_report" in graph.neighbours("rule:xxy_support_plan_review")
    assert "source:EAA2020" in graph.neighbours("rule:xxy_support_plan_review", "supports")


def test_graph_exports(example: dict[str, Any]) -> None:
    graph = make_graph(evaluate_plan(example))
    assert graph.to_dot().startswith("digraph care_plan {")
    assert graph.to_mermaid().startswith("flowchart LR")
    data = json.loads(graph.to_json())
    assert (len(data["nodes"]), len(data["links"])) == (len(graph.nodes), len(graph.edges))


def test_graph_networkx_round_trip(example: dict[str, Any]) -> None:
    nx = pytest.importorskip("networkx")
    g = make_graph(evaluate_plan(example)).to_networkx()
    assert nx.is_directed_acyclic_graph(g)


# explain / summarize ------------------------------------------------------------------


def test_explain_action_shows_formula_and_source(example: dict[str, Any]) -> None:
    text = explain_action(evaluate_plan(example), "autism_screen:18")
    assert "P(a) = (c=2, -d=-18)" in text
    assert "missing:   completion:autism_screen:18" in text
    assert "[CDC2026]" in text


def test_summary_is_markdown(example: dict[str, Any]) -> None:
    text = summarize(evaluate_plan(example))
    assert text.startswith("# Care plan at 22 mo")
    assert "## Questions that could change the plan" in text


def test_read_history() -> None:
    assert read_history(EXAMPLE).age_months == 22


# CLI ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        [str(EXAMPLE)],
        ["plan", str(EXAMPLE), "--horizon", "6"],
        ["summary", str(EXAMPLE)],
        ["explain", str(EXAMPLE), "--action", "autism_screen:24"],
        ["questions", str(EXAMPLE)],
        ["timeline", str(EXAMPLE)],
        ["graph", str(EXAMPLE), "--format", "dot"],
        ["packs"],
        ["validate", "--pack", "us_development_seed"],
    ],
)
def test_cli_commands(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    assert main(argv) == 0
    assert capsys.readouterr().out.strip()


def test_cli_reports_bad_input(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(child(-3)))
    assert main(["plan", str(bad)]) == 2
    assert "age_months" in capsys.readouterr().err


def test_cli_no_command_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert "sca-care" in capsys.readouterr().out
