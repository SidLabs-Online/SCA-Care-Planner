# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Sidhartha Mitra, SidLabs Online LLP. See NOTICE.
"""Human-readable output.

``explain_action`` traces one action to its rule, evidence and inputs.
``summarize`` renders a whole plan as Markdown for a lab notebook, a pull
request or a clinician review packet. Both read only the plan object.
"""

from __future__ import annotations

from .plan import Action, CarePlan

_STATE_TEXT = {
    "review": "Current review candidate",
    "due": "Due care (explicitly not done)",
    "scheduled": "Scheduled within the horizon",
    "verify": "Needs verification before it can be suggested",
}


def _state(a: Action) -> str:
    return "verify" if a.needs_information else a.priority.label


def _age(months: float) -> str:
    return f"{months:g} mo"


def explain_action(plan: CarePlan, action_id: str) -> str:
    """Plain-text trace for one action. Raises ``KeyError`` if the id is not in the plan."""
    a = plan.action(action_id)
    lines = [
        f"{a.action_id}  [{_STATE_TEXT[_state(a)]}]",
        f"  do:        {a.action}",
        f"  why:       {a.reason}",
        f"  target:    {_age(a.due_age_months)}"
        + (f" (overdue by {_age(a.overdue_months)})" if a.overdue_months else f" (in {_age(a.due_in_months)})"),
        f"  priority:  P(a) = (c={int(a.priority)}, -d={-a.due_age_months:g})  workflow order, not risk",
        f"  rule:      {a.rule_id} v{a.rule_version} ({a.rule_review_status})",
    ]
    for ev in a.evidence:
        locator = f", {ev['locator']}" if ev.get("locator") else ""
        lines.append(f"  evidence:  [{ev.get('id')}] {ev.get('title')}{locator} <{ev.get('url')}>")
    for obs in a.observations_used:
        lines.append(
            f"  used:      {obs['key']}={obs['value']} at {_age(obs['observed_at_months'])}, "
            f"valid to {_age(obs['valid_until_months'])} ({obs['source']})"
        )
    for field in a.missing:
        lines.append(f"  missing:   {field}")
    return "\n".join(lines)


def summarize(plan: CarePlan) -> str:
    """Markdown report of the whole plan."""
    out = [
        f"# Care plan at {_age(plan.age_months)}",
        "",
        f"Pack `{plan.pack_id}` v{plan.pack_version}, evidence reviewed {plan.evidence_review_date}, "
        f"sha256 `{plan.pack_sha256[:12]}`. Horizon to {_age(plan.requested_end_age_months)}; "
        f"pack covers to {_age(plan.seed_pack_end_age_months)}.",
        "",
        "Research prototype. Clinical validation: not performed. Risk probability: not estimated.",
    ]
    if plan.warnings:
        out += ["", "## Warnings", ""] + [f"- {w}" for w in plan.warnings]
    for title, items in (("Care candidates", plan.actions), ("Needs verification", plan.needs_information)):
        if not items:
            continue
        out += ["", f"## {title}", "", "| # | Action id | State | Target | Evidence |", "|---|---|---|---|---|"]
        for i, a in enumerate(items, 1):
            ev = ", ".join(str(e.get("id")) for e in a.evidence)
            out.append(f"| {i} | `{a.action_id}` | {_state(a)} | {_age(a.due_age_months)} | {ev} |")
    if plan.questions:
        out += ["", "## Questions that could change the plan", ""]
        for i, q in enumerate(plan.questions, 1):
            out.append(f"{i}. `{q.field}` blocks {q.affected_count} item(s): {', '.join(q.affected_action_ids)}")
    if plan.withheld:
        out += ["", "## Withheld", ""] + [f"- `{w.rule_id}`: {w.reason}" for w in plan.withheld]
    return "\n".join(out) + "\n"
