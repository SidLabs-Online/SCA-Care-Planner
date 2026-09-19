# Changelog

## 0.2.0 (2026-09-19)

First public library release, built from the 0.1.0 research prototype.

### Added
* Typed, frozen models: `PatientHistory`, `EvidencePack`, `CarePlan`, `Action`, `Question`.
* `predict_care`: month-by-month projection over the horizon.
* `what_if` and `question_impact`: how each answer to an open question would move the plan.
* `make_graph`: evidence graph with Mermaid, DOT, node-link JSON and networkx export.
* `explain_action`, `summarize`, `compare_plans`.
* `Truth`, `all_of`, `any_of` (Kleene logic), and compound observation rules through `when`.
* Pack validation that reports every problem at once, and bundled-pack discovery.
* `sca-care` CLI with `plan`, `summary`, `explain`, `questions`, `timeline`, `graph`, `packs`, `validate`.
* Errors carry the offending `field`. Debug logging on `sca_care_planner`.
* Differential test against the frozen 0.1.0 engine on 2,000 random histories.
* CI on Linux, macOS and Windows, Python 3.10 to 3.13. Strict mypy.
* Apache-2.0 LICENSE, NOTICE and CITATION.cff. The white paper is kept out of this repository until it is published.

### Changed
* Package renamed from `sca_care` to `sca_care_planner`. `python -m sca_care_planner patient.json` still works.
* `evaluate_plan` returns a `CarePlan`. `CarePlan.to_dict()` gives the 0.1.0 JSON, plus `age_months`.
* Unsupported-karyotype warning now reads "general rules only" (was "general US rules only"), since packs are not always US.
* Licence changed from MIT (prototype) and GPL-3.0 (empty repository) to Apache-2.0 with a NOTICE file.

### Unchanged on purpose
* Rule semantics, priorities, question ranking and the evidence pack itself. Pack fingerprint: `03d69fd2ea42…`.

## 0.1.0 (2026-09-19)

Research prototype: five rules, 19 tests, one synthetic example. Not published.
