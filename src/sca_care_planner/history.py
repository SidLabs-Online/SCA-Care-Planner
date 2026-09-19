# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Sidhartha Mitra, SidLabs Online LLP. See NOTICE.
"""Patient history: the input contract.

Ages are in months. The host system supplies every observation with a
validity window and every completion record with a source; this module only
checks that those fields are present and coherent. It never fills a gap with
a default that could look like a clinical finding.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Literal, cast

from .errors import HistoryError

CompletionStatus = Literal["done", "not_done"]

#: Fields a caller may send that version 0.x deliberately does not interpret.
#: They are reported back as warnings so nobody assumes they were used.
UNINTERPRETED_FIELDS: tuple[str, ...] = (
    "legacy_n_score",
    "measurements",
    "medications",
    "genomic_files",
)


def as_months(value: object, name: str) -> float:
    """Return ``value`` as a finite, nonnegative float or raise :class:`HistoryError`."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HistoryError("must be a finite number", field=name)
    if not math.isfinite(value) or value < 0:
        raise HistoryError("must be finite and nonnegative", field=name)
    return float(value)


def _require_text(record: Mapping[str, Any], key: str, where: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise HistoryError("is required and must be a nonempty string", field=f"{where}.{key}")
    return value


@dataclass(frozen=True, slots=True)
class Observation:
    """A dated, explicit true/false finding with a validity window."""

    key: str
    value: bool
    observed_at_months: float
    valid_until_months: float
    source: str

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any], index: int = 0) -> Observation:
        where = f"observations[{index}]"
        if type(raw.get("value")) is not bool:
            raise HistoryError("must be explicit true or false; omit unknowns", field=f"{where}.value")
        at = as_months(raw.get("observed_at_months"), f"{where}.observed_at_months")
        until = as_months(raw.get("valid_until_months"), f"{where}.valid_until_months")
        if until < at:
            raise HistoryError("valid_until_months is earlier than observed_at_months", field=where)
        return cls(
            key=_require_text(raw, "key", where),
            value=raw["value"],
            observed_at_months=at,
            valid_until_months=until,
            source=_require_text(raw, "source", where),
        )

    def is_visible_at(self, age: float) -> bool:
        return self.observed_at_months <= age

    def is_valid_at(self, age: float) -> bool:
        return self.observed_at_months <= age <= self.valid_until_months

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "value": self.value,
            "observed_at_months": self.observed_at_months,
            "valid_until_months": self.valid_until_months,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class Completion:
    """A record that a named care instance was, or was not, done."""

    action_id: str
    status: CompletionStatus
    recorded_at_months: float
    source: str

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any], index: int = 0) -> Completion:
        where = f"completions[{index}]"
        status = raw.get("status")
        if status not in ("done", "not_done"):
            raise HistoryError("must be 'done' or 'not_done'; omit unknowns", field=f"{where}.status")
        return cls(
            action_id=_require_text(raw, "action_id", where),
            status=cast(CompletionStatus, status),
            recorded_at_months=as_months(raw.get("recorded_at_months"), f"{where}.recorded_at_months"),
            source=_require_text(raw, "source", where),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "status": self.status,
            "recorded_at_months": self.recorded_at_months,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class PatientHistory:
    """Everything the engine may look at, frozen at one evaluation age."""

    age_months: float
    jurisdiction: str | None = None
    karyotype: str = "unknown"
    karyotype_status: str = "unknown"
    observations: tuple[Observation, ...] = ()
    completions: tuple[Completion, ...] = ()
    uninterpreted: tuple[str, ...] = field(default=())

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> PatientHistory:
        """Parse and validate a JSON-style mapping. The input is never mutated."""
        if not isinstance(raw, Mapping):
            raise HistoryError("history must be a JSON object")
        observations = raw.get("observations", [])
        completions = raw.get("completions", [])
        if not isinstance(observations, Sequence) or not isinstance(completions, Sequence):
            raise HistoryError("observations and completions must be lists")
        return cls(
            age_months=as_months(raw.get("age_months"), "age_months"),
            jurisdiction=raw.get("jurisdiction"),
            karyotype=raw.get("karyotype", "unknown"),
            karyotype_status=raw.get("karyotype_status", "unknown"),
            observations=tuple(Observation.from_dict(o, i) for i, o in enumerate(observations)),
            completions=tuple(Completion.from_dict(c, i) for i, c in enumerate(completions)),
            uninterpreted=tuple(k for k in UNINTERPRETED_FIELDS if k in raw),
        )

    @classmethod
    def coerce(cls, value: PatientHistory | Mapping[str, Any]) -> PatientHistory:
        return value if isinstance(value, PatientHistory) else cls.from_dict(value)

    # Immutable updates, used by what-if analysis and handy in notebooks.
    def at_age(self, age_months: float) -> PatientHistory:
        return replace(self, age_months=as_months(age_months, "age_months"))

    def with_observation(self, observation: Observation) -> PatientHistory:
        return replace(self, observations=(*self.observations, observation))

    def with_completion(self, completion: Completion) -> PatientHistory:
        return replace(self, completions=(*self.completions, completion))

    def to_dict(self) -> dict[str, Any]:
        return {
            "age_months": self.age_months,
            "jurisdiction": self.jurisdiction,
            "karyotype": self.karyotype,
            "karyotype_status": self.karyotype_status,
            "observations": [o.to_dict() for o in self.observations],
            "completions": [c.to_dict() for c in self.completions],
        }
