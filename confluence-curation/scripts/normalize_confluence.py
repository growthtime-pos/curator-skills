#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set


STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "have",
    "will",
    "your",
    "into",
    "page",
    "pages",
    "문서",
    "정리",
    "관련",
    "대한",
    "에서",
    "있는",
    "하기",
    "그리고",
    "으로",
    "합니다",
}


def iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Normalize fetched Confluence data for downstream analysis.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-sentences", type=int, default=12)
    parser.add_argument("--max-keywords", type=int, default=12)
    parser.add_argument("--min-sentence-length", type=int, default=18)
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


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def split_sentences(text: str, min_length: int) -> List[str]:
    if not text:
        return []
    parts = re.split(r"(?<=[.!?।다요])\s+|\n+", text)
    sentences: List[str] = []
    for part in parts:
        sentence = normalize_whitespace(part).strip("-|• ")
        if len(sentence) >= min_length:
            sentences.append(sentence)
    return sentences


def extract_keywords(title: str, body_excerpt: str, max_keywords: int) -> List[str]:
    text = f"{title} {body_excerpt}".lower()
    tokens = re.findall(r"[a-z0-9가-힣]{3,}", text)
    counts = Counter(token for token in tokens if token not in STOPWORDS)
    return [token for token, _ in counts.most_common(max_keywords)]


def extract_claim_candidates(sentences: List[str], limit: int = 5) -> List[str]:
    preferred: List[str] = []
    fallback: List[str] = []
    for sentence in sentences:
        if len(sentence) > 240:
            sentence = sentence[:237] + "..."
        if re.search(r"(정의|목적|절차|정책|기준|원칙|방법|요약|설명|활용|특징|구성|중요|의미|must|should|process|policy|guide|owner)", sentence, re.IGNORECASE):
            preferred.append(sentence)
        else:
            fallback.append(sentence)
    claims = preferred[:limit]
    if len(claims) < limit:
        claims.extend(fallback[: limit - len(claims)])
    return claims


def build_page_relationship_index(relationships: List[Dict[str, Any]]) -> Dict[str, Dict[str, List[str]]]:
    index: Dict[str, Dict[str, List[str]]] = {}
    for relationship in relationships:
        from_page_id = relationship.get("from_page_id")
        to_page_id = relationship.get("to_page_id")
        rel_type = relationship.get("type", "unknown")
        if not from_page_id or not to_page_id:
            continue
        bucket = index.setdefault(from_page_id, {})
        bucket.setdefault(rel_type, []).append(to_page_id)
    return index


