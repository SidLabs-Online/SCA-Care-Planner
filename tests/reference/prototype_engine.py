# Frozen copy of the 0.1.0 prototype engine. Used only by test_differential.py
# to prove the 0.2 library reproduces its behaviour. Do not edit.
# ruff: noqa
# mypy: ignore-errors
"""Original, dependency-free reference implementation for research review.

This evaluates a small, explicitly incomplete evidence pack. It is not an
emergency triage system, diagnostic model, or validated clinical product.
Age is expressed in months; the host supplies clinically appropriate validity
windows and verifies the underlying observations and completion records.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path


def load_pack(path=None):
    return json.loads(Path(path).read_text())


def number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be finite and nonnegative")
    return float(value)


def observation_state(observations, key, age):
    """Newest visible observation wins; stale/conflicting values are unknown."""
    visible = [o for o in observations if o["key"] == key and o["observed_at_months"] <= age]
    if not visible:
        return None, f"observation:{key}", []
    latest_time = max(o["observed_at_months"] for o in visible)
    latest = [o for o in visible if o["observed_at_months"] == latest_time]
    if len({o["value"] for o in latest}) != 1:
        return None, f"conflicting_observation:{key}", latest
    if any(o["valid_until_months"] < age for o in latest):
        return None, f"stale_observation:{key}", latest
    return latest[0]["value"], f"observation:{key}", latest


def completion_state(completions, action_id, age):
    visible = [c for c in completions if c["action_id"] == action_id and c["recorded_at_months"] <= age]
    if not visible:
        return None
    latest_time = max(c["recorded_at_months"] for c in visible)
    states = {c["status"] for c in visible if c["recorded_at_months"] == latest_time}
    return next(iter(states)) if len(states) == 1 else None


def evaluate_plan(patient, pack=None, horizon_months=24):
    pack = load_pack() if pack is None else pack
    age = number(patient["age_months"], "age_months")
    horizon = number(horizon_months, "horizon_months")
    if not 0 < horizon <= 24:
        raise ValueError("horizon_months must be greater than 0 and at most 24")
    observations = patient.get("observations", [])
    completions = patient.get("completions", [])
    for o in observations:
        if type(o.get("value")) is not bool:
            raise ValueError("Observation values must be explicit true or false")
        at = number(o["observed_at_months"], "observed_at_months")
        until = number(o["valid_until_months"], "valid_until_months")
        if until < at or not o.get("key") or not o.get("source"):
            raise ValueError("Observation needs a key, source and valid time window")
    for c in completions:
        if c.get("status") not in {"done", "not_done"}:
            raise ValueError("Completion status must be done or not_done; omit unknowns")
        number(c["recorded_at_months"], "recorded_at_months")
        if not c.get("action_id") or not c.get("source"):
            raise ValueError("Completion records need an action_id and source")
        for rule in pack["rules"]:
            if rule["kind"] == "schedule":
                for milestone in rule["ages_months"]:
                    if (
                        c["action_id"] == f"{rule['id']}:{milestone}"
                        and c["status"] == "done"
                        and c["recorded_at_months"] < milestone
                    ):
                        raise ValueError("Early screening cannot automatically complete a later age slot")
    requested_end = age + horizon
    supported_end = min(requested_end, pack["max_age_months"])
    warnings = []
    if requested_end > pack["max_age_months"]:
        warnings.append("Part of the requested horizon exceeds the seed pack's age coverage")
    if any(o["observed_at_months"] > age for o in observations) or any(
        c["recorded_at_months"] > age for c in completions
    ):
        warnings.append("Future observations/completion records were excluded from the snapshot")
    for unsupported in ("legacy_n_score", "measurements", "medications", "genomic_files"):
        if unsupported in patient:
            warnings.append(f"{unsupported} is not interpreted by this seed pack")
    canonical = json.dumps(pack, sort_keys=True, separators=(",", ":"))
    result = {
        "status": "research_prototype",
        "pack_id": pack["id"],
        "pack_version": pack["version"],
        "pack_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
        "evidence_review_date": pack["review_date"],
        "clinical_validation": "not_performed",
        "complete_care_coverage": False,
        "scope_notes": pack["scope"],
        "requested_horizon_months": horizon,
        "requested_end_age_months": requested_end,
        "seed_pack_end_age_months": max(age, supported_end),
        "risk_probability": None,
        "risk_probability_status": "not_estimated",
        "actions": [],
        "needs_information": [],
        "questions": [],
        "withheld": [],
        "trace": [],
        "warnings": warnings,
    }
    if patient.get("jurisdiction") != pack["jurisdiction"]:
        warnings.append("No matching jurisdiction pack; no recommendations generated")
        return result
    if age > pack["max_age_months"]:
        warnings.append("Current age is outside seed pack coverage; no recommendations generated")
        return result
    karyotype = patient.get("karyotype", "unknown")
    if karyotype not in pack["supported_karyotypes"]:
        warnings.append("No SCA-specific coverage for this karyotype; general US rules only")
    priorities = {"review": 3, "due": 2, "scheduled": 1}
    questions = defaultdict(lambda: {"affected_actions": set(), "priority": 0})

    def add_question(key, action_id, priority):
        questions[key]["affected_actions"].add(action_id)
        questions[key]["priority"] = max(questions[key]["priority"], priority)

    def emit(rule, action_id, due_age, priority, missing=(), observations_used=()):
        entry = {
            "action_id": action_id,
            "domain": rule["domain"],
            "action": rule["action"],
            "due_age_months": due_age,
            "due_in_months": max(0, due_age - age),
            "overdue_months": max(0, age - due_age),
            "priority_class": priority,
            "priority_key": [priorities[priority], -due_age],
            "rule_id": rule["id"],
            "rule_version": rule["version"],
            "evidence": [pack["sources"][s] for s in rule["sources"]],
            "rule_review_status": rule["review_status"],
            "reason": rule["reason"],
            "observations_used": list(observations_used),
        }
        if missing:
            entry["status"] = "verify_before_recommending"
            entry["missing"] = list(missing)
            result["needs_information"].append(entry)
            for key in missing:
                add_question(key, action_id, priorities[priority])
        else:
            entry["status"] = "candidate_for_clinician_review"
            result["actions"].append(entry)

    for rule in pack["rules"]:
        if not rule["min_age_months"] <= age <= rule["max_age_months"]:
            result["trace"].append({"rule_id": rule["id"], "result": "outside_age_range"})
            continue
        if rule.get("karyotypes"):
            if karyotype not in rule["karyotypes"]:
                result["trace"].append({"rule_id": rule["id"], "result": "karyotype_not_matched"})
                continue
            if patient.get("karyotype_status") != "confirmed":
                result["withheld"].append(
                    {"rule_id": rule["id"], "reason": "The supplied karyotype has no diagnostic confirmation"}
                )
                add_question("confirmation_of_existing_genetic_report", rule["id"], 3)
                continue
        if rule["kind"] == "observation":
            value, missing_key, used = observation_state(observations, rule["feature"], age)
            if value is None:
                emit(rule, rule["id"], age, "review", [missing_key], used)
            elif value == rule["expected"]:
                emit(rule, rule["id"], age, "review", observations_used=used)
            else:
                result["trace"].append({"rule_id": rule["id"], "result": "trigger_explicitly_false"})
        elif rule["kind"] == "schedule":
            past = [m for m in rule["ages_months"] if m <= age]
            latest_past = max(past) if past else None
            for milestone in rule["ages_months"]:
                action_id = f"{rule['id']}:{milestone}"
                if milestone < age and milestone != latest_past:
                    result["trace"].append(
                        {"action_id": action_id, "result": "older_slot_collapsed_into_latest_catch_up_review"}
                    )
                    continue
                if milestone > supported_end:
                    continue
                if milestone > age:
                    emit(rule, action_id, milestone, "scheduled")
                    continue
                state = completion_state(completions, action_id, age)
                if state == "done":
                    result["trace"].append({"action_id": action_id, "result": "completed"})
                elif state == "not_done":
                    emit(rule, action_id, milestone, "due")
                else:
                    emit(rule, action_id, milestone, "due", [f"completion:{action_id}"])
        else:
            raise ValueError(f"Unsupported rule kind: {rule['kind']}")
    for category in ("actions", "needs_information"):
        result[category].sort(key=lambda a: (-a["priority_key"][0], a["due_age_months"], a["action_id"]))
    result["questions"] = [
        {
            "field": key,
            "affected_action_ids": sorted(v["affected_actions"]),
            "potential_priority": v["priority"],
            "affected_count": len(v["affected_actions"]),
        }
        for key, v in questions.items()
    ]
    result["questions"].sort(key=lambda q: (-q["potential_priority"], -q["affected_count"], q["field"]))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("patient_json")
    parser.add_argument("--pack")
    parser.add_argument("--horizon", type=float, default=24)
    args = parser.parse_args()
    patient = json.loads(Path(args.patient_json).read_text())
    print(json.dumps(evaluate_plan(patient, load_pack(args.pack), args.horizon), indent=2))


if __name__ == "__main__":
    main()
