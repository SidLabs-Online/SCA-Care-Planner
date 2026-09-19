"""Five-minute tour. Run from the repository root:  python examples/quickstart.py"""

from pathlib import Path

import sca_care_planner as scp

history = scp.read_history(Path(__file__).with_name("child_22_months.json"))

# 1. The plan: ranked candidates, each with rule and evidence attached.
plan = scp.evaluate_plan(history)
for action in plan.all_actions:
    state = "verify" if action.needs_information else action.priority.label
    print(f"{action.key}  {state:9}  {action.action_id}")

# 2. Why is one item here?
print()
print(scp.explain_action(plan, "autism_screen:18"))

# 3. Which unanswered question would move the plan, and how?
print()
for impact in scp.question_impact(history):
    for outcome in impact.outcomes:
        print(f"if {impact.field} = {next(iter(outcome.answers.values()))!r}:")
        print("   " + str(outcome.diff).replace("\n", "\n   "))

# 4. What will the plan ask for over the next 24 months if nothing new is recorded?
print()
for event in scp.predict_care(history):
    print(f"{event.age_months:>5g} mo  {event.action_id:32} {event.previous_state or '':>9} -> {event.state}")

# 5. The evidence graph, ready to paste into a GitHub comment.
print()
print(scp.make_graph(plan).to_mermaid())
