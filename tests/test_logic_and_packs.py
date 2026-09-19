from __future__ import annotations

import itertools
import json
from pathlib import Path
from typing import Any

import pytest

from conftest import child, obs
from sca_care_planner import EvidencePack, PackError, Truth, all_of, any_of, available_packs, evaluate_plan, load_pack

T, F, U = Truth.TRUE, Truth.FALSE, Truth.UNKNOWN


# Kleene logic -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("a", "b", "conj", "disj"),
    [(T, T, T, T), (T, F, F, T), (T, U, U, T), (F, F, F, F), (F, U, F, U), (U, U, U, U)],
)
def test_kleene_tables(a: Truth, b: Truth, conj: Truth, disj: Truth) -> None:
    assert (a & b) is conj
    assert (b & a) is conj
    assert (a | b) is disj
    assert (b | a) is disj


def test_de_morgan_holds_for_all_values() -> None:
    for a, b in itertools.product(Truth, repeat=2):
        assert ~(a & b) is (~a | ~b)


def test_empty_and_or() -> None:
    assert all_of([]) is T
    assert any_of([]) is F


def test_truth_refuses_implicit_bool() -> None:
    with pytest.raises(TypeError):
        bool(U)


# Pack validation ----------------------------------------------------------------


def test_bundled_pack_loads(pack: EvidencePack) -> None:
    assert "us_development_seed" in available_packs()
    assert len(pack.rules) == 5
    assert all(r.sources for r in pack.rules)


def test_pack_loads_from_path(tmp_path: Path, pack_dict: dict[str, Any]) -> None:
    path = tmp_path / "pack.json"
    path.write_text(json.dumps(pack_dict))
    assert load_pack(path).sha256 == load_pack().sha256


def test_missing_pack_path() -> None:
    with pytest.raises(PackError, match="no bundled pack"):
        load_pack("does/not/exist.json")


def test_pack_errors_are_collected(pack_dict: dict[str, Any]) -> None:
    pack_dict["rules"][0]["sources"] = ["NOPE"]
    pack_dict["rules"][1]["kind"] = "magic"
    pack_dict["rules"][2]["id"] = pack_dict["rules"][3]["id"]
    with pytest.raises(PackError) as info:
        EvidencePack.from_dict(pack_dict)
    message = str(info.value)
    assert "unknown source 'NOPE'" in message
    assert "unsupported rule kind 'magic'" in message
    assert "duplicates rule id" in message


def test_rule_without_sources_rejected(pack_dict: dict[str, Any]) -> None:
    pack_dict["rules"][0]["sources"] = []
    with pytest.raises(PackError, match="cites no source"):
        EvidencePack.from_dict(pack_dict)


def test_missing_pack_keys(pack_dict: dict[str, Any]) -> None:
    del pack_dict["jurisdiction"]
    with pytest.raises(PackError, match="jurisdiction"):
        EvidencePack.from_dict(pack_dict)


# Compound triggers (``when``) --------------------------------------------------------


@pytest.fixture
def compound_pack(pack_dict: dict[str, Any]) -> dict[str, Any]:
    rule = dict(pack_dict["rules"][0])
    rule.pop("feature")
    rule.pop("expected")
    rule.update(
        id="concern_without_plan",
        when=[
            {"feature": "developmental_concern", "expected": True},
            {"feature": "developmental_followup_plan_in_place", "expected": False},
        ],
    )
    pack_dict["rules"] = [rule]
    return pack_dict


def test_compound_rule_true(compound_pack: dict[str, Any]) -> None:
    history = child(
        observations=[obs("developmental_concern", True), obs("developmental_followup_plan_in_place", False)]
    )
    assert evaluate_plan(history, compound_pack).ids("actions") == ["concern_without_plan"]


def test_compound_rule_one_false_clause_silences(compound_pack: dict[str, Any]) -> None:
    history = child(observations=[obs("developmental_followup_plan_in_place", True)])
    plan = evaluate_plan(history, compound_pack)
    assert plan.ids() == []
    assert plan.trace[0].result == "trigger_explicitly_false"


def test_compound_rule_unknown_asks_only_for_missing_clause(compound_pack: dict[str, Any]) -> None:
    history = child(observations=[obs("developmental_concern", True)])
    plan = evaluate_plan(history, compound_pack)
    assert plan.needs_information[0].missing == ("observation:developmental_followup_plan_in_place",)
