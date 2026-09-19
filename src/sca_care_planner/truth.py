# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Sidhartha Mitra, SidLabs Online LLP. See NOTICE.
"""Three-valued (Kleene) logic.

A missing record is ``UNKNOWN``, never ``FALSE``. Conjunction is false as soon
as one operand is false, true only when every operand is true, and unknown
otherwise. That single property is what stops an unmeasured feature from
reading as reassurance.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import Enum


class Truth(Enum):
    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"

    @classmethod
    def of(cls, value: bool | None) -> Truth:
        """Map ``True``/``False``/``None`` to a truth value."""
        if value is None:
            return cls.UNKNOWN
        return cls.TRUE if value else cls.FALSE

    def __invert__(self) -> Truth:
        if self is Truth.UNKNOWN:
            return self
        return Truth.FALSE if self is Truth.TRUE else Truth.TRUE

    def __and__(self, other: Truth) -> Truth:
        return all_of((self, other))

    def __or__(self, other: Truth) -> Truth:
        return any_of((self, other))

    def __bool__(self) -> bool:
        raise TypeError("Truth has three values; compare with Truth.TRUE explicitly")


def all_of(values: Iterable[Truth]) -> Truth:
    """Kleene AND. An empty conjunction is ``TRUE``."""
    seen_unknown = False
    for value in values:
        if value is Truth.FALSE:
            return Truth.FALSE
        seen_unknown |= value is Truth.UNKNOWN
    return Truth.UNKNOWN if seen_unknown else Truth.TRUE


def any_of(values: Iterable[Truth]) -> Truth:
    """Kleene OR. An empty disjunction is ``FALSE``."""
    seen_unknown = False
    for value in values:
        if value is Truth.TRUE:
            return Truth.TRUE
        seen_unknown |= value is Truth.UNKNOWN
    return Truth.UNKNOWN if seen_unknown else Truth.FALSE
