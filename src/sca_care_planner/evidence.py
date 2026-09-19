# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Sidhartha Mitra, SidLabs Online LLP. See NOTICE.
"""Evidence packs: versioned, citable rule sets.

A pack is plain JSON so a clinician can review it without reading Python. The
rule vocabulary is deliberately small: no expressions, no imported code. Two
rule kinds exist.

``observation``
    Fires on the current state of one or more named observations. Use either
    ``feature`` + ``expected`` or a ``when`` list of such pairs, combined with
    Kleene AND (see :mod:`sca_care_planner.truth`).

``schedule``
    Emits one care instance per age in ``ages_months``. Instance ids are
    ``"<rule_id>:<age>"``, and completion records refer to those ids.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any, Literal

from .errors import PackError

RuleKind = Literal["observation", "schedule"]

DEFAULT_PACK = "us_development_seed"
_REQUIRED_PACK_KEYS = (
    "id",
    "version",
    "review_date",
    "jurisdiction",
    "max_age_months",
    "supported_karyotypes",
    "scope",
    "sources",
    "rules",
)
_REQUIRED_RULE_KEYS = (
    "id",
    "version",
    "kind",
    "domain",
    "min_age_months",
    "max_age_months",
    "action",
    "reason",
    "sources",
    "review_status",
)


@dataclass(frozen=True, slots=True)
class Condition:
    """One clause of an observation trigger: ``feature`` currently equals ``expected``."""

    feature: str
    expected: bool


@dataclass(frozen=True, slots=True)
class Rule:
    id: str
    version: str
    kind: RuleKind
    domain: str
    min_age_months: float
    max_age_months: float
    action: str
    reason: str
    sources: tuple[str, ...]
    review_status: str
    karyotypes: tuple[str, ...] = ()
    conditions: tuple[Condition, ...] = ()
    ages_months: tuple[float, ...] = ()

    def covers_age(self, age: float) -> bool:
        return self.min_age_months <= age <= self.max_age_months

    def slot_id(self, milestone: float) -> str:
        """Instance id of a scheduled slot. Integral ages print without ``.0``."""
        label = int(milestone) if float(milestone).is_integer() else milestone
        return f"{self.id}:{label}"

    @property
    def features(self) -> tuple[str, ...]:
        return tuple(c.feature for c in self.conditions)


@dataclass(frozen=True, slots=True)
class EvidencePack:
    id: str
    version: str
    review_date: str
    jurisdiction: str
    max_age_months: float
    supported_karyotypes: tuple[str, ...]
    scope: str
    sources: Mapping[str, Mapping[str, Any]]
    rules: tuple[Rule, ...]
    sha256: str

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> EvidencePack:
        """Validate a pack mapping. All structural problems are reported together."""
        problems: list[str] = [f"missing pack key '{k}'" for k in _REQUIRED_PACK_KEYS if k not in raw]
        if problems:
            raise PackError("; ".join(problems))
        sources = raw["sources"]
        rules: list[Rule] = []
        seen: set[str] = set()
        for index, rule_raw in enumerate(raw["rules"]):
            where = f"rules[{index}]"
            missing = [k for k in _REQUIRED_RULE_KEYS if k not in rule_raw]
            if missing:
                problems.append(f"{where} missing {missing}")
                continue
            rule_id = rule_raw["id"]
            if rule_id in seen:
                problems.append(f"{where} duplicates rule id '{rule_id}'")
            seen.add(rule_id)
            problems += [f"{where} cites unknown source '{s}'" for s in rule_raw["sources"] if s not in sources]
            if not rule_raw["sources"]:
                problems.append(f"{where} cites no source; every action needs evidence")
            try:
                rules.append(_parse_rule(rule_raw))
            except (KeyError, TypeError, ValueError) as exc:
                problems.append(f"{where} ({rule_id}): {exc}")
        if problems:
            raise PackError("; ".join(problems))
        return cls(
            id=raw["id"],
            version=raw["version"],
            review_date=raw["review_date"],
            jurisdiction=raw["jurisdiction"],
            max_age_months=float(raw["max_age_months"]),
            supported_karyotypes=tuple(raw["supported_karyotypes"]),
            scope=raw["scope"],
            sources={k: dict(v) for k, v in sources.items()},
            rules=tuple(rules),
            sha256=fingerprint(raw),
        )

    @classmethod
    def coerce(cls, value: EvidencePack | Mapping[str, Any] | None) -> EvidencePack:
        if value is None:
            return load_pack()
        return value if isinstance(value, EvidencePack) else cls.from_dict(value)

    def rule(self, rule_id: str) -> Rule:
        for rule in self.rules:
            if rule.id == rule_id:
                return rule
        raise KeyError(rule_id)

    def evidence_for(self, rule: Rule) -> list[dict[str, Any]]:
        return [dict(self.sources[s]) for s in rule.sources]


def _parse_rule(raw: Mapping[str, Any]) -> Rule:
    kind = raw["kind"]
    lo, hi = float(raw["min_age_months"]), float(raw["max_age_months"])
    if lo > hi:
        raise ValueError("min_age_months exceeds max_age_months")
    conditions: tuple[Condition, ...] = ()
    ages: tuple[float, ...] = ()
    if kind == "observation":
        clauses = raw.get("when") or [{"feature": raw.get("feature"), "expected": raw.get("expected")}]
        for clause in clauses:
            if not isinstance(clause.get("feature"), str) or type(clause.get("expected")) is not bool:
                raise ValueError("observation clauses need a string 'feature' and boolean 'expected'")
        conditions = tuple(Condition(c["feature"], c["expected"]) for c in clauses)
    elif kind == "schedule":
        ages = tuple(sorted(float(a) for a in raw["ages_months"]))
        if not ages:
            raise ValueError("schedule rules need at least one age in 'ages_months'")
    else:
        raise ValueError(f"unsupported rule kind '{kind}'")
    return Rule(
        id=raw["id"],
        version=raw["version"],
        kind=kind,
        domain=raw["domain"],
        min_age_months=lo,
        max_age_months=hi,
        action=raw["action"],
        reason=raw["reason"],
        sources=tuple(raw["sources"]),
        review_status=raw["review_status"],
        karyotypes=tuple(raw.get("karyotypes") or ()),
        conditions=conditions,
        ages_months=ages,
    )


def fingerprint(raw: Mapping[str, Any]) -> str:
    """SHA-256 of the canonical JSON form. Any edit to the evidence changes it."""
    canonical = json.dumps(raw, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def available_packs() -> list[str]:
    """Names of the packs shipped inside the package."""
    folder = resources.files("sca_care_planner") / "packs"
    return sorted(p.name.removesuffix(".json") for p in folder.iterdir() if p.name.endswith(".json"))


def load_pack_dict(source: str | Path | None = None) -> dict[str, Any]:
    """Raw pack JSON, by bundled name or by file path. ``None`` loads the default pack."""
    name = DEFAULT_PACK if source is None else str(source)
    if name in available_packs():
        text = (resources.files("sca_care_planner") / "packs" / f"{name}.json").read_text("utf-8")
    else:
        path = Path(name)
        if not path.is_file():
            raise PackError(f"no bundled pack named '{name}' and no file at that path")
        text = path.read_text("utf-8")
    data: dict[str, Any] = json.loads(text)
    return data


def load_pack(source: str | Path | None = None) -> EvidencePack:
    """Load and validate a pack. See :func:`load_pack_dict` for ``source``."""
    return EvidencePack.from_dict(load_pack_dict(source))
