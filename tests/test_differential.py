"""Differential test: 0.2 must reproduce the 0.1 prototype on every history.

2,000 seeded random histories go through both engines. Either both reject the
input, or the JSON outputs match field for field. If you change engine
semantics on purpose, update the reference and say so in CHANGELOG.md.
"""

from __future__ import annotations

import random
from typing import Any

import pytest

from reference import prototype_engine
from sca_care_planner import SCACareError, evaluate_plan
from sca_care_planner.evidence import load_pack_dict

KEYS = ("developmental_concern", "developmental_followup_plan_in_place")
SLOTS = {"developmental_screen": (9, 18, 30), "autism_screen": (18, 24)}
KARYOTYPES = ("47,XXY", "47,XXX", "47,XYY", "45,X", "unknown")


def random_history(rng: random.Random) -> tuple[dict[str, Any], float]:
    age = rng.choice([rng.randint(0, 80), rng.randint(0, 80) + 0.5])
    observations = []
    for _ in range(rng.randint(0, 4)):
        at = rng.randint(0, 80)
        observations.append(
            {
                "key": rng.choice(KEYS),
                "value": rng.random() < 0.5,
                "observed_at_months": at,
                "valid_until_months": at + rng.randint(0, 12),
                "source": "fuzz",
            }
        )
    completions = []
    for _ in range(rng.randint(0, 4)):
        rule = rng.choice(list(SLOTS))
        milestone = rng.choice(SLOTS[rule])
        completions.append(
            {
                "action_id": f"{rule}:{milestone}",
                "status": rng.choice(["done", "not_done"]),
                "recorded_at_months": milestone + rng.randint(-2, 10),
                "source": "fuzz",
            }
        )
    history = {
        "age_months": age,
        "jurisdiction": "US" if rng.random() < 0.9 else "IN",
        "karyotype": rng.choice(KARYOTYPES),
        "karyotype_status": rng.choice(["confirmed", "confirmed", "screen_positive"]),
        "observations": observations,
        "completions": [c for c in completions if c["recorded_at_months"] >= 0],
    }
    return history, rng.choice([0.5, 1, 6, 12, 24])


def normalise_new(plan: dict[str, Any]) -> dict[str, Any]:
    plan = dict(plan)
    plan.pop("age_months")
    return plan


def normalise_old(plan: dict[str, Any]) -> dict[str, Any]:
    plan = dict(plan)
    plan["warnings"] = [w.replace("general US rules only", "general rules only") for w in plan["warnings"]]
    return plan


@pytest.mark.parametrize("seed", range(20))
def test_matches_prototype(seed: int) -> None:
    pack = load_pack_dict()
    rng = random.Random(seed)
    compared = 0
    for _ in range(100):
        history, horizon = random_history(rng)
        try:
            expected = normalise_old(prototype_engine.evaluate_plan(history, pack, horizon))
        except ValueError:
            with pytest.raises(SCACareError):
                evaluate_plan(history, pack, horizon)
            continue
        assert normalise_new(evaluate_plan(history, pack, horizon).to_dict()) == expected, history
        compared += 1
    assert compared > 50, "fuzzer produced too few valid histories to mean anything"
