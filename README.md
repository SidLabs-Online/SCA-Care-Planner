# SCA Care Planner

[![ci](https://github.com/SidLabs-Online/SCA-Care-Planner/actions/workflows/ci.yml/badge.svg)](https://github.com/SidLabs-Online/SCA-Care-Planner/actions/workflows/ci.yml)
![python](https://img.shields.io/badge/python-3.10%20to%203.13-blue)
![license](https://img.shields.io/badge/license-Apache--2.0-green)
![status](https://img.shields.io/badge/status-research%20software-orange)

A small Python library that reads a child's documented findings and answers three questions for the care team:

1. What should be reviewed now?
2. What monitoring falls due over the next 24 months?
3. Which missing fact would change that plan if we had it?

Every suggested action carries the rule that produced it and the published evidence behind that rule. Anything the record does not say is treated as **unknown**, never as normal. The first evidence pack covers developmental monitoring for children with confirmed 47,XXY, 47,XXX or 47,XYY from birth to 72 months, using US guidance.

> **Research software.** It has not been clinically validated and it is not a medical device. Do not use it for emergency triage. It never outputs a risk percentage: `risk_probability` is always `None`. The ordering it produces is a workflow order for a clinician to review, not a severity score.

The derivation, evidence review and validation plan are in an accompanying white paper, to be published separately. A link will go here once it is out.

## Install

No runtime dependencies. Python 3.10 or newer.

```bash
pip install git+https://github.com/SidLabs-Online/SCA-Care-Planner.git
```

For development:

```bash
git clone https://github.com/SidLabs-Online/SCA-Care-Planner.git
cd SCA-Care-Planner
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## A first run

The repository ships one synthetic child ([`examples/child_22_months.json`](examples/child_22_months.json)): 22 months old with confirmed 47,XXY. There is a current developmental concern and a follow-up plan in place. The 18-month developmental screen is recorded as done, and nothing is recorded about the 18-month autism screen.

```python
import sca_care_planner as scp

history = scp.read_history("examples/child_22_months.json")
plan = scp.evaluate_plan(history)

for a in plan.all_actions:
    print(a.key, a.action_id, a.status)
```

```text
(3, -22.0) developmental_concern_review candidate_for_clinician_review
(1, -24.0) autism_screen:24 candidate_for_clinician_review
(1, -30.0) developmental_screen:30 candidate_for_clinician_review
(2, -18.0) autism_screen:18 verify_before_recommending
```

The concern comes first. The 18-month autism screen is not reported as missed, because nobody said it was missed; it becomes a question instead. The completed developmental screen produces nothing. [`examples/quickstart.py`](examples/quickstart.py) walks through the rest of the API on the same child.

## The operations

| Function | What you get back |
|---|---|
| `evaluate_plan(history, pack=None, horizon_months=24)` | `CarePlan`: ranked actions, items waiting on information, ranked questions, withheld rules, a trace of every silent rule, warnings |
| `predict_care(history, ...)` | `CareTimeline`: month-by-month projection of the plan if nothing new is recorded. Shows when a screen falls due, when an observation goes stale, when coverage ends |
| `what_if(history, {"completion:autism_screen:18": "done"})` | The new plan plus a diff against today's plan |
| `question_impact(history, ...)` | Every open question with the diff each possible answer would cause |
| `make_graph(plan, pack=None)` | `CareGraph` linking source to rule to action, with observations and blocking questions. Export `.to_mermaid()`, `.to_dot()`, `.to_json()`, `.to_networkx()` |
| `explain_action(plan, action_id)` | Plain-text trace of one action: rule, evidence, inputs, the priority tuple |
| `summarize(plan)` | Markdown report for a notebook, a pull request or a review packet |
| `compare_plans(before, after)` | Diff two plans. Use it when you edit an evidence pack |
| `load_pack(name_or_path)` / `available_packs()` | Load and validate an evidence pack |
| `Truth`, `all_of`, `any_of` | The three-valued logic used by the engine, exposed for your own rules |

`history` can be a `PatientHistory` or the plain JSON dict. Everything returned is a frozen dataclass with a `to_dict()`.

### Command line

```bash
sca-care plan      examples/child_22_months.json            # JSON plan
sca-care summary   examples/child_22_months.json            # Markdown
sca-care explain   examples/child_22_months.json --action autism_screen:18
sca-care questions examples/child_22_months.json
sca-care timeline  examples/child_22_months.json --horizon 12
sca-care graph     examples/child_22_months.json --format dot | dot -Tsvg > plan.svg
sca-care validate  --pack path/to/my_pack.json
sca-care -v plan   examples/child_22_months.json            # log every rule decision
```

Bad input exits with status 2 and names the field, for example `observations[0].valid_until_months`.

## How it decides

Three steps, all deterministic.

**Truth.** Each rule clause evaluates to true, false or unknown (Kleene logic). A clause is unknown when there is no observation, when two observations at the same time disagree, or when the latest one has passed its `valid_until_months`. A rule with a false clause is silent. A rule with an unknown clause becomes a verification item. Only an all-true rule becomes a candidate.

**Priority.** Candidates sort on

```
P(a) = (c_a, -d_a)
```

where `c_a` is 3 for a current review, 2 for care explicitly recorded as not done, 1 for future scheduled care, and `d_a` is the target age in months. Larger sorts first, then by action id. These are workflow classes. Nothing here is a probability.

**Questions.** A missing field `f` that blocks the set of actions `B_f` ranks by

```
Q(f) = (max c_a over B_f, |B_f|)
```

so a fact that holds up a current review outranks one that holds up a future screen, and a fact that blocks two items outranks one that blocks one. `question_impact` then shows what each answer would actually move.

## Input format

```json
{
  "age_months": 22,
  "jurisdiction": "US",
  "karyotype": "47,XXY",
  "karyotype_status": "confirmed",
  "observations": [
    {"key": "developmental_concern", "value": true,
     "observed_at_months": 22, "valid_until_months": 22, "source": "caregiver report"}
  ],
  "completions": [
    {"action_id": "developmental_screen:18", "status": "done",
     "recorded_at_months": 18, "source": "clinic record"}
  ]
}
```

* Observation values must be literal `true` or `false`. If you do not know, leave the observation out.
* You set `valid_until_months`. The library invents no expiry period.
* Completion ids are `<rule_id>:<age>`. Status is `done` or `not_done`; unknown means omit it.
* Records dated after `age_months` are ignored and flagged in `warnings`.
* SCA-specific rules need `karyotype_status: "confirmed"`. Anything else withholds them and asks for confirmation.
* `legacy_n_score`, `measurements`, `medications` and `genomic_files` are accepted and reported as not interpreted.

## Evidence packs

A pack is reviewable JSON: sources with URLs and locators, and rules that cite them. The bundled pack is [`src/sca_care_planner/packs/us_development_seed.json`](src/sca_care_planner/packs/us_development_seed.json). An observation rule looks like this:

```json
{
  "id": "concern_without_plan", "version": "0.1.0", "kind": "observation",
  "domain": "development", "min_age_months": 0, "max_age_months": 72,
  "when": [
    {"feature": "developmental_concern", "expected": true},
    {"feature": "developmental_followup_plan_in_place", "expected": false}
  ],
  "action": "Discuss a follow-up plan for the current concern.",
  "reason": "Why the evidence supports this, in one or two sentences.",
  "sources": ["AAP2020"],
  "review_status": "author_drafted_not_clinically_reviewed"
}
```

A `schedule` rule takes `ages_months` instead of `when`. Every pack gets a SHA-256 fingerprint, and every plan records the fingerprint it was built from, so a result can always be traced to the exact evidence that produced it. `load_pack` reports every structural problem in one go, whether it is an unknown source id, a duplicate rule id or a rule that cites nothing.

## Debugging

* `plan.trace` lists every rule or slot that produced nothing, and why (`outside_age_range`, `karyotype_not_matched`, `trigger_explicitly_false`, `completed`, `older_slot_collapsed_into_latest_catch_up_review`).
* `logging.getLogger("sca_care_planner").setLevel(logging.DEBUG)` prints each decision as it happens. The CLI flag is `-v`.
* Errors subclass `ValueError` and carry `.field`.
* `explain_action` is usually the quickest answer to "why is this here?".

## Verification

```bash
python scripts/run_validation.py
```

This runs the suite, regenerates the demo outputs in `examples/`, and writes [`reports/test_results.json`](reports/test_results.json) with the engine and pack fingerprints. The suite carries over the 19 original prototype tests and adds a differential test that feeds 2,000 seeded random histories through both this library and a frozen copy of the 0.1.0 prototype, and requires identical output. CI runs lint, strict type checks and tests on Linux, macOS and Windows for Python 3.10 to 3.13.

Passing tests show the software does what the rules say. They say nothing about whether the rules are clinically right. That needs clinical review of every rule by people with SCA and developmental expertise.

## Scope, stated plainly

In: developmental concern review; US developmental screening at 9, 18 and 30 months; autism screening at 18 and 24 months; follow-up plan checks for confirmed XXY (to 72 months) and XXX/XYY (to 36 months).

Out, for now: endocrine, cardiac and medication modules; questionnaire scoring; raw genomic files; Turner syndrome and mosaic karyotypes; non-US packs; any individual risk estimate. A jurisdiction or karyotype the pack does not cover produces a coverage warning, not a guess.

## Contributing

Evidence-pack reviews from clinicians are the most useful contribution right now. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence and credit

Code: [Apache License 2.0](LICENSE). You may use and modify it, and redistribute it commercially too, provided you keep the copyright notice and the [NOTICE](NOTICE) file with any redistribution.

If this library helps your research, please cite it. GitHub's "Cite this repository" button reads [CITATION.cff](CITATION.cff), or use:

```bibtex
@software{mitra_sca_care_planner_2026,
  author  = {Mitra, Sidhartha},
  title   = {SCA Care Planner},
  version = {0.2.0},
  year    = {2026},
  publisher = {SidLabs Online LLP},
  url     = {https://github.com/SidLabs-Online/SCA-Care-Planner},
  license = {Apache-2.0}
}
```

Copyright 2026 Sidhartha Mitra, SidLabs Online LLP.
