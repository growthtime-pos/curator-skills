#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


GRAPHIFY_BUILD_CODE = r"""
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from graphify.analyze import god_nodes, surprising_connections, suggest_questions
from graphify.build import build_from_json
from graphify.cluster import cluster, score_all
from graphify.export import to_html, to_json
from graphify.report import generate


def choose_label(node_ids, node_by_id):
    spaces = []
    keywords = []
    pages = []
    others = []
    for node_id in node_ids:
        node = node_by_id.get(node_id, {})
        label = (node.get("label") or "").strip()
        if not label:
            continue
        if label.startswith("Space "):
            spaces.append(label)
        elif label.startswith("kw:"):
            keywords.append(label.replace("kw:", "").strip())
        elif node.get("id", "").startswith("page_"):
            pages.append(label)
        else:
            others.append(label)
    if spaces:
        return spaces[0]
    if keywords:
        return " / ".join(keywords[:2])[:48]
    if pages:
        return pages[0][:48]
    if others:
        return others[0][:48]
    return "Community"


extract_path = Path(sys.argv[1])
out_dir = Path(sys.argv[2])
emit_html = sys.argv[3] == "1"

extraction = json.loads(extract_path.read_text(encoding="utf-8"))
G = build_from_json(extraction)
communities = cluster(G)
cohesion = score_all(G, communities)
gods = god_nodes(G)
surprises = surprising_connections(G, communities)
node_by_id = {node["id"]: node for node in extraction.get("nodes", [])}
labels = {cid: choose_label(node_ids, node_by_id) for cid, node_ids in communities.items()}
questions = suggest_questions(G, communities, labels)
tokens = {"input": extraction.get("input_tokens", 0), "output": extraction.get("output_tokens", 0)}
report = generate(
    G,
    communities,
    cohesion,
    labels,
    gods,
    surprises,
    {"total_files": 0, "total_words": 0, "files": {}},
    tokens,
    str(out_dir.parent),
    suggested_questions=questions,
)
out_dir.mkdir(parents=True, exist_ok=True)
(out_dir / "GRAPH_REPORT.md").write_text(report, encoding="utf-8")
to_json(G, communities, str(out_dir / "graph.json"))
if emit_html and G.number_of_nodes() <= 5000:
    to_html(G, communities, str(out_dir / "graph.html"), community_labels=labels)

page_context = {}
for node_id, data in G.nodes(data=True):
    page_id = data.get("page_id")
    if not page_id:
        continue
    neighbors = []
    for neighbor in G.neighbors(node_id):
        neighbor_label = G.nodes[neighbor].get("label", neighbor)
        if neighbor_label == data.get("label"):
            continue
        neighbors.append(neighbor_label)
    page_context[page_id] = {
        "node_id": node_id,
        "label": data.get("label"),
        "community_id": data.get("community"),
        "community_label": labels.get(data.get("community"), "Community"),
        "degree": G.degree(node_id),
        "top_neighbors": neighbors[:6],
    }

page_nodes = []
for node_id, data in G.nodes(data=True):
    if data.get("page_id"):
        page_nodes.append(
            {
                "page_id": data.get("page_id"),
                "label": data.get("label"),
                "degree": G.degree(node_id),
                "community_label": labels.get(data.get("community"), "Community"),
            }
        )
page_nodes.sort(key=lambda item: (item["degree"], item["label"]), reverse=True)

summary = {
    "meta": {
        "graphify_available": True,
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(),
    },
    "stats": {
        "node_count": G.number_of_nodes(),
        "edge_count": G.number_of_edges(),
        "community_count": len(communities),
    },
    "communities": [
        {
            "community_id": cid,
            "label": labels.get(cid, "Community"),
            "node_count": len(node_ids),
            "cohesion": cohesion.get(cid),
            "top_labels": [
                node_by_id.get(node_id, {}).get("label", node_id)
                for node_id in node_ids[:6]
            ],
        }
        for cid, node_ids in sorted(communities.items())
    ],
    "god_nodes": gods[:10],
    "surprising_connections": surprises[:8],
    "suggested_questions": questions[:8],
    "page_context": page_context,
    "bridge_pages": page_nodes[:10],
}
(out_dir / "graph_context.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
(out_dir / "graph_analysis.json").write_text(
    json.dumps(
        {
            "labels": {str(cid): label for cid, label in labels.items()},
            "communities": {str(cid): node_ids for cid, node_ids in communities.items()},
            "cohesion": {str(cid): value for cid, value in cohesion.items()},
            "questions": questions,
        },
        ensure_ascii=False,
        indent=2,
    ),
    encoding="utf-8",
)
print(json.dumps(summary["stats"], ensure_ascii=False))
"""


def iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build graphify artifacts from normalized Confluence data.")
    parser.add_argument("--normalized-input", required=True)
    parser.add_argument("--corpus-dir", required=True)
    parser.add_argument("--graphify-out-dir", required=True)
    parser.add_argument("--emit-html", action="store_true")
    return parser.parse_args()


def read_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: str, payload: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9가-힣]+", "-", (value or "").lower()).strip("-") or "item"


def trim_text(value: str, limit: int = 280) -> str:
    text = normalize_text(value)
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def resolve_graphify_python() -> Optional[str]:
    candidates: List[str] = []
    env_python = os.environ.get("GRAPHIFY_PYTHON")
    if env_python:
        candidates.append(env_python)
    candidates.append(sys.executable)

    graphify_bin = shutil.which("graphify")
    if graphify_bin and os.path.isfile(graphify_bin):
        try:
            first_line = Path(graphify_bin).read_text(encoding="utf-8").splitlines()[0]
        except (IndexError, OSError, UnicodeDecodeError):
            first_line = ""
        if first_line.startswith("#!"):
            candidates.append(first_line[2:].strip())

    fallback_bin = Path.home() / ".local" / "bin" / "graphify"
    if fallback_bin.exists():
        try:
            first_line = fallback_bin.read_text(encoding="utf-8").splitlines()[0]
        except (IndexError, OSError, UnicodeDecodeError):
            first_line = ""
        if first_line.startswith("#!"):
            candidates.append(first_line[2:].strip())

    seen = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        try:
            result = subprocess.run(
                [candidate, "-c", "import graphify, sys; print(sys.executable)"],
                check=True,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.CalledProcessError):
            continue
        resolved = result.stdout.strip()
        if resolved:
            return resolved
    return None


def collect_page_maintainers(page: Dict[str, Any]) -> List[Dict[str, Any]]:
    maintainers = []
    for signal in page.get("maintainer_signals", []):
        account_id = signal.get("account_id")
        if account_id:
            maintainers.append(signal)
    return maintainers


def add_node(nodes: List[Dict[str, Any]], seen: Dict[str, Dict[str, Any]], node: Dict[str, Any]) -> None:
    node_id = node["id"]
    if node_id in seen:
        existing = seen[node_id]
        if not existing.get("label") and node.get("label"):
            existing["label"] = node["label"]
        if not existing.get("page_id") and node.get("page_id"):
            existing["page_id"] = node["page_id"]
        return
    seen[node_id] = node
    nodes.append(node)


def add_edge(edges: List[Dict[str, Any]], seen: set[Tuple[str, str, str]], edge: Dict[str, Any]) -> None:
    key = (edge["source"], edge["target"], edge["relation"])
    if key in seen:
        return
    seen.add(key)
    edges.append(edge)


