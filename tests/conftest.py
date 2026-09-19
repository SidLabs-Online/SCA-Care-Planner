from __future__ import annotations

from typing import Any

import pytest

from sca_care_planner import EvidencePack, load_pack
from sca_care_planner.evidence import load_pack_dict


def child(age: float = 22, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "age_months": age,
        "jurisdiction": "US",
        "karyotype": "47,XXY",
        "karyotype_status": "confirmed",
        "observations": [],
        "completions": [],
    }
    base.update(overrides)
    return base


def obs(key: str, value: bool, at: float = 22, until: float = 22) -> dict[str, Any]:
    return {"key": key, "value": value, "observed_at_months": at, "valid_until_months": until, "source": "synthetic"}


def done(action_id: str, at: float, status: str = "done") -> dict[str, Any]:
    return {"action_id": action_id, "status": status, "recorded_at_months": at, "source": "synthetic"}


@pytest.fixture(scope="session")
def pack() -> EvidencePack:
    return load_pack()


@pytest.fixture
def pack_dict() -> dict[str, Any]:
    return load_pack_dict()
