# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Sidhartha Mitra, SidLabs Online LLP. See NOTICE.
"""Command line interface: ``sca-care <command> patient.json``.

Commands
    plan        full plan as JSON (default)
    summary     Markdown report
    explain     trace one action (--action ID)
    questions   open questions with the diff each answer would cause
    timeline    month-by-month projection over the horizon
    graph       evidence graph as dot, mermaid or json (--format)
    packs       list bundled evidence packs
    validate    validate an evidence pack (--pack PATH)

Exit status is 0 on success and 2 on bad input, with the offending field named.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from . import __version__
from .engine import MAX_HORIZON_MONTHS, evaluate_plan
from .errors import SCACareError
from .evidence import available_packs, load_pack
from .explain import explain_action, summarize
from .graph import make_graph
from .timeline import predict_care
from .whatif import question_impact


def _read_json(path: str) -> Any:
    if path == "-":
        return json.load(sys.stdin)
    return json.loads(Path(path).read_text("utf-8"))


def _dump(data: Any) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sca-care", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="log every rule decision to stderr")
    sub = parser.add_subparsers(dest="command")

    def with_history(name: str, help_text: str) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_text)
        p.add_argument("history", help="patient history JSON file, or - for stdin")
        p.add_argument("--pack", help="bundled pack name or path to a pack JSON")
        p.add_argument("--horizon", type=float, default=MAX_HORIZON_MONTHS, help="months ahead, max 24")
        return p

    with_history("plan", "full plan as JSON")
    with_history("summary", "Markdown report")
    with_history("explain", "trace one action").add_argument("--action", required=True)
    with_history("questions", "open questions and their impact")
    with_history("timeline", "projection over the horizon")
    with_history("graph", "evidence graph").add_argument(
        "--format", choices=("dot", "mermaid", "json"), default="mermaid"
    )
    sub.add_parser("packs", help="list bundled evidence packs")
    sub.add_parser("validate", help="validate an evidence pack").add_argument("--pack", required=True)
    return parser


def run(args: argparse.Namespace) -> str:
    if args.command == "packs":
        return "\n".join(available_packs())
    if args.command == "validate":
        pack = load_pack(args.pack)
        return f"ok: {pack.id} v{pack.version}, {len(pack.rules)} rules, sha256 {pack.sha256}"

    history = _read_json(args.history)
    pack = load_pack(args.pack)
    if args.command == "timeline":
        return _dump(predict_care(history, pack, args.horizon).to_dict())
    if args.command == "questions":
        return _dump([q.to_dict() for q in question_impact(history, pack, args.horizon)])
    plan = evaluate_plan(history, pack, args.horizon)
    if args.command == "summary":
        return summarize(plan)
    if args.command == "explain":
        return explain_action(plan, args.action)
    if args.command == "graph":
        graph = make_graph(plan, pack)
        return {"dot": graph.to_dot, "mermaid": graph.to_mermaid, "json": graph.to_json}[args.format]()
    return _dump(plan.to_dict())


def main(argv: Sequence[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    # Backward compatible with the 0.1 prototype: `python -m sca_care patient.json`.
    if (
        raw
        and not raw[0].startswith("-")
        and raw[0]
        not in {
            "plan",
            "summary",
            "explain",
            "questions",
            "timeline",
            "graph",
            "packs",
            "validate",
        }
    ):
        raw.insert(0, "plan")
    parser = build_parser()
    args = parser.parse_args(raw)
    if args.command is None:
        parser.print_help()
        return 0
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING, format="%(name)s %(levelname)s %(message)s"
    )
    try:
        print(run(args))
    except (SCACareError, KeyError, FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"sca-care: error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
