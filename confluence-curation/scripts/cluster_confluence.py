#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Set


def iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cluster normalized Confluence pages into topic groups.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--title-threshold", type=float, default=0.82)
    parser.add_argument("--keyword-overlap", type=int, default=2)
    parser.add_argument("--shared-contributors", type=int, default=1)
    return parser.parse_args()


def parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def days_ago(value: Optional[str]) -> Optional[int]:
    dt = parse_datetime(value)
    if not dt:
        return None
    return max(0, (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).days)


def title_key(title: str) -> str:
    return re.sub(r"[^a-z0-9가-힣]+", "", (title or "").lower())


def title_similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, title_key(left), title_key(right)).ratio()


def share_ancestor(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
    left_ids = {ancestor.get("page_id") for ancestor in left.get("ancestors", [])}
    right_ids = {ancestor.get("page_id") for ancestor in right.get("ancestors", [])}
    return bool(left_ids & right_ids)


def shared_contributor_count(left: Dict[str, Any], right: Dict[str, Any]) -> int:
    return len(set(left.get("recent_contributors", [])) & set(right.get("recent_contributors", [])))


def shared_label_count(left: Dict[str, Any], right: Dict[str, Any]) -> int:
    return len(set(left.get("labels", [])) & set(right.get("labels", [])))


def shared_keyword_count(left: Dict[str, Any], right: Dict[str, Any]) -> int:
    return len(set(left.get("keywords", [])) & set(right.get("keywords", [])))


def relationship_link_types(left: Dict[str, Any], right_page_id: str) -> List[str]:
    matches: List[str] = []
    targets = left.get("relationship_targets", {})
    for rel_type, page_ids in targets.items():
        if right_page_id in page_ids:
            matches.append(rel_type)
    return matches


def pair_evidence(
    left: Dict[str, Any],
    right: Dict[str, Any],
    title_threshold: float,
    keyword_overlap: int,
    shared_contributors_threshold: int,
) -> Optional[Dict[str, Any]]:
    title_score = title_similarity(left.get("title", ""), right.get("title", ""))
    shared_keywords = shared_keyword_count(left, right)
    shared_contributors = shared_contributor_count(left, right)
    shared_labels = shared_label_count(left, right)
    same_ancestor = share_ancestor(left, right)
    direct_links = relationship_link_types(left, right.get("page_id")) + relationship_link_types(right, left.get("page_id"))

    reasons: List[str] = []
    score = 0.0
    if title_score >= title_threshold:
        reasons.append(f"title_similarity={title_score:.2f}")
        score += 3.0
    if shared_keywords >= keyword_overlap:
        reasons.append(f"shared_keywords={shared_keywords}")
        score += 2.0
    if shared_contributors >= shared_contributors_threshold:
        reasons.append(f"shared_contributors={shared_contributors}")
        score += 1.5
    if shared_labels >= 1:
        reasons.append(f"shared_labels={shared_labels}")
        score += 1.0
    if same_ancestor:
        reasons.append("shared_ancestor")
        score += 1.5
    if direct_links:
        reasons.append("relationship=" + ",".join(sorted(set(direct_links))))
        score += 2.0

    if score < 3.0:
        return None
    return {
        "left_page_id": left.get("page_id"),
        "right_page_id": right.get("page_id"),
        "score": round(score, 2),
        "reasons": reasons,
    }


def build_adjacency(
    pages: List[Dict[str, Any]],
    title_threshold: float,
    keyword_overlap: int,
    shared_contributors_threshold: int,
) -> Dict[str, List[Dict[str, Any]]]:
    adjacency: Dict[str, List[Dict[str, Any]]] = {page["page_id"]: [] for page in pages}
    for index, left in enumerate(pages):
        for right in pages[index + 1 :]:
            evidence = pair_evidence(
                left,
                right,
                title_threshold,
                keyword_overlap,
                shared_contributors_threshold,
            )
            if not evidence:
                continue
            adjacency[left["page_id"]].append(evidence)
            adjacency[right["page_id"]].append(
                {
                    "left_page_id": right["page_id"],
                    "right_page_id": left["page_id"],
                    "score": evidence["score"],
                    "reasons": evidence["reasons"],
                }
            )
    return adjacency


def connected_components(pages: List[Dict[str, Any]], adjacency: Dict[str, List[Dict[str, Any]]]) -> List[List[str]]:
    page_ids = {page["page_id"] for page in pages}
    seen: Set[str] = set()
    components: List[List[str]] = []
    for page_id in page_ids:
        if page_id in seen:
            continue
        stack = [page_id]
        component: List[str] = []
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            component.append(current)
            for edge in adjacency.get(current, []):
                neighbor = edge.get("right_page_id")
                if neighbor and neighbor not in seen:
                    stack.append(neighbor)
        components.append(component)
    return components


def confidence_label(size: int, average_score: float, evidence_types: Set[str]) -> str:
    if size >= 3 and average_score >= 4.5 and len(evidence_types) >= 3:
        return "high"
    if average_score >= 3.5 and len(evidence_types) >= 2:
        return "medium"
    return "low"


def representative_keywords(pages: List[Dict[str, Any]], limit: int = 8) -> List[str]:
    counts = Counter()
    for page in pages:
        counts.update(page.get("keywords", []))
    return [keyword for keyword, _ in counts.most_common(limit)]


def choose_current_page(pages: List[Dict[str, Any]]) -> Dict[str, Any]:
    return min(
        pages,
        key=lambda page: (
            page.get("updated_days_ago") if page.get("updated_days_ago") is not None else 999999,
            -(len(page.get("recent_contributors", []))),
        ),
    )


def choose_background_page(pages: List[Dict[str, Any]]) -> Dict[str, Any]:
    return max(
        pages,
        key=lambda page: (
            len(page.get("ancestors", [])),
            -(page.get("updated_days_ago") if page.get("updated_days_ago") is not None else 999999),
        ),
    )


def build_clusters(
    pages: List[Dict[str, Any]],
    adjacency: Dict[str, List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    page_lookup = {page["page_id"]: page for page in pages}
    clusters: List[Dict[str, Any]] = []
    components = connected_components(pages, adjacency)
    multi_page_index = 1

    for component in components:
        cluster_pages = [page_lookup[page_id] for page_id in component]
        cluster_pages.sort(
            key=lambda page: (
                page.get("updated_days_ago") if page.get("updated_days_ago") is not None else 999999,
                page.get("title") or "",
            )
        )
        current_page = choose_current_page(cluster_pages)
        background_page = choose_background_page(cluster_pages)

        pair_links: List[Dict[str, Any]] = []
        evidence_types: Set[str] = set()
        for page_id in component:
            for edge in adjacency.get(page_id, []):
                right_page_id = edge.get("right_page_id")
                if right_page_id not in component:
                    continue
                if page_id < right_page_id:
                    pair_links.append(edge)
                    for reason in edge.get("reasons", []):
                        evidence_types.add(reason.split("=", 1)[0])

        average_score = sum(edge.get("score", 0.0) for edge in pair_links) / len(pair_links) if pair_links else 0.0
        label = current_page.get("title") if len(cluster_pages) > 1 else f"single::{current_page.get('title')}"
        cluster_id = f"topic_{multi_page_index:03d}" if len(cluster_pages) > 1 else f"singleton_{current_page.get('page_id')}"
        if len(cluster_pages) > 1:
            multi_page_index += 1

        clusters.append(
            {
                "cluster_id": cluster_id,
                "label": label,
                "page_ids": [page["page_id"] for page in cluster_pages],
                "page_count": len(cluster_pages),
                "likely_current_page_id": current_page.get("page_id"),
                "likely_background_page_id": background_page.get("page_id"),
                "keywords": representative_keywords(cluster_pages),
                "confidence": confidence_label(len(cluster_pages), average_score, evidence_types),
                "average_link_score": round(average_score, 2),
                "evidence_types": sorted(evidence_types),
                "pages": [
                    {
                        "page_id": page.get("page_id"),
                        "title": page.get("title"),
                        "space_key": page.get("space_key"),
                        "updated_at": page.get("updated_at"),
                        "updated_days_ago": page.get("updated_days_ago"),
                        "keywords": page.get("keywords", [])[:6],
                        "recent_contributors": page.get("recent_contributors", [])[:3],
                    }
                    for page in cluster_pages
                ],
                "pair_links": pair_links,
            }
        )

    clusters.sort(key=lambda cluster: (-cluster["page_count"], cluster["label"]))
    return clusters


def summarize_clusters(clusters: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "cluster_count": len(clusters),
        "multi_page_cluster_count": len([cluster for cluster in clusters if cluster["page_count"] > 1]),
        "singleton_count": len([cluster for cluster in clusters if cluster["page_count"] == 1]),
        "largest_cluster_size": max((cluster["page_count"] for cluster in clusters), default=0),
    }


def main() -> int:
    args = parse_args()
    with open(args.input, "r", encoding="utf-8") as handle:
        payload = json.load(handle)

    pages = payload.get("pages", [])
    adjacency = build_adjacency(pages, args.title_threshold, args.keyword_overlap, args.shared_contributors)
    clusters = build_clusters(pages, adjacency)

    result = {
        "meta": {
            "generated_at": iso_now(),
            "source_type": "normalize_confluence",
            "source_meta": payload.get("meta", {}),
            "thresholds": {
                "title_threshold": args.title_threshold,
                "keyword_overlap": args.keyword_overlap,
                "shared_contributors": args.shared_contributors,
            },
        },
        "summary": summarize_clusters(clusters),
        "clusters": clusters,
        "warnings": payload.get("warnings", []),
        "missing_signals": payload.get("missing_signals", []),
    }

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
