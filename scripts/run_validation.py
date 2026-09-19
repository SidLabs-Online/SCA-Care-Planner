"""Reproducible software verification. This is not clinical validation.

Runs the full test suite, then regenerates the worked-example outputs, and
writes a machine-readable report with the fingerprints of the engine and the
evidence pack that were tested.

    python scripts/run_validation.py
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

import sca_care_planner as scp

ROOT = Path(__file__).resolve().parents[1]
PKG = Path(scp.__file__).parent


class _Counter:
    def __init__(self) -> None:
        self.counts = {"passed": 0, "failed": 0, "skipped": 0}

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        if report.when == "call" or (report.when == "setup" and report.outcome != "passed"):
            self.counts[report.outcome] = self.counts.get(report.outcome, 0) + 1


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    counter = _Counter()
    exit_code = pytest.main(["-q", "-p", "no:cacheprovider", str(ROOT / "tests")], plugins=[counter])
    pack = scp.load_pack()
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "library_version": scp.__version__,
        "python": platform.python_version(),
        "test_type": "synthetic_fixture_software_tests",
        "tests": counter.counts,
        "passed": exit_code == 0,
        "differential_check": "2000 seeded random histories compared against the frozen 0.1.0 prototype",
        "clinical_validation": "not_performed",
        "patient_data_used": False,
        "predictive_model_trained": False,
        "pack": {"id": pack.id, "version": pack.version, "sha256": pack.sha256},
        "source_sha256": {p.name: sha256(p) for p in sorted(PKG.glob("*.py"))},
    }
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports" / "test_results.json").write_text(json.dumps(report, indent=2) + "\n")

    history = scp.read_history(ROOT / "examples" / "child_22_months.json")
    plan = scp.evaluate_plan(history)
    examples = ROOT / "examples"
    (examples / "demo_output.json").write_text(json.dumps(plan.to_dict(), indent=2) + "\n")
    (examples / "demo_timeline.json").write_text(json.dumps(scp.predict_care(history).to_dict(), indent=2) + "\n")
    (examples / "demo_graph.mmd").write_text(scp.make_graph(plan, pack).to_mermaid() + "\n")
    (examples / "demo_summary.md").write_text(scp.summarize(plan))

    print(json.dumps({k: report[k] for k in ("library_version", "tests", "passed", "pack")}, indent=2))
    return 0 if exit_code == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