def summarize_people(people: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    people_by_id: Dict[str, Dict[str, Any]] = {}
    for person in people:
        account_id = person.get("account_id")
        if not account_id:
            continue
        people_by_id[account_id] = {
            "account_id": account_id,
            "display_name": person.get("display_name") or account_id,
            "public_name": person.get("public_name") or person.get("display_name") or account_id,
            "email": person.get("email"),
            "team": ((person.get("org_hint") or {}).get("team")),
            "title": ((person.get("org_hint") or {}).get("title")),
            "role_band": ((person.get("org_hint") or {}).get("role_band", "unknown")),
            "confidence": ((person.get("org_hint") or {}).get("confidence", "low")),
        }
    return people_by_id


def collect_maintainer_signals(recent_contributors: List[str], people_by_id: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    signals: List[Dict[str, Any]] = []
    for account_id in recent_contributors:
        person = people_by_id.get(account_id)
        if not person:
            signals.append(
                {
                    "account_id": account_id,
                    "display_name": account_id,
                    "team": None,
                    "title": None,
                    "role_band": "unknown",
                    "confidence": "low",
                }
            )
            continue
        signals.append(person)
    return signals


def normalize_pages(
    pages: List[Dict[str, Any]],
    people_by_id: Dict[str, Dict[str, Any]],
    relationship_index: Dict[str, Dict[str, List[str]]],
    max_sentences: int,
    max_keywords: int,
    min_sentence_length: int,
) -> List[Dict[str, Any]]:
    normalized_pages: List[Dict[str, Any]] = []
    for page in pages:
        body_excerpt = (page.get("body_excerpt") or "").strip()
        sentences = split_sentences(body_excerpt, min_sentence_length)
        keywords = extract_keywords(page.get("title") or "", body_excerpt, max_keywords)
        claim_candidates = extract_claim_candidates(sentences)
        recent_contributors = page.get("recent_contributors", [])
        normalized_pages.append(
            {
                "page_id": page.get("page_id"),
                "title": page.get("title"),
                "url": page.get("url"),
                "space_key": page.get("space_key"),
                "status": page.get("status", "current"),
                "created_at": page.get("created_at"),
                "updated_at": page.get("updated_at"),
                "updated_days_ago": days_ago(page.get("updated_at")),
                "version_number": page.get("version_number"),
                "labels": page.get("labels", []),
                "ancestors": page.get("ancestors", []),
                "version_events": page.get("version_events", []),
                "body_excerpt": body_excerpt,
                "body_hash": page.get("body_hash"),
                "sentences": sentences[:max_sentences],
                "keywords": keywords,
                "claim_candidates": claim_candidates,
                "recent_contributors": recent_contributors,
                "reference_snapshot": page.get("reference_snapshot", {}),
                "change_summary": page.get("change_summary", {}),
                "maintainer_signals": collect_maintainer_signals(recent_contributors, people_by_id),
                "relationship_targets": relationship_index.get(page.get("page_id"), {}),
                "discovery_source": page.get("discovery_source", "query_seed"),
                "discovery_reasons": page.get("discovery_reasons", []),
                "retrieval_paths": page.get("retrieval_paths", []),
                "preferred_space_match": bool(page.get("preferred_space_match")),
                "signals": {
                    "has_body_excerpt": bool(body_excerpt),
                    "has_labels": bool(page.get("labels")),
                    "has_ancestors": bool(page.get("ancestors")),
                    "has_recent_contributors": bool(recent_contributors),
                    "has_reference_snapshot": bool((page.get("reference_snapshot") or {}).get("has_reference")),
                    "has_meaningful_change": bool((page.get("change_summary") or {}).get("changed")),
                },
            }
        )
    return normalized_pages


def build_topic_seed_index(normalized_pages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    topic_seeds: List[Dict[str, Any]] = []
    for page in normalized_pages:
        topic_seeds.append(
            {
                "page_id": page["page_id"],
                "title": page["title"],
                "space_key": page.get("space_key"),
                "keywords": page.get("keywords", [])[:6],
                "updated_days_ago": page.get("updated_days_ago"),
                "recent_contributors": page.get("recent_contributors", [])[:3],
            }
        )
    return topic_seeds


def collect_missing_signals(pages: List[Dict[str, Any]], people_by_id: Dict[str, Dict[str, Any]]) -> List[str]:
    missing: Set[str] = set()
    for page in pages:
        if not page.get("body_excerpt"):
            missing.add(f"페이지 {page.get('page_id')} 는 본문 excerpt 가 없습니다.")
        if not page.get("recent_contributors"):
            missing.add(f"페이지 {page.get('page_id')} 는 최근 기여자 정보가 없습니다.")
        for account_id in page.get("recent_contributors", []):
            if account_id not in people_by_id:
                missing.add(f"사용자 {account_id} 의 프로필 요약이 없습니다.")
    return sorted(missing)


def main() -> int:
    args = parse_args()
    with open(args.input, "r", encoding="utf-8") as handle:
        payload = json.load(handle)

    meta = payload.get("meta", {})
    pages = payload.get("pages", [])
    people = payload.get("people", [])
    relationships = payload.get("relationships", [])
    warnings = payload.get("warnings", [])

    people_by_id = summarize_people(people)
    relationship_index = build_page_relationship_index(relationships)
    normalized_pages = normalize_pages(
        pages,
        people_by_id,
        relationship_index,
        args.max_sentences,
        args.max_keywords,
        args.min_sentence_length,
    )

    result = {
        "meta": {
            "generated_at": iso_now(),
            "source_type": "fetch_confluence",
            "source_meta": meta,
            "page_count": len(normalized_pages),
            "relationship_count": len(relationships),
            "normalization": {
                "max_sentences": args.max_sentences,
                "max_keywords": args.max_keywords,
                "min_sentence_length": args.min_sentence_length,
            },
        },
        "pages": normalized_pages,
        "people": list(people_by_id.values()),
        "relationships": relationships,
        "topic_seeds": build_topic_seed_index(normalized_pages),
        "warnings": warnings,
        "missing_signals": collect_missing_signals(pages, people_by_id),
    }

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