def build_graph_extraction(payload: Dict[str, Any]) -> Dict[str, Any]:
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    seen_nodes: Dict[str, Dict[str, Any]] = {}
    seen_edges: set[Tuple[str, str, str]] = set()
    page_ids = {page.get("page_id") for page in payload.get("pages", []) if page.get("page_id")}
    people_lookup = {
        person.get("account_id"): person
        for person in payload.get("people", [])
        if person.get("account_id")
    }
    keyword_pairs: Dict[Tuple[str, str], int] = {}
    keyword_to_pages: Dict[str, List[str]] = {}

    for page in payload.get("pages", []):
        page_id = page.get("page_id")
        if not page_id:
            continue
        page_node_id = f"page_{slugify(page_id)}"
        add_node(
            nodes,
            seen_nodes,
            {
                "id": page_node_id,
                "label": page.get("title") or page_id,
                "page_id": page_id,
                "file_type": "document",
                "source_file": f"normalized:{page_id}",
                "source_location": None,
                "source_url": page.get("url"),
                "captured_at": page.get("updated_at"),
                "author": None,
                "contributor": None,
            },
        )

        space_key = page.get("space_key")
        if space_key:
            space_node_id = f"space_{slugify(space_key)}"
            add_node(
                nodes,
                seen_nodes,
                {
                    "id": space_node_id,
                    "label": f"Space {space_key}",
                    "file_type": "document",
                    "source_file": f"normalized:{page_id}",
                    "source_location": None,
                    "source_url": None,
                    "captured_at": page.get("updated_at"),
                    "author": None,
                    "contributor": None,
                },
            )
            add_edge(
                edges,
                seen_edges,
                {
                    "source": page_node_id,
                    "target": space_node_id,
                    "relation": "belongs_to",
                    "confidence": "EXTRACTED",
                    "confidence_score": 1.0,
                    "source_file": f"normalized:{page_id}",
                    "source_location": None,
                    "weight": 1.0,
                },
            )

        for maintainer in collect_page_maintainers(page):
            account_id = maintainer.get("account_id")
            person = people_lookup.get(account_id, maintainer)
            person_node_id = f"person_{slugify(account_id)}"
            add_node(
                nodes,
                seen_nodes,
                {
                    "id": person_node_id,
                    "label": person.get("display_name") or account_id,
                    "file_type": "document",
                    "source_file": f"normalized:{page_id}",
                    "source_location": None,
                    "source_url": None,
                    "captured_at": page.get("updated_at"),
                    "author": None,
                    "contributor": None,
                },
            )
            add_edge(
                edges,
                seen_edges,
                {
                    "source": page_node_id,
                    "target": person_node_id,
                    "relation": "maintained_by",
                    "confidence": "EXTRACTED",
                    "confidence_score": 1.0,
                    "source_file": f"normalized:{page_id}",
                    "source_location": None,
                    "weight": 1.0,
                },
            )

        for keyword in page.get("keywords", [])[:8]:
            keyword_node_id = f"keyword_{slugify(keyword)}"
            add_node(
                nodes,
                seen_nodes,
                {
                    "id": keyword_node_id,
                    "label": f"kw:{keyword}",
                    "file_type": "document",
                    "source_file": f"normalized:{page_id}",
                    "source_location": None,
                    "source_url": None,
                    "captured_at": page.get("updated_at"),
                    "author": None,
                    "contributor": None,
                },
            )
            add_edge(
                edges,
                seen_edges,
                {
                    "source": page_node_id,
                    "target": keyword_node_id,
                    "relation": "references",
                    "confidence": "EXTRACTED",
                    "confidence_score": 1.0,
                    "source_file": f"normalized:{page_id}",
                    "source_location": None,
                    "weight": 1.0,
                },
            )
            keyword_to_pages.setdefault(keyword, []).append(page_id)

        for index, claim in enumerate(page.get("claim_candidates", [])[:2], start=1):
            claim_node_id = f"claim_{slugify(page_id)}_{index}"
            add_node(
                nodes,
                seen_nodes,
                {
                    "id": claim_node_id,
                    "label": trim_text(claim, 96),
                    "file_type": "document",
                    "source_file": f"normalized:{page_id}",
                    "source_location": None,
                    "source_url": page.get("url"),
                    "captured_at": page.get("updated_at"),
                    "author": None,
                    "contributor": None,
                },
            )
            add_edge(
                edges,
                seen_edges,
                {
                    "source": page_node_id,
                    "target": claim_node_id,
                    "relation": "references",
                    "confidence": "EXTRACTED",
                    "confidence_score": 1.0,
                    "source_file": f"normalized:{page_id}",
                    "source_location": None,
                    "weight": 1.0,
                },
            )

        for rel_type, target_ids in (page.get("relationship_targets") or {}).items():
            for target_page_id in target_ids:
                target_node_id = f"page_{slugify(target_page_id)}"
                if target_page_id not in page_ids:
                    add_node(
                        nodes,
                        seen_nodes,
                        {
                            "id": target_node_id,
                            "label": target_page_id,
                            "page_id": target_page_id,
                            "file_type": "document",
                            "source_file": f"normalized:{page_id}",
                            "source_location": None,
                            "source_url": None,
                            "captured_at": page.get("updated_at"),
                            "author": None,
                            "contributor": None,
                        },
                    )
                add_edge(
                    edges,
                    seen_edges,
                    {
                        "source": page_node_id,
                        "target": target_node_id,
                        "relation": rel_type or "references",
                        "confidence": "EXTRACTED",
                        "confidence_score": 1.0,
                        "source_file": f"normalized:{page_id}",
                        "source_location": None,
                        "weight": 1.0,
                    },
                )

    for keyword, page_list in keyword_to_pages.items():
        if len(page_list) < 2:
            continue
        unique_pages = sorted(set(page_list))
        for index, left in enumerate(unique_pages):
            for right in unique_pages[index + 1 :]:
                pair = (left, right)
                keyword_pairs[pair] = keyword_pairs.get(pair, 0) + 1

    for (left_page_id, right_page_id), overlap_count in keyword_pairs.items():
        if overlap_count < 2:
            continue
        add_edge(
            edges,
            seen_edges,
            {
                "source": f"page_{slugify(left_page_id)}",
                "target": f"page_{slugify(right_page_id)}",
                "relation": "conceptually_related_to",
                "confidence": "INFERRED",
                "confidence_score": min(0.95, 0.55 + overlap_count * 0.1),
                "source_file": "normalized:keyword-overlap",
                "source_location": None,
                "weight": float(overlap_count),
            },
        )

    return {
        "nodes": nodes,
        "edges": edges,
        "hyperedges": [],
        "input_tokens": 0,
        "output_tokens": 0,
    }


