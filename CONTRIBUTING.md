# Contributing

Thanks for looking. Two kinds of contribution help most: clinical review of evidence packs, and code that keeps the engine honest.

## Set up

```bash
pip install -e ".[dev]"
ruff check . && ruff format --check . && mypy && pytest
```

All four must pass before a pull request is reviewed. CI runs the same commands.

## Ground rules for code

* The engine stays dependency-free and deterministic. No network access, no clock and no randomness.
* Unknown stays unknown. A missing record must never be read as a negative finding.
* No risk probabilities. `risk_probability` stays `None` until an externally validated and calibrated model exists. That model will live in a separate module with its own paper.
* Every action carries evidence. A rule with no source is rejected by `load_pack`, and it should stay that way.
* Public functions get type hints and a docstring. New behaviour gets a test.
* If you change engine semantics on purpose, the differential test in `tests/test_differential.py` will fail. Say why in `CHANGELOG.md` and in the pull request.

## Evidence packs

A new or changed rule needs:

1. A source entry with its title and URL, the source date, and a locator (section or recommendation number) where one exists.
2. Explicit age limits, plus karyotype limits where relevant.
3. A `reason` written in your own words. Do not paste guideline text.
4. `review_status` set honestly. Only a named clinical reviewer can move it past `author_drafted_not_clinically_reviewed`.
5. A version bump on the rule and the pack.

Run `sca-care validate --pack your_pack.json`, then use `compare_plans` on the example fixtures to show reviewers exactly what your change moves.

## Data

Never commit real patient data, even de-identified. Fixtures are synthetic and labelled as such.

## Licence

By contributing you agree that your contribution is licensed under Apache-2.0.
