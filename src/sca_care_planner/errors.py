# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Sidhartha Mitra, SidLabs Online LLP. See NOTICE.
"""Exception types.

Every error raised on bad input subclasses :class:`ValueError`, so existing
``except ValueError`` code keeps working. Each error carries a ``field`` so a
caller (or a researcher reading a stack trace) can see which part of the input
was rejected without parsing the message.
"""

from __future__ import annotations


class SCACareError(ValueError):
    """Base class for all input and evidence-pack errors raised by this library."""

    def __init__(self, message: str, *, field: str | None = None) -> None:
        self.field = field
        super().__init__(f"{field}: {message}" if field else message)


class HistoryError(SCACareError):
    """The patient history is malformed or internally inconsistent."""


class PackError(SCACareError):
    """The evidence pack is malformed, references missing sources, or uses an unknown rule kind."""
