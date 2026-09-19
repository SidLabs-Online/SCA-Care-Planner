# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Sidhartha Mitra, SidLabs Online LLP. See NOTICE.
"""SCA Care Planner.

Turns a child's documented findings into evidence-linked care-review
priorities, a monitoring timeline over the next 24 months, and the questions
whose answers would change that plan.

Research software. Not clinically validated. No risk probabilities.

Quick start::

    from sca_care_planner import evaluate_plan, predict_care, make_graph

    plan = evaluate_plan(history_dict)          # CarePlan
    plan.actions[0].evidence                    # every action carries its sources
    predict_care(history_dict).to_rows()        # month-by-month projection
    print(make_graph(plan).to_mermaid())        # why each action exists
"""

from __future__ import annotations

import json
from pathlib import Path

from .compare import PlanDiff, compare_plans
from .engine import evaluate_plan, observation_state
from .errors import HistoryError, PackError, SCACareError
from .evidence import EvidencePack, Rule, available_packs, load_pack
from .explain import explain_action, summarize
from .graph import CareGraph, make_graph
from .history import Completion, Observation, PatientHistory
from .plan import Action, CarePlan, PriorityClass, Question, priority_key
from .timeline import CareTimeline, TimelineEvent, predict_care
from .truth import Truth, all_of, any_of
from .whatif import QuestionImpact, WhatIf, question_impact, what_if

__version__ = "0.2.0"


def read_history(path: str | Path) -> PatientHistory:
    """Load and validate a patient history JSON file."""
    return PatientHistory.from_dict(json.loads(Path(path).read_text("utf-8")))


__all__ = [
    "Action",
    "CareGraph",
    "CarePlan",
    "CareTimeline",
    "Completion",
    "EvidencePack",
    "HistoryError",
    "Observation",
    "PackError",
    "PatientHistory",
    "PlanDiff",
    "PriorityClass",
    "Question",
    "QuestionImpact",
    "Rule",
    "SCACareError",
    "TimelineEvent",
    "Truth",
    "WhatIf",
    "__version__",
    "all_of",
    "any_of",
    "available_packs",
    "compare_plans",
    "evaluate_plan",
    "explain_action",
    "load_pack",
    "make_graph",
    "observation_state",
    "predict_care",
    "priority_key",
    "question_impact",
    "read_history",
    "summarize",
    "what_if",
]
