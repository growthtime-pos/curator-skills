#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


CONFIDENCE_KO = {"high": "높음", "medium": "보통", "low": "낮음"}


def iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract topic-level evidence packs from normalized pages and clusters.")
    parser.add_argument("--normalized-input", required=True)
    parser.add_argument("--clusters-input", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--emit-manifest")
    parser.add_argument("--max-snippets", type=int, default=4)
    parser.add_argument("--max-maintainers", type=int, default=4)
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


def page_freshness_score(page: Dict[str, Any]) -> int:
    updated_days = page.get("updated_days_ago")
    score = 0
    if updated_days is None:
        return 0
    if updated_days <= 7:
        score += 45
    elif updated_days <= 30:
        score += 35
    elif updated_days <= 90:
        score += 22
    elif updated_days <= 180:
        score += 10
    score += min(len(page.get("version_events", [])), 5) * 5
    score += min(len(page.get("recent_contributors", [])), 4) * 4
    return min(score, 100)


def maintainer_score(signal: Dict[str, Any]) -> float:
    role_score = {
        "director": 9.0,
        "lead": 8.0,
        "staff": 7.0,
        "individual": 6.0,
        "unknown": 2.0,
    }.get(signal.get("role_band", "unknown"), 2.0)
    confidence_multiplier = {
        "high": 1.0,
        "medium": 0.8,
        "low": 0.4,
    }.get(signal.get("confidence", "low"), 0.4)
    return role_score * confidence_multiplier


def page_trust_score(page: Dict[str, Any]) -> int:
    score = 0.0
    score += min(len(page.get("ancestors", [])), 3) * 6.0
    score += min(len(page.get("labels", [])), 4) * 3.0
    score += min(len(page.get("recent_contributors", [])), 4) * 4.0
    score += min(len(page.get("keywords", [])), 8) * 1.0
    for signal in page.get("maintainer_signals", []):
        score += maintainer_score(signal)
    return min(int(round(score)), 100)


def candidate_sort_key(page: Dict[str, Any], mode: str) -> Tuple[int, int, int, str]:
    freshness = page_freshness_score(page)
    trust = page_trust_score(page)
    updated_days = page.get("updated_days_ago")
    updated_rank = -(999999 if updated_days is None else (999999 - updated_days))
    if mode == "current":
        return (freshness, trust, len(page.get("recent_contributors", [])), page.get("page_id", ""))
    if mode == "trusted":
        return (trust, freshness, len(page.get("ancestors", [])), page.get("page_id", ""))
    return (-freshness, trust, -len(page.get("recent_contributors", [])), updated_rank)


def choose_candidates(cluster_pages: List[Dict[str, Any]]) -> Dict[str, Optional[Dict[str, Any]]]:
    if not cluster_pages:
        return {
            "current": None,
            "trusted": None,
            "stale": None,
        }

    current = max(cluster_pages, key=lambda page: candidate_sort_key(page, "current"))
    trusted = max(cluster_pages, key=lambda page: candidate_sort_key(page, "trusted"))
    stale_candidates = [
        page
        for page in cluster_pages
        if page.get("updated_days_ago") is not None and page.get("updated_days_ago", 0) > 60
    ]
    stale = max(stale_candidates, key=lambda page: candidate_sort_key(page, "stale")) if stale_candidates else None
    return {
        "current": current,
        "trusted": trusted,
        "stale": stale,
    }


def pick_snippets(page: Dict[str, Any], limit: int) -> List[str]:
    snippets = page.get("claim_candidates") or page.get("sentences") or []
    return snippets[:limit]


def summarize_maintainers(cluster_pages: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    aggregate: Dict[str, Dict[str, Any]] = {}
    for page in cluster_pages:
        for signal in page.get("maintainer_signals", []):
            account_id = signal.get("account_id") or signal.get("display_name")
            if not account_id:
                continue
            item = aggregate.setdefault(
                account_id,
                {
                    "account_id": signal.get("account_id"),
                    "display_name": signal.get("display_name") or account_id,
                    "team": signal.get("team"),
                    "title": signal.get("title"),
                    "role_band": signal.get("role_band", "unknown"),
                    "confidence": signal.get("confidence", "low"),
                    "page_ids": [],
                    "score": 0.0,
                },
            )
            item["score"] += maintainer_score(signal)
            if page.get("page_id") not in item["page_ids"]:
                item["page_ids"].append(page.get("page_id"))

    maintainers = list(aggregate.values())
    maintainers.sort(key=lambda item: (item["score"], len(item["page_ids"])), reverse=True)
    return maintainers[:limit]


def summarize_changes(cluster_pages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    changes: List[Dict[str, Any]] = []
    for page in cluster_pages:
        if page.get("updated_at"):
            changes.append(
                {
                    "page_id": page.get("page_id"),
                    "title": page.get("title"),
                    "updated_at": page.get("updated_at"),
                    "kind": "page_update",
                    "summary": f"{page.get('title')} 문서가 {page.get('updated_at')} 에 갱신되었습니다.",
                }
            )
        for event in page.get("version_events", [])[:3]:
            if event.get("updated_at"):
                message = (event.get("message") or "").strip()
                changes.append(
                    {
                        "page_id": page.get("page_id"),
                        "title": page.get("title"),
                        "updated_at": event.get("updated_at"),
                        "kind": "version_event",
                        "summary": (
                            f"{page.get('title')} 버전 {event.get('version')} 이 {event.get('updated_at')} 에 기록되었습니다."
                            + (f" 변경 메모: {message}" if message else "")
                        ),
                    }
                )
    changes.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
    return changes[:10]


def conflict_notes(cluster: Dict[str, Any], cluster_pages: List[Dict[str, Any]], candidates: Dict[str, Optional[Dict[str, Any]]]) -> List[str]:
    notes: List[str] = []
    current = candidates.get("current")
    trusted = candidates.get("trusted")
    stale = candidates.get("stale")

    if cluster.get("page_count", 0) > 1:
        notes.append(f"연관된 페이지 {cluster.get('page_count')}개가 하나의 클러스터로 묶였습니다.")
    if current and trusted and current.get("page_id") != trusted.get("page_id"):
        notes.append("현재 기준 후보와 신뢰 기준 후보가 서로 다릅니다.")
    if stale:
        notes.append(f"오래된 문서 후보로 `{stale.get('title')}` 가 확인됩니다.")
    if cluster.get("confidence") == "low" and cluster.get("page_count", 0) > 1:
        notes.append("연관 페이지가 여러 개지만 클러스터 확신도는 낮습니다.")

    keywords = [set(page.get("keywords", [])) for page in cluster_pages]
    if keywords and len(keywords) > 1:
        shared = set.intersection(*keywords) if len(keywords) > 1 else set()
        if len(shared) <= 1 and cluster.get("page_count", 0) > 1:
            notes.append("연관 페이지들 사이의 핵심 키워드 겹침이 약합니다.")
    return notes


def collect_missing_signals(cluster_pages: List[Dict[str, Any]], global_missing: List[str]) -> List[str]:
    page_ids = {page.get("page_id") for page in cluster_pages}
    filtered = [item for item in global_missing if any(page_id in item for page_id in page_ids if page_id)]
    for page in cluster_pages:
        if not page.get("body_excerpt"):
            filtered.append(f"페이지 {page.get('page_id')} 에는 본문 excerpt 가 없습니다.")
        if not page.get("recent_contributors"):
            filtered.append(f"페이지 {page.get('page_id')} 에는 최근 기여자 정보가 없습니다.")
    return sorted(set(filtered))


def page_summary(page: Optional[Dict[str, Any]], max_snippets: int) -> Optional[Dict[str, Any]]:
    if not page:
        return None
    return {
        "page_id": page.get("page_id"),
        "title": page.get("title"),
        "url": page.get("url"),
        "space_key": page.get("space_key"),
        "updated_at": page.get("updated_at"),
        "updated_days_ago": page.get("updated_days_ago"),
        "freshness_score": page_freshness_score(page),
        "trust_score": page_trust_score(page),
        "recent_contributors": page.get("recent_contributors", []),
        "labels": page.get("labels", []),
        "keywords": page.get("keywords", [])[:8],
        "snippets": pick_snippets(page, max_snippets),
    }


def build_evidence_pack(
    cluster: Dict[str, Any],
    normalized_pages: Dict[str, Dict[str, Any]],
    global_missing: List[str],
    warnings: List[str],
    max_snippets: int,
    max_maintainers: int,
) -> Dict[str, Any]:
    cluster_pages = [normalized_pages[page_id] for page_id in cluster.get("page_ids", []) if page_id in normalized_pages]
    candidates = choose_candidates(cluster_pages)
    evidence_snippets: List[Dict[str, Any]] = []
    for page in cluster_pages:
        snippets = pick_snippets(page, max_snippets)
        if snippets:
            evidence_snippets.append(
                {
                    "page_id": page.get("page_id"),
                    "title": page.get("title"),
                    "snippets": snippets,
                }
            )

    return {
        "topic_id": cluster.get("cluster_id"),
        "label": cluster.get("label"),
        "confidence": cluster.get("confidence"),
        "confidence_ko": CONFIDENCE_KO.get(cluster.get("confidence"), "알 수 없음"),
        "page_ids": cluster.get("page_ids", []),
        "current_candidate": page_summary(candidates.get("current"), max_snippets),
        "trusted_candidate": page_summary(candidates.get("trusted"), max_snippets),
        "stale_candidate": page_summary(candidates.get("stale"), max_snippets),
        "maintainer_signals": summarize_maintainers(cluster_pages, max_maintainers),
        "recent_changes": summarize_changes(cluster_pages),
        "conflict_notes": conflict_notes(cluster, cluster_pages, candidates),
        "missing_signals": collect_missing_signals(cluster_pages, global_missing),
        "evidence_snippets": evidence_snippets,
        "pair_links": cluster.get("pair_links", []),
        "warnings": warnings,
    }


def main() -> int:
    args = parse_args()
    with open(args.normalized_input, "r", encoding="utf-8") as handle:
        normalized_payload = json.load(handle)
    with open(args.clusters_input, "r", encoding="utf-8") as handle:
        cluster_payload = json.load(handle)

    normalized_pages = {
        page["page_id"]: page
        for page in normalized_payload.get("pages", [])
        if page.get("page_id")
    }
    clusters = cluster_payload.get("clusters", [])
    warnings = sorted(set(normalized_payload.get("warnings", []) + cluster_payload.get("warnings", [])))
    global_missing = sorted(
        set(normalized_payload.get("missing_signals", []) + cluster_payload.get("missing_signals", []))
    )

    os.makedirs(args.output_dir, exist_ok=True)
    manifest: List[Dict[str, Any]] = []
    for cluster in clusters:
        pack = build_evidence_pack(
            cluster,
            normalized_pages,
            global_missing,
            warnings,
            args.max_snippets,
            args.max_maintainers,
        )
        output_path = os.path.abspath(os.path.join(args.output_dir, f"{pack['topic_id']}.json"))
        with open(output_path, "w", encoding="utf-8") as handle:
            json.dump(pack, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        manifest.append(
            {
                "topic_id": pack["topic_id"],
                "label": pack["label"],
                "page_count": len(pack["page_ids"]),
                "confidence": pack["confidence"],
                "output_path": output_path,
            }
        )

    if args.emit_manifest:
        payload = {
            "meta": {
                "generated_at": iso_now(),
                "source_type": "extract_evidence",
                "normalized_input": args.normalized_input,
                "clusters_input": args.clusters_input,
                "pack_count": len(manifest),
            },
            "packs": manifest,
            "warnings": warnings,
        }
        with open(args.emit_manifest, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
