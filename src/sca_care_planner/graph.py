# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Sidhartha Mitra, SidLabs Online LLP. See NOTICE.
"""Evidence graph of a plan.

``make_graph`` links every action back to the rule that produced it and the
published sources behind that rule, and forward to the observations it used
and the missing facts that block it. One picture answers "why is this here?"
and "what would unblock it?".

Node ids are prefixed by type: ``source:``, ``rule:``, ``action:``,
``observation:``, ``question:``. Exports need no third-party package; the
optional :meth:`CareGraph.to_networkx` imports networkx only when called.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .evidence import EvidencePack
from .plan import CarePlan

if TYPE_CHECKING:  # pragma: no cover
    import networkx

NODE_KINDS = ("source", "rule", "action", "observation", "question")


@dataclass(frozen=True, slots=True)
class Node:
    id: str
    kind: str
    label: str
    attrs: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Edge:
    source: str
    target: str
    relation: str
    """``supports`` (source to rule), ``produces`` (rule to action), ``informs``
    (observation to action), ``blocks`` (question to action or rule)."""


@dataclass(frozen=True, slots=True)
class CareGraph:
    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]

    def node(self, node_id: str) -> Node:
        for n in self.nodes:
            if n.id == node_id:
                return n
        raise KeyError(node_id)

    def neighbours(self, node_id: str, relation: str | None = None) -> list[str]:
        return [
            e.target if e.source == node_id else e.source
            for e in self.edges
            if node_id in (e.source, e.target) and (relation is None or e.relation == relation)
        ]

    def why(self, action_id: str) -> list[str]:
        """Source ids that stand behind an action, walking action <- rule <- source."""
        rules = [e.source for e in self.edges if e.target == f"action:{action_id}" and e.relation == "produces"]
        return sorted({e.source for e in self.edges if e.target in rules and e.relation == "supports"})

    # Exports --------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Node-link JSON, the same layout ``networkx.node_link_graph`` reads."""
        return {
            "directed": True,
            "multigraph": False,
            "graph": {},
            "nodes": [{"id": n.id, "kind": n.kind, "label": n.label, **n.attrs} for n in self.nodes],
            "links": [{"source": e.source, "target": e.target, "relation": e.relation} for e in self.edges],
        }

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    def to_dot(self) -> str:
        """Graphviz DOT. Render with ``dot -Tsvg plan.dot -o plan.svg``."""
        shapes = {
            "source": "note",
            "rule": "box",
            "action": "ellipse",
            "observation": "cylinder",
            "question": "diamond",
        }
        lines = ["digraph care_plan {", "  rankdir=LR;", '  node [fontname="Helvetica"];']
        for n in self.nodes:
            lines.append(f"  {_q(n.id)} [label={_q(n.label)}, shape={shapes[n.kind]}];")
        for e in self.edges:
            style = ", style=dashed" if e.relation == "blocks" else ""
            lines.append(f"  {_q(e.source)} -> {_q(e.target)} [label={_q(e.relation)}{style}];")
        lines.append("}")
        return "\n".join(lines)

    def to_mermaid(self) -> str:
        """Mermaid flowchart. GitHub renders it inside a ```mermaid block."""
        brackets = {
            "source": ("[/", "/]"),
            "rule": ("[", "]"),
            "action": ("([", "])"),
            "observation": ("[(", ")]"),
            "question": ("{", "}"),
        }
        ids = {n.id: f"n{i}" for i, n in enumerate(self.nodes)}
        lines = ["flowchart LR"]
        for n in self.nodes:
            left, right = brackets[n.kind]
            lines.append(f'  {ids[n.id]}{left}"{_mermaid_text(n.label)}"{right}')
        for e in self.edges:
            arrow = "-.->" if e.relation == "blocks" else "-->"
            lines.append(f"  {ids[e.source]} {arrow}|{e.relation}| {ids[e.target]}")
        return "\n".join(lines)

    def to_networkx(self) -> networkx.DiGraph:
        try:
            import networkx as nx
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise ImportError("to_networkx needs networkx: pip install 'sca-care-planner[graph]'") from exc
        g = nx.DiGraph()
        for n in self.nodes:
            g.add_node(n.id, kind=n.kind, label=n.label, **n.attrs)
        for e in self.edges:
            g.add_edge(e.source, e.target, relation=e.relation)
        return g


def _q(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _mermaid_text(text: str) -> str:
    return text.replace('"', "'")


def make_graph(plan: CarePlan, pack: EvidencePack | Mapping[str, Any] | None = None) -> CareGraph:
    """Build the evidence graph for ``plan``.

    ``pack`` is optional. When given, source nodes carry the full title; when
    omitted, titles come from the evidence already embedded in each action.
    """
    resolved = EvidencePack.coerce(pack) if pack is not None else None
    nodes: dict[str, Node] = {}
    edges: list[Edge] = []

    def add(node: Node) -> None:
        nodes.setdefault(node.id, node)

    def link(src: str, dst: str, relation: str) -> None:
        edge = Edge(src, dst, relation)
        if edge not in edges:
            edges.append(edge)

    for a in plan.all_actions:
        action_node = f"action:{a.action_id}"
        rule_node = f"rule:{a.rule_id}"
        add(
            Node(
                action_node,
                "action",
                a.action_id,
                {
                    "state": "verify" if a.needs_information else a.priority.label,
                    "due_age_months": a.due_age_months,
                    "priority_key": list(a.key),
                },
            )
        )
        add(
            Node(
                rule_node,
                "rule",
                f"rule {a.rule_id} v{a.rule_version}",
                {"version": a.rule_version, "review_status": a.rule_review_status},
            )
        )
        link(rule_node, action_node, "produces")
        for ev in a.evidence:
            sid = str(ev.get("id"))
            meta = resolved.sources.get(sid, ev) if resolved else ev
            add(Node(f"source:{sid}", "source", str(meta.get("title", sid)), {"url": meta.get("url")}))
            link(f"source:{sid}", rule_node, "supports")
        for obs in a.observations_used:
            key = f"observation:{obs['key']}@{obs['observed_at_months']:g}"
            add(Node(key, "observation", f"{obs['key']}={obs['value']}", {"source": obs["source"]}))
            link(key, action_node, "informs")
    for w in plan.withheld:
        rule_node = f"rule:{w.rule_id}"
        add(Node(rule_node, "rule", f"rule {w.rule_id} (withheld)", {"state": "withheld", "reason": w.reason}))
        if resolved:
            for sid in resolved.rule(w.rule_id).sources:
                add(
                    Node(
                        f"source:{sid}",
                        "source",
                        str(resolved.sources[sid].get("title", sid)),
                        {"url": resolved.sources[sid].get("url")},
                    )
                )
                link(f"source:{sid}", rule_node, "supports")
    for q in plan.questions:
        qid = f"question:{q.field}"
        add(Node(qid, "question", q.field, {"potential_priority": q.potential_priority}))
        for target in q.affected_action_ids:
            target_node = f"action:{target}" if f"action:{target}" in nodes else f"rule:{target}"
            add(Node(target_node, "rule", target, {"state": "withheld"}))  # no-op if already present
            link(qid, target_node, "blocks")
    return CareGraph(tuple(nodes.values()), tuple(edges))