def write_corpus_docs(payload: Dict[str, Any], corpus_dir: str) -> None:
    corpus_path = Path(corpus_dir)
    corpus_path.mkdir(parents=True, exist_ok=True)
    for page in payload.get("pages", []):
        page_id = page.get("page_id")
        if not page_id:
            continue
        title = page.get("title") or page_id
        target_path = corpus_path / f"{slugify(page_id)}.md"
        keywords = ", ".join(page.get("keywords", [])[:8])
        maintainers = ", ".join(
            signal.get("display_name") or signal.get("account_id") or "unknown"
            for signal in page.get("maintainer_signals", [])[:5]
        )
        lines = [
            "---",
            f'title: "{title.replace(chr(34), chr(39))}"',
            f'page_id: "{page_id}"',
            f'space_key: "{page.get("space_key") or ""}"',
            f'source_url: "{page.get("url") or ""}"',
            f'captured_at: "{page.get("updated_at") or ""}"',
            "---",
            "",
            f"# {title}",
            "",
            "## Metadata",
            f"- page_id: `{page_id}`",
            f"- space_key: `{page.get('space_key') or ''}`",
            f"- updated_at: `{page.get('updated_at') or ''}`",
            f"- keywords: {keywords or '없음'}",
            f"- maintainers: {maintainers or '없음'}",
            "",
            "## Claim Candidates",
        ]
        claims = page.get("claim_candidates", [])
        if claims:
            lines.extend(f"- {trim_text(claim, 320)}" for claim in claims[:5])
        else:
            lines.append("- 없음")
        lines.extend(["", "## Sentences"])
        sentences = page.get("sentences", [])
        if sentences:
            lines.extend(f"- {trim_text(sentence, 320)}" for sentence in sentences[:8])
        else:
            lines.append("- 없음")
        target_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_unavailable_context(graphify_out_dir: str, normalized_input: str, reason: str) -> None:
    payload = {
        "meta": {
            "generated_at": iso_now(),
            "graphify_available": False,
            "normalized_input": os.path.abspath(normalized_input),
            "reason": reason,
        },
        "stats": {"node_count": 0, "edge_count": 0, "community_count": 0},
        "communities": [],
        "god_nodes": [],
        "surprising_connections": [],
        "suggested_questions": [],
        "page_context": {},
        "bridge_pages": [],
        "warnings": [reason],
    }
    write_json(os.path.join(graphify_out_dir, "graph_context.json"), payload)


def main() -> int:
    args = parse_args()
    payload = read_json(args.normalized_input)
    os.makedirs(args.corpus_dir, exist_ok=True)
    os.makedirs(args.graphify_out_dir, exist_ok=True)

    write_corpus_docs(payload, args.corpus_dir)
    extraction = build_graph_extraction(payload)
    extraction_path = os.path.join(args.graphify_out_dir, "graph_extract.json")
    write_json(extraction_path, extraction)

    graphify_python = resolve_graphify_python()
    if not graphify_python:
        write_unavailable_context(args.graphify_out_dir, args.normalized_input, "graphify python environment could not be resolved")
        print("graphify unavailable: graph context written without graph artifacts")
        return 0

    result = subprocess.run(
        [
            graphify_python,
            "-c",
            GRAPHIFY_BUILD_CODE,
            extraction_path,
            os.path.abspath(args.graphify_out_dir),
            "1" if args.emit_html else "0",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        reason = result.stderr.strip() or result.stdout.strip() or "graphify build failed"
        write_unavailable_context(args.graphify_out_dir, args.normalized_input, f"graphify build failed: {reason}")
        print("graphify build failed; graph_context.json contains the failure reason")
        return 0

    print(result.stdout.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
