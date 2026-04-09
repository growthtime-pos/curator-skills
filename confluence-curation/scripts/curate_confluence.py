#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

from data_store import default_data_dir, persist_feature_state


STATUS_KO = {
    "fresh-and-trusted": "최신·신뢰 높음",
    "fresh-but-unverified": "최신이나 검증 부족",
    "trusted-but-stale": "신뢰 높으나 오래됨",
    "likely-duplicate": "중복 가능성",
    "likely-superseded": "대체됨 가능성",
    "needs-review": "검토 필요",
}


CONFIDENCE_KO = {"high": "높음", "medium": "보통", "low": "낮음"}
VERDICT_KO = {"approved": "승인", "review": "추가 검토", "revise": "수정 필요"}
ANALYSIS_METHOD_LABELS = {
    "evidence-first": "evidence-first",
    "pyramid": "pyramid",
    "hypothesis-driven": "hypothesis-driven",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Curate fetched Confluence metadata into Korean Markdown.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--expansion-input")
    parser.add_argument("--insights-input")
    parser.add_argument("--review-input")
    parser.add_argument("--top-n", type=int, default=20)
    parser.add_argument("--recent-days-strong", type=int, default=30)
    parser.add_argument("--recent-days-medium", type=int, default=90)
    parser.add_argument("--title-similarity-threshold", type=float, default=0.82)
    parser.add_argument("--people-signal-weight", type=float, default=35.0)
    parser.add_argument("--freshness-weight", type=float, default=40.0)
    parser.add_argument("--relationship-weight", type=float, default=25.0)
    parser.add_argument("--emit-json-summary")
    parser.add_argument("--data-dir", default=os.getenv("CONFLUENCE_DATA_DIR") or default_data_dir())
    parser.add_argument("--purpose", default="general", choices=["general", "change-tracking", "onboarding"])
    parser.add_argument("--analysis-method", default="evidence-first", choices=list(ANALYSIS_METHOD_LABELS))
    return parser.parse_args()


def read_json(path: Optional[str]) -> Optional[Dict[str, Any]]:
    if not path:
        return None
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def merge_expansion_payload(payload: Dict[str, Any], expansion_payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not expansion_payload:
        return payload

    pages = list(payload.get("pages", []))
    people = list(payload.get("people", []))
    relationships = list(payload.get("relationships", []))
    warnings = list(payload.get("warnings", []))
    preferred_spaces = expansion_payload.get("preferred_spaces", [])

    page_ids = {page.get("page_id") for page in pages}
    person_ids = {person.get("account_id") for person in people if person}
    relationship_keys = {
        (rel.get("from_page_id"), rel.get("to_page_id"), rel.get("type"))
        for rel in relationships
    }

    for page in pages:
        page.setdefault("discovery_source", "query_seed")
        page.setdefault("discovery_reasons", ["키워드 검색 시드"])
        page.setdefault("preferred_space_match", page.get("space_key") in preferred_spaces if preferred_spaces else False)
        page.setdefault("preferred_space_boost", 8 if page.get("preferred_space_match") else 0)

    for page in expansion_payload.get("expanded_pages", []):
        page_id = page.get("page_id")
        if not page_id or page_id in page_ids:
            continue
        expanded_page = dict(page)
        expanded_page.setdefault("discovery_source", "preferred_space_expansion")
        expanded_page.setdefault("discovery_reasons", [])
        expanded_page.setdefault("preferred_space_match", True)
        expanded_page.setdefault("preferred_space_boost", 8 if expanded_page.get("preferred_space_match") else 0)
        pages.append(expanded_page)
        page_ids.add(page_id)

    for person in expansion_payload.get("people", []):
        account_id = person.get("account_id") if person else None
        if not account_id or account_id in person_ids:
            continue
        people.append(person)
        person_ids.add(account_id)

    for rel in expansion_payload.get("links", []):
        key = (rel.get("from_page_id"), rel.get("to_page_id"), rel.get("type"))
        if key in relationship_keys:
            continue
        relationships.append(rel)
        relationship_keys.add(key)

    for warning in expansion_payload.get("warnings", []):
        if warning not in warnings:
            warnings.append(warning)

    meta = dict(payload.get("meta", {}))
    scope = dict(meta.get("scope", {}))
    scope["preferred_spaces"] = preferred_spaces
    scope["expanded_page_ids"] = [page.get("page_id") for page in expansion_payload.get("expanded_pages", []) if page.get("page_id")]
    scope["query_seed_page_ids"] = expansion_payload.get("seed_page_ids", [])
    meta["scope"] = scope
    meta["preferred_space_expansion"] = {
        "used": True,
        "artifact_schema_version": ((expansion_payload.get("meta") or {}).get("schema_version")),
        "expanded_page_count": len(expansion_payload.get("expanded_pages", [])),
    }

    merged = dict(payload)
    merged["meta"] = meta
    merged["pages"] = pages
    merged["people"] = people
    merged["relationships"] = relationships
    merged["warnings"] = warnings
    return merged


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


def title_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def score_freshness(page: Dict[str, Any], strong_days: int, medium_days: int) -> Tuple[int, List[str]]:
    evidence: List[str] = []
    updated_days = days_ago(page.get("updated_at"))
    version_count = len(page.get("version_events", []))
    contributor_count = len(page.get("recent_contributors", []))
    score = 0.0

    if updated_days is None:
        evidence.append("최근 수정일 정보가 부족합니다")
    elif updated_days <= 7:
        score += 40
        evidence.append("최근 7일 내 수정")
    elif updated_days <= strong_days:
        score += 34
        evidence.append(f"최근 {strong_days}일 내 수정")
    elif updated_days <= medium_days:
        score += 24
        evidence.append(f"최근 {medium_days}일 내 수정")
    elif updated_days <= 180:
        score += 12
        evidence.append("최근 수정은 있으나 다소 오래됨")
    else:
        evidence.append("오래된 문서로 보임")

    score += min(version_count, 5) * 4
    if version_count:
        evidence.append(f"최근 버전 이력 {version_count}건 확인")
    score += min(contributor_count, 4) * 5
    if contributor_count >= 2:
        evidence.append(f"최근 기여자 {contributor_count}명")

    return min(100, round(score)), evidence


def score_change_signal(page: Dict[str, Any]) -> Tuple[int, List[str]]:
    change = page.get("change_summary") or {}
    if not change:
        return 0, []
    score = min(int(change.get("importance_score", 0) or 0), 18)
    evidence: List[str] = []
    if change.get("summary_ko"):
        evidence.append(change["summary_ko"])
    if change.get("has_reference") and not change.get("changed"):
        evidence.append("저장된 기준본을 배경 참고로 함께 사용했습니다.")
    return score, evidence[:2]


def score_people(page: Dict[str, Any], people_by_id: Dict[str, Dict[str, Any]]) -> Tuple[float, List[str], bool]:
    evidence: List[str] = []
    missing = False
    total = 0.0
    contributors = page.get("recent_contributors", [])
    for account_id in contributors:
        person = people_by_id.get(account_id)
        if not person:
            missing = True
            continue
        hint = person.get("org_hint", {})
        confidence = hint.get("confidence", "low")
        role_band = hint.get("role_band", "unknown")
        title = hint.get("title")
        team = hint.get("team")

        band_score = {
            "director": 9,
            "lead": 8,
            "staff": 7,
            "individual": 6,
            "unknown": 2,
        }.get(role_band, 2)
        confidence_multiplier = {"high": 1.0, "medium": 0.8, "low": 0.4}.get(confidence, 0.4)
        total += band_score * confidence_multiplier
        if title or team:
            parts = [part for part in [team, title] if part]
            evidence.append(f"{person.get('display_name')}: {' / '.join(parts)}")
        else:
            missing = True

    if not contributors:
        missing = True
        evidence.append("기여자 정보가 부족합니다")
    return min(35.0, total), evidence[:3], missing


def score_relationships(
    page: Dict[str, Any],
    relationships: List[Dict[str, Any]],
    page_lookup: Dict[str, Dict[str, Any]],
) -> Tuple[float, List[str], bool, bool]:
    evidence: List[str] = []
    inbound = [rel for rel in relationships if rel.get("to_page_id") == page["page_id"]]
    related = [rel for rel in inbound if rel.get("type") == "related_title"]
    ancestor = [rel for rel in inbound if rel.get("type") == "ancestor"]
    child = [rel for rel in inbound if rel.get("type") == "child"]

    score = min(20.0, len(inbound) * 4.0)
    duplicate = False
    superseded = False

    if ancestor:
        evidence.append("상위 구조 안에서 관리되는 문서")
        score += 4
    if child:
        evidence.append("다른 문서와 계층 관계가 확인됨")
        score += 3
    if related:
        score += min(8.0, len(related) * 3.0)
        evidence.append(f"유사 제목 문서 {len(related)}건")
        newer_related = []
        for rel in related:
            other = page_lookup.get(rel.get("from_page_id"))
            if not other:
                continue
            if (days_ago(other.get("updated_at")) or math.inf) < (days_ago(page.get("updated_at")) or math.inf):
                newer_related.append(other)
        duplicate = len(related) >= 1
        superseded = bool(newer_related) and (days_ago(page.get("updated_at")) or math.inf) > 60

    return min(25.0, score), evidence, duplicate, superseded


def compute_confidence(freshness: int, trust: int, missing_people: bool, duplicate: bool, warnings: List[str]) -> str:
    confidence_score = 0
    if freshness >= 60:
        confidence_score += 1
    if trust >= 60:
        confidence_score += 1
    if not missing_people:
        confidence_score += 1
    if not duplicate:
        confidence_score += 1
    if warnings:
        confidence_score -= 1
    if confidence_score >= 3:
        return "high"
    if confidence_score >= 2:
        return "medium"
    return "low"


def determine_status(
    freshness: int,
    trust: int,
    confidence: str,
    duplicate: bool,
    superseded: bool,
) -> str:
    if superseded:
        return "likely-superseded"
    if duplicate:
        return "likely-duplicate"
    if freshness >= 65 and trust >= 65 and confidence != "low":
        return "fresh-and-trusted"
    if freshness >= 65 and trust < 65:
        return "fresh-but-unverified"
    if freshness < 65 and trust >= 65:
        return "trusted-but-stale"
    return "needs-review"


def cluster_pages(pages: List[Dict[str, Any]], threshold: float) -> List[List[Dict[str, Any]]]:
    clusters: List[List[Dict[str, Any]]] = []
    for page in pages:
        placed = False
        for cluster in clusters:
            if any(title_similarity(page["title"], other["title"]) >= threshold for other in cluster):
                cluster.append(page)
                placed = True
                break
        if not placed:
            clusters.append([page])
    return [cluster for cluster in clusters if len(cluster) > 1]


def level_label(score: int) -> str:
    if score >= 80:
        return "높음"
    if score >= 55:
        return "보통"
    return "낮음"


def content_signal(page: Dict[str, Any]) -> Tuple[int, List[str]]:
    excerpt = (page.get("body_excerpt") or "").strip()
    if not excerpt:
        return 0, ["본문 내용이 수집되지 않았습니다"]
    sentences = split_sentences(excerpt)
    score = 10 if len(sentences) >= 2 else 5
    if len(excerpt) >= 800:
        score += 10
    elif len(excerpt) >= 300:
        score += 6
    return min(20, score), [f"본문 요약 길이 {len(excerpt)}자", f"핵심 문장 {min(len(sentences), 5)}개 추출 가능"]


def split_sentences(text: str) -> List[str]:
    parts = re.split(r"(?<=[.!?।다요])\s+|\n+", text)
    cleaned = []
    for part in parts:
        chunk = re.sub(r"\s+", " ", part).strip(" -|")
        if len(chunk) >= 18:
            cleaned.append(chunk)
    return cleaned


def choose_key_sentences(text: str, limit: int = 3) -> List[str]:
    preferred: List[str] = []
    fallback: List[str] = []
    for sentence in split_sentences(text):
        if len(sentence) > 220:
            sentence = sentence[:217] + "..."
        if re.search(r"(정의|목적|절차|정책|기준|원칙|방법|요약|설명|활용|특징|구성|중요|의미)", sentence):
            preferred.append(sentence)
        else:
            fallback.append(sentence)
    chosen = preferred[:limit]
    if len(chosen) < limit:
        chosen.extend(fallback[: limit - len(chosen)])
    return chosen


def synthesize_trusted_data(scored_pages: List[Dict[str, Any]], page_lookup: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    ranked = sorted(
        scored_pages,
        key=lambda item: (item["trust_score"], item["freshness_score"], item["confidence_level"] == "high"),
        reverse=True,
    )
    for item in ranked[:5]:
        page = page_lookup.get(item["page_id"], {})
        excerpt = (page.get("body_excerpt") or "").strip()
        if not excerpt:
            continue
        points = choose_key_sentences(excerpt, limit=3)
        if not points:
            continue
        items.append(
            {
                "page_id": item["page_id"],
                "title": item["title"],
                "space_key": page.get("space_key"),
                "trust_score": item["trust_score"],
                "freshness_score": item["freshness_score"],
                "confidence_level": item["confidence_level"],
                "points": points,
            }
        )
    return items


def synthesize_overview(scored_pages: List[Dict[str, Any]], page_lookup: Dict[str, Dict[str, Any]]) -> List[str]:
    lines: List[str] = []
    ranked = sorted(
        scored_pages,
        key=lambda item: item.get("ranking_score", item["trust_score"] + item["freshness_score"]),
        reverse=True,
    )
    seen = set()
    for item in ranked:
        page = page_lookup.get(item["page_id"], {})
        excerpt = (page.get("body_excerpt") or "").strip()
        if not excerpt:
            continue
        for sentence in choose_key_sentences(excerpt, limit=2):
            key = sentence[:80]
            if key in seen:
                continue
            seen.add(key)
            lines.append(sentence)
            if len(lines) >= 6:
                return lines
    return lines


def summarize_scope(meta: Dict[str, Any], pages: List[Dict[str, Any]], warnings: List[str]) -> List[str]:
    scope = meta.get("scope", {})
    lines = [
        f"- 총 {len(pages)}개 문서를 기준으로 분석했습니다.",
        f"- 인증 방식은 `{meta.get('auth_used', 'unknown')}` 입니다.",
        f"- API 호출 제한은 초당 {meta.get('rate_limit_rps', 'unknown')}회입니다.",
    ]
    if scope.get("space_key"):
        lines.append(f"- 대상 space는 `{scope['space_key']}` 입니다.")
    if scope.get("all_spaces"):
        lines.append("- 접근 가능한 전체 space 범위를 대상으로 분석했습니다.")
    if scope.get("preferred_spaces"):
        lines.append(f"- 선호 space 확장 기준은 `{', '.join(scope['preferred_spaces'])}` 입니다.")
    if scope.get("expanded_page_ids"):
        lines.append(f"- 선호 space 확장으로 {len(scope['expanded_page_ids'])}개 문서를 추가 검토했습니다.")
    if scope.get("root_page_id"):
        lines.append(f"- 기준 루트 페이지 ID는 `{scope['root_page_id']}` 입니다.")
    if warnings:
        lines.append(f"- 수집 경고가 {len(warnings)}건 있어 일부 판단 근거가 약할 수 있습니다.")
    return lines


def build_review_lookup(review_payload: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    if not review_payload:
        return {}
    return {
        item.get("topic_id"): item
        for item in review_payload.get("reviews", [])
        if item.get("topic_id")
    }


def build_topic_insight_lines(
    insights_payload: Optional[Dict[str, Any]],
    review_payload: Optional[Dict[str, Any]],
    purpose: str = "general",
) -> List[str]:
    lines: List[str] = []
    if not insights_payload:
        return lines

    review_lookup = build_review_lookup(review_payload)
    insights = insights_payload.get("insights", [])

    if purpose == "change-tracking":
        lines.append("## 주제별 변경 동향")
    elif purpose == "onboarding":
        lines.append("## 주제별 학습 가이드")
    else:
        lines.append("## 주제별 인사이트")

    if not insights:
        lines.append("- 생성된 주제별 인사이트가 없습니다.")
        lines.append("")
        return lines

    for insight in insights[:10]:
        review = review_lookup.get(insight.get("topic_id"), {})
        analysis_method = insight.get("analysis_method") or (insights_payload.get("meta") or {}).get("analysis_method") or "evidence-first"
        lines.append(f"### {insight.get('label') or insight.get('topic_id')}")
        lines.append(f"- 분석 방식: {ANALYSIS_METHOD_LABELS.get(analysis_method, analysis_method)}")
        lines.append(f"- 결론: {insight.get('conclusion')}")
        insight_confidence = insight.get("confidence_ko") or CONFIDENCE_KO.get(insight.get("confidence", ""), "알 수 없음")
        review_confidence = review.get("adjusted_confidence_ko") or CONFIDENCE_KO.get(review.get("adjusted_confidence", ""), "알 수 없음")
        review_verdict = review.get("verdict_ko") or VERDICT_KO.get(review.get("verdict", ""), review.get("verdict", "알 수 없음"))
        lines.append(
            f"- 확신도: {insight_confidence}"
            + (
                f" -> 검토 후 {review_confidence} ({review_verdict})"
                if review
                else ""
            )
        )

        current = insight.get("current_reference") or {}
        background = insight.get("background_reference") or {}
        stale = insight.get("stale_reference") or {}

        if analysis_method == "pyramid":
            for support in (insight.get("key_supports") or [])[:3]:
                lines.append(f"- 핵심 근거: {support}")
            if insight.get("wider_significance"):
                lines.append(f"- 의미: {insight.get('wider_significance')}")
            for action in (insight.get("suggested_actions") or [])[:2]:
                lines.append(f"- 권장 후속 조치: {action}")

        elif analysis_method == "hypothesis-driven":
            if insight.get("working_hypothesis"):
                lines.append(f"- 가설: {insight.get('working_hypothesis')}")
            for point in (insight.get("validation_points") or [])[:3]:
                status = point.get("status") or "unknown"
                lines.append(f"- 검증({status}): {point.get('check')}: {point.get('result')}")
            if insight.get("hypothesis_status"):
                lines.append(f"- 가설 판정: {insight.get('hypothesis_status')}")
            if insight.get("pivot_question"):
                lines.append(f"- 추가 확인 질문: {insight.get('pivot_question')}")
            for action in (insight.get("suggested_actions") or [])[:2]:
                lines.append(f"- 다음 검증 행동: {action}")

        elif purpose == "change-tracking":
            # 변경 추적: 변경 내역 확장, 충돌 축소
            for change in (insight.get("recent_change_summary") or [])[:8]:
                lines.append(f"- 변경: {change}")
            if current:
                lines.append(f"- 가장 활발한 문서: `{current.get('title')}`")
            for action in (insight.get("suggested_actions") or [])[:3]:
                lines.append(f"- 후속 조치: {action}")

        elif purpose == "onboarding":
            # 온보딩: 읽기 순서 + 배경, 충돌 제거
            if current:
                lines.append(f"- 시작점 문서: `{current.get('title')}`")
            if background and background.get("page_id") != current.get("page_id"):
                lines.append(f"- 배경 읽기: `{background.get('title')}`")
            if stale:
                lines.append(f"- 역사적 맥락: `{stale.get('title')}`")
            for action in (insight.get("suggested_actions") or [])[:3]:
                lines.append(f"- 추천: {action}")

        else:
            # general (기존 로직)
            if current:
                lines.append(f"- 현재 작업 기준 문서: `{current.get('title')}`")
            if background and background.get("page_id") != current.get("page_id"):
                lines.append(f"- 배경 참고 문서: `{background.get('title')}`")
            if stale:
                lines.append(f"- 오래된 참고 후보: `{stale.get('title')}`")
            for note in (insight.get("conflict_notes") or [])[:2]:
                lines.append(f"- 충돌 또는 중복 신호: {note}")
            for change in (insight.get("recent_change_summary") or [])[:2]:
                lines.append(f"- 최근 의미 있는 변화: {change}")
            for action in (insight.get("suggested_actions") or [])[:2]:
                lines.append(f"- 권장 후속 조치: {action}")

        if insight.get("evidence_gaps"):
            lines.append(f"- 근거 공백: {insight['evidence_gaps'][0]}")
        if review and review.get("requires_follow_up"):
            reviewer_notes = []
            for reviewer in review.get("reviewers", []):
                if reviewer.get("severity") in {"warn", "fail"}:
                    reviewer_notes.extend(reviewer.get("findings", [])[:1])
            for note in reviewer_notes[:2]:
                lines.append(f"- 검토 메모: {note}")
        lines.append("")
    return lines


def build_markdown_general(
    meta: Dict[str, Any],
    pages: List[Dict[str, Any]],
    scored_pages: List[Dict[str, Any]],
    clusters: List[Dict[str, Any]],
    timeline: List[Dict[str, Any]],
    trusted_data: List[Dict[str, Any]],
    synthesized_overview: List[str],
    warnings: List[str],
    insights_payload: Optional[Dict[str, Any]] = None,
    review_payload: Optional[Dict[str, Any]] = None,
) -> str:
    best_current = max(scored_pages, key=lambda item: item["freshness_score"], default=None)
    best_trust = max(scored_pages, key=lambda item: item["trust_score"], default=None)
    review_pages = [item for item in scored_pages if item["status_flag"] == "needs-review"]

    lines: List[str] = ["# Confluence 문서 큐레이션", ""]
    lines.append("## 요약")
    lines.extend(summarize_scope(meta, pages, warnings))
    if meta.get("data_artifacts", {}).get("used"):
        lines.append(
            f"- 저장된 data 기준본을 함께 사용했고, 신규 {meta['data_artifacts'].get('new_page_count', 0)}개 / 갱신 {meta['data_artifacts'].get('updated_page_count', 0)}개 / 유지 {meta['data_artifacts'].get('unchanged_page_count', 0)}개를 반영했습니다."
        )
    if best_current:
        lines.append(
            f"- 현재 작업 기준으로는 **{best_current['title']}** 가 가장 최신 후보로 보입니다."
        )
    if best_trust:
        lines.append(
            f"- 신뢰도 관점에서는 **{best_trust['title']}** 가 가장 유력합니다."
        )
    if best_current and best_trust and best_current["page_id"] != best_trust["page_id"]:
        lines.append("- 최신성과 신뢰도가 서로 다른 문서에 모여 있어 함께 참고하는 편이 안전합니다.")
    if warnings:
        lines.append("- 프로필 정보 또는 API 제한 때문에 일부 문서는 확신이 낮습니다.")
    if meta.get("preferred_space_expansion", {}).get("used"):
        lines.append("- 선호 space 내부의 연관 문서를 추가 탐색해 검토 범위와 우선순위를 보강했습니다.")
    lines.append("")

    topic_lines = build_topic_insight_lines(insights_payload, review_payload, "general")
    if topic_lines:
        lines.extend(topic_lines)

    lines.append("## 정리된 핵심 내용")
    if synthesized_overview:
        for sentence in synthesized_overview:
            lines.append(f"- {sentence}")
    else:
        lines.append("- 본문 내용이 충분히 수집되지 않아 핵심 내용을 자동 정리하지 못했습니다.")
    lines.append("")

    lines.append("## 가장 신뢰할 수 있는 데이터")
    if trusted_data:
        for item in trusted_data:
            lines.append(
                f"### {item['title']} ({item.get('space_key') or 'space 미상'})"
            )
            lines.append(
                f"- 신뢰도 {item['trust_score']}, 최신성 {item['freshness_score']}, 확신도 {CONFIDENCE_KO.get(item['confidence_level'], item['confidence_level'])}"
            )
            for point in item["points"]:
                lines.append(f"- {point}")
    else:
        lines.append("- 본문 내용이 없거나 너무 짧아 신뢰 데이터 정리를 만들지 못했습니다.")
    lines.append("")

    lines.extend(build_document_table(scored_pages, "general"))

    lines.append("## 변경 흐름")
    if timeline:
        for event in timeline[:20]:
            lines.append(f"- {event['summary_ko']}")
    else:
        lines.append("- 확인 가능한 변경 흐름 정보가 충분하지 않습니다.")
    lines.append("")

    lines.append("## 검토 필요 문서")
    if review_pages:
        for item in review_pages[:10]:
            note = item.get("risk_notes", ["근거가 충분하지 않습니다"])[0]
            lines.append(f"- **{item['title']}**: {note}")
    else:
        lines.append("- 현재 기준으로 특별히 검토 필요로 분류된 문서는 많지 않습니다.")
    lines.append("")

    lines.append("## 추천 결론")
    if best_current:
        lines.append(
            f"- 현재 실무 작업 기준 문서로는 **{best_current['title']}** 를 우선 보는 것이 적절해 보입니다."
        )
    if best_trust and best_current and best_trust["page_id"] != best_current["page_id"]:
        lines.append(
            f"- 배경 기준이나 정책 맥락은 **{best_trust['title']}** 를 함께 참고하는 편이 안전합니다."
        )
    for cluster in clusters[:5]:
        titles = ", ".join(item["title"] for item in cluster["pages"])
        lines.append(f"- 유사 주제 문서군 `{titles}` 는 중복 또는 대체 관계를 추가 확인할 필요가 있습니다.")
    if warnings:
        lines.append("- 수집 제약이 있었으므로 최종 기준 문서로 단정하기 전에 한 번 더 확인하는 것이 좋습니다.")
    lines.append("")

    return "\n".join(lines)


def build_markdown_change_tracking(
    meta: Dict[str, Any],
    pages: List[Dict[str, Any]],
    scored_pages: List[Dict[str, Any]],
    clusters: List[Dict[str, Any]],
    timeline: List[Dict[str, Any]],
    trusted_data: List[Dict[str, Any]],
    synthesized_overview: List[str],
    warnings: List[str],
    insights_payload: Optional[Dict[str, Any]] = None,
    review_payload: Optional[Dict[str, Any]] = None,
) -> str:
    lines: List[str] = ["# Confluence 변경 추적 리포트", ""]

    # 1. 요약
    lines.append("## 요약")
    lines.extend(summarize_scope(meta, pages, warnings))
    total_changes = sum(len(page.get("version_events", [])) for page in pages)
    lines.append(f"- 검토 대상 문서에서 총 {total_changes}건의 버전 이벤트가 확인되었습니다.")
    if warnings:
        lines.append("- 일부 데이터는 API 제한으로 불완전할 수 있습니다.")
    lines.append("")

    # 2. 트렌드 신호
    lines.append("## 트렌드 신호")
    recently_created = [p for p in pages if days_ago(p.get("created_at")) is not None and days_ago(p.get("created_at")) <= 30]
    frequently_updated = sorted(
        scored_pages, key=lambda item: len(
            (next((p for p in pages if p["page_id"] == item["page_id"]), {}) or {}).get("version_events", [])
        ), reverse=True,
    )[:5]
    if recently_created:
        lines.append(f"- 최근 30일 내 신규 생성 문서: {len(recently_created)}건")
        for page in recently_created[:5]:
            lines.append(f"  - `{page['title']}` ({(page.get('created_at') or '날짜 미상')[:10]} 생성)")
    else:
        lines.append("- 최근 30일 내 신규 생성 문서는 없습니다.")
    if frequently_updated:
        lines.append("- 업데이트 빈도 상위 문서 (수집된 버전 이력 기준, 최대 5건까지 수집):")
        for item in frequently_updated:
            source_page = next((p for p in pages if p["page_id"] == item["page_id"]), {})
            event_count = len(source_page.get("version_events", []))
            if event_count > 0:
                capped = "5건+" if event_count >= 5 else f"{event_count}건"
                lines.append(f"  - `{item['title']}`: {capped} 버전 이벤트")
    lines.append("")

    # 3. 주제별 변경 동향 (insights)
    topic_lines = build_topic_insight_lines(insights_payload, review_payload, "change-tracking")
    if topic_lines:
        lines.extend(topic_lines)

    # 4. 변경 타임라인 (확장)
    lines.append("## 변경 타임라인")
    if timeline:
        for event in timeline[:30]:
            lines.append(f"- {event['summary_ko']}")
    else:
        lines.append("- 확인 가능한 변경 흐름 정보가 충분하지 않습니다.")
    lines.append("")

    # 5. 변경 주체 분석
    lines.append("## 변경 주체 분석")
    contributor_pages: Dict[str, List[str]] = {}
    for page in pages:
        for contributor_id in page.get("recent_contributors", [])[:3]:
            contributor_pages.setdefault(contributor_id, []).append(page["title"])
    if contributor_pages:
        sorted_contributors = sorted(contributor_pages.items(), key=lambda x: len(x[1]), reverse=True)
        for contributor_id, page_titles in sorted_contributors[:10]:
            lines.append(f"- `{contributor_id}`: {len(page_titles)}건 문서 관여 ({', '.join(page_titles[:3])})")
    else:
        lines.append("- 기여자 정보가 충분하지 않습니다.")
    lines.append("")

    # 6. 문서 현황 표 (변경 빈도 컬럼 포함)
    lines.extend(build_document_table(scored_pages, "change-tracking", pages=pages))

    # 7. 후속 확인 필요 항목
    lines.append("## 후속 확인 필요 항목")
    follow_ups: List[str] = []
    if recently_created:
        follow_ups.append("신규 생성 문서가 기존 문서와 중복되지 않는지 확인하세요.")
    if total_changes > 20:
        follow_ups.append("변경 활동이 활발하므로 주기적 모니터링을 권장합니다.")
    if warnings:
        follow_ups.append("데이터 수집 제약이 있었으므로 누락된 변경 사항이 있을 수 있습니다.")
    if not follow_ups:
        follow_ups.append("현재 기준으로 특별히 긴급한 후속 항목은 없습니다.")
    for item in follow_ups:
        lines.append(f"- {item}")
    lines.append("")

    return "\n".join(lines)


def build_markdown_onboarding(
    meta: Dict[str, Any],
    pages: List[Dict[str, Any]],
    scored_pages: List[Dict[str, Any]],
    clusters: List[Dict[str, Any]],
    timeline: List[Dict[str, Any]],
    trusted_data: List[Dict[str, Any]],
    synthesized_overview: List[str],
    warnings: List[str],
    insights_payload: Optional[Dict[str, Any]] = None,
    review_payload: Optional[Dict[str, Any]] = None,
) -> str:
    lines: List[str] = ["# Confluence 온보딩 가이드", ""]

    # 1. 주제 요약
    lines.append("## 주제 요약")
    lines.extend(summarize_scope(meta, pages, warnings))
    if synthesized_overview:
        for sentence in synthesized_overview[:5]:
            lines.append(f"- {sentence}")
    else:
        lines.append("- 본문 내용이 충분히 수집되지 않아 주제 요약을 자동 생성하지 못했습니다.")
    lines.append("")

    # 2. 추천 읽기 순서
    lines.append("## 추천 읽기 순서")
    reading_order = sorted(
        scored_pages,
        key=lambda item: (item["trust_score"] + item["freshness_score"], item["trust_score"]),
        reverse=True,
    )
    if reading_order:
        for idx, item in enumerate(reading_order[:7], start=1):
            reason_parts: List[str] = []
            if item["freshness_score"] >= 70:
                reason_parts.append("최신")
            if item["trust_score"] >= 60:
                reason_parts.append("신뢰도 높음")
            if item.get("status_flag") == "fresh-and-trusted":
                reason_parts.append("기준 문서 후보")
            reason = ", ".join(reason_parts) if reason_parts else "관련 문서"
            lines.append(f"{idx}. **{item['title']}** — {reason}")
    else:
        lines.append("- 읽기 순서를 추천할 만한 문서가 충분하지 않습니다.")
    lines.append("")

    # 3. 주제별 학습 가이드 (insights)
    topic_lines = build_topic_insight_lines(insights_payload, review_payload, "onboarding")
    if topic_lines:
        lines.extend(topic_lines)

    # 4. 핵심 내용 정리
    lines.append("## 핵심 내용 정리")
    if trusted_data:
        for item in trusted_data:
            lines.append(f"### {item['title']}")
            for point in item["points"]:
                lines.append(f"- {point}")
    elif synthesized_overview:
        for sentence in synthesized_overview:
            lines.append(f"- {sentence}")
    else:
        lines.append("- 본문 내용이 충분하지 않아 핵심 내용을 정리하지 못했습니다.")
    lines.append("")

    # 5. 배경 문맥
    lines.append("## 배경 문맥")
    stale_pages = [item for item in scored_pages if item.get("status_flag") in ("trusted-but-stale", "needs-review")]
    if stale_pages:
        lines.append("- 아래 문서들은 오래되었지만 역사적 맥락을 파악하는 데 도움이 됩니다:")
        for item in stale_pages[:5]:
            lines.append(f"  - `{item['title']}` ({item.get('updated_at', '날짜 미상')[:10]})")
    else:
        lines.append("- 별도의 배경 문맥 문서는 식별되지 않았습니다.")
    lines.append("")

    # 6. 문서 맵
    lines.append("## 문서 맵")
    if clusters:
        for cluster in clusters[:5]:
            lines.append(f"### {cluster['label']}")
            for page in cluster["pages"]:
                lines.append(f"- `{page['title']}`")
    else:
        lines.append("- 문서 간 그룹 관계가 충분히 식별되지 않았습니다.")
    lines.append("")

    # 7. 추가 탐색 제안
    lines.append("## 추가 탐색 제안")
    space_keys = sorted({page.get("space_key") for page in pages if page.get("space_key")})
    labels = sorted({label for page in pages for label in page.get("labels", [])})
    if space_keys:
        lines.append(f"- 관련 Space: {', '.join(space_keys[:5])}")
    if labels:
        lines.append(f"- 관련 Label: {', '.join(labels[:10])}")
    if not space_keys and not labels:
        lines.append("- 추가 탐색을 위한 Space 또는 Label 정보가 충분하지 않습니다.")
    lines.append("")

    return "\n".join(lines)


def build_document_table(
    scored_pages: List[Dict[str, Any]],
    purpose: str = "general",
    pages: Optional[List[Dict[str, Any]]] = None,
) -> List[str]:
    lines: List[str] = []
    if purpose == "change-tracking":
        lines.append("## 문서 현황")
        lines.append("| 문서명 | 최근 수정일 | 주요 작성자/수정자 | 최신성 | 변경 빈도 | 탐색 경로 | 판단 근거 |")
        lines.append("|---|---|---|---|---|---|---|")
        page_lookup = {p["page_id"]: p for p in (pages or [])}
        for item in scored_pages:
            updated_at = item.get("updated_at") or "-"
            authors = ", ".join(item.get("recent_contributors", [])[:2]) or "정보 부족"
            evidence = "; ".join(item.get("evidence", [])[:2]) or "근거 부족"
            discovery = "; ".join(item.get("discovery_reasons", [])[:2]) or "키워드 검색"
            source_page = page_lookup.get(item["page_id"], {})
            event_count = len(source_page.get("version_events", []))
            freq_label = ("5건+" if event_count >= 5 else f"{event_count}건") if event_count > 0 else "이력 없음"
            lines.append(
                f"| {item['title']} | {updated_at} | {authors} | {level_label(item['freshness_score'])} | {freq_label} | {discovery} | {evidence} |"
            )
    else:
        lines.append("## 문서 현황")
        lines.append("| 문서명 | 최근 수정일 | 주요 작성자/수정자 | 추정 팀/직책 | 최신성 | 신뢰도 | 상태 | 탐색 경로 | 판단 근거 |")
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for item in scored_pages:
            team_title = item.get("people_summary") or "정보 부족"
            updated_at = item.get("updated_at") or "-"
            evidence = "; ".join(item.get("evidence", [])[:2]) or "근거 부족"
            authors = ", ".join(item.get("recent_contributors", [])[:2]) or "정보 부족"
            discovery = "; ".join(item.get("discovery_reasons", [])[:2]) or "키워드 검색"
            lines.append(
                f"| {item['title']} | {updated_at} | {authors} | {team_title} | {level_label(item['freshness_score'])} | {level_label(item['trust_score'])} | {STATUS_KO[item['status_flag']]} | {discovery} | {evidence} |"
            )
    lines.append("")
    return lines


def build_markdown(
    meta: Dict[str, Any],
    pages: List[Dict[str, Any]],
    scored_pages: List[Dict[str, Any]],
    clusters: List[Dict[str, Any]],
    timeline: List[Dict[str, Any]],
    trusted_data: List[Dict[str, Any]],
    synthesized_overview: List[str],
    warnings: List[str],
    insights_payload: Optional[Dict[str, Any]] = None,
    review_payload: Optional[Dict[str, Any]] = None,
    purpose: str = "general",
) -> str:
    builder_args = (
        meta, pages, scored_pages, clusters, timeline,
        trusted_data, synthesized_overview, warnings,
        insights_payload, review_payload,
    )
    if purpose == "change-tracking":
        return build_markdown_change_tracking(*builder_args)
    if purpose == "onboarding":
        return build_markdown_onboarding(*builder_args)
    return build_markdown_general(*builder_args)


def main() -> int:
    args = parse_args()
    with open(args.input, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    expansion_payload = read_json(args.expansion_input)
    payload = merge_expansion_payload(payload, expansion_payload)
    insights_payload = read_json(args.insights_input)
    review_payload = read_json(args.review_input)

    meta = payload.get("meta", {})
    pages = payload.get("pages", [])
    warnings = payload.get("warnings", [])
    relationships = payload.get("relationships", [])
    people_by_id = {person["account_id"]: person for person in payload.get("people", []) if person}
    page_lookup = {page["page_id"]: page for page in pages}

    scored_pages: List[Dict[str, Any]] = []
    for page in pages:
        freshness_base, freshness_evidence = score_freshness(
            page, args.recent_days_strong, args.recent_days_medium
        )
        change_score, change_evidence = score_change_signal(page)
        freshness_score = min(100, freshness_base + change_score)
        people_score, people_evidence, missing_people = score_people(page, people_by_id)
        relationship_score, relationship_evidence, duplicate, superseded = score_relationships(
            page, relationships, page_lookup
        )
        content_score, content_evidence = content_signal(page)
        trust_score = min(100, round(people_score + relationship_score + content_score + min(20, freshness_score * 0.2)))
        confidence = compute_confidence(freshness_score, trust_score, missing_people, duplicate, warnings)
        status_flag = determine_status(freshness_score, trust_score, confidence, duplicate, superseded)
        recent_people_summary = []
        for account_id in page.get("recent_contributors", [])[:3]:
            person = people_by_id.get(account_id)
            if not person:
                continue
            hint = person.get("org_hint", {})
            bits = [hint.get("team"), hint.get("title")]
            summary = " / ".join([bit for bit in bits if bit])
            if summary:
                recent_people_summary.append(summary)
        evidence = freshness_evidence + change_evidence + relationship_evidence + content_evidence
        if people_evidence:
            evidence.append("주요 기여자: " + "; ".join(people_evidence[:2]))
        risk_notes = []
        if missing_people:
            risk_notes.append("작성자 또는 수정자 프로필 정보가 부족해 신뢰도 확신이 낮습니다.")
        if duplicate:
            risk_notes.append("유사 문서가 있어 기준 문서 여부를 추가 확인할 필요가 있습니다.")
        if superseded:
            risk_notes.append("더 최근에 갱신된 유사 문서가 있어 대체되었을 가능성이 있습니다.")
        if not risk_notes:
            risk_notes.append("현재 기준으로는 큰 충돌 신호가 많지 않습니다.")
        preferred_space_boost = int(page.get("preferred_space_boost", 0) or 0)
        ranking_score = trust_score + freshness_score + preferred_space_boost
        if page.get("preferred_space_match"):
            evidence.append(f"선호 space 우대 +{preferred_space_boost}")
        if page.get("discovery_source") == "preferred_space_expansion":
            evidence.append("선호 space 연관 탐색으로 포함")
        scored_pages.append(
            {
                "page_id": page["page_id"],
                "title": page["title"],
                "updated_at": page.get("updated_at"),
                "recent_contributors": page.get("recent_contributors", []),
                "people_summary": ", ".join(recent_people_summary) if recent_people_summary else "정보 부족",
                "freshness_score": freshness_score,
                "change_score": change_score,
                "trust_score": trust_score,
                "ranking_score": ranking_score,
                "confidence_level": confidence,
                "status_flag": status_flag,
                "evidence": evidence[:5],
                "risk_notes": risk_notes,
                "discovery_source": page.get("discovery_source", "query_seed"),
                "discovery_reasons": page.get("discovery_reasons", []),
                "preferred_space_match": bool(page.get("preferred_space_match")),
                "preferred_space_boost": preferred_space_boost,
                "topic_update_boost": 0,
            }
        )

    cluster_groups = cluster_pages(pages, args.title_similarity_threshold)
    scored_page_lookup = {item["page_id"]: item for item in scored_pages}
    for cluster in cluster_groups:
        changed_candidates = []
        for page in cluster:
            item = scored_page_lookup.get(page.get("page_id"))
            if not item:
                continue
            if item.get("change_score", 0) <= 0:
                continue
            updated_days = days_ago(page.get("updated_at"))
            changed_candidates.append(
                (
                    item["change_score"],
                    -(999999 if updated_days is None else updated_days),
                    item["page_id"],
                )
            )
        changed_candidates.sort(reverse=True)
        for index, _candidate in enumerate(changed_candidates):
            page_id = _candidate[2]
            item = scored_page_lookup[page_id]
            boost = 8 if index == 0 else 4
            item["topic_update_boost"] += boost
            item["ranking_score"] += boost
            item["evidence"].append(f"동일 주제 최신 변경 가중치 +{boost}")

    scored_pages.sort(key=lambda item: (item["ranking_score"], item["trust_score"], item["freshness_score"]), reverse=True)
    scored_pages = scored_pages[: args.top_n]

    clusters = []
    for idx, cluster in enumerate(cluster_groups, start=1):
        ordered = sorted(cluster, key=lambda item: days_ago(item.get("updated_at")) or 999999)
        clusters.append(
            {
                "cluster_id": f"topic_{idx}",
                "label": ordered[0]["title"],
                "page_ids": [item["page_id"] for item in ordered],
                "likely_current_page_id": ordered[0]["page_id"],
                "likely_background_page_id": ordered[-1]["page_id"],
                "confidence": "medium",
                "pages": ordered,
            }
        )

    timeline = []
    for page in sorted(pages, key=lambda item: parse_datetime(item.get("updated_at")) or datetime.min.replace(tzinfo=timezone.utc), reverse=True):
        change = page.get("change_summary") or {}
        if change.get("changed"):
            timeline.append(
                {
                    "at": page.get("updated_at"),
                    "page_id": page["page_id"],
                    "event_type": "stored_reference_diff",
                    "summary_ko": change.get("summary_ko"),
                }
            )
        summary = f"{(page.get('updated_at') or '날짜 미상')[:10]}: {page['title']} 문서가 갱신되었습니다."
        timeline.append({"at": page.get("updated_at"), "page_id": page["page_id"], "event_type": "updated", "summary_ko": summary})
        for event in page.get("version_events", [])[:3]:
            if event.get("updated_at"):
                timeline.append(
                    {
                        "at": event.get("updated_at"),
                        "page_id": page["page_id"],
                        "event_type": "version",
                        "summary_ko": f"{event.get('updated_at')[:10]}: {page['title']} 버전 {event.get('version')} 이 기록되었습니다.",
                    }
                )
    timeline.sort(key=lambda item: item.get("at") or "", reverse=True)

    trusted_data = synthesize_trusted_data(scored_pages, page_lookup)
    synthesized_overview = synthesize_overview(scored_pages, page_lookup)

    markdown = build_markdown(
        meta,
        pages,
        scored_pages,
        clusters,
        timeline,
        trusted_data,
        synthesized_overview,
        warnings,
        insights_payload,
        review_payload,
        purpose=args.purpose,
    )
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as handle:
        handle.write(markdown)

    if args.emit_json_summary:
        analysis_method = (
            ((insights_payload or {}).get("meta") or {}).get("analysis_method")
            or args.analysis_method
        )
        summary_payload = {
            "purpose": args.purpose,
            "analysis_method": analysis_method,
            "summary": {
                "best_current_candidate_page_id": max(scored_pages, key=lambda item: item["freshness_score"], default={}).get("page_id"),
                "best_trust_candidate_page_id": max(scored_pages, key=lambda item: item["trust_score"], default={}).get("page_id"),
                "best_ranked_candidate_page_id": max(scored_pages, key=lambda item: item["ranking_score"], default={}).get("page_id"),
                "needs_review_count": len([item for item in scored_pages if item["status_flag"] == "needs-review"]),
            },
            "scored_pages": scored_pages,
            "topic_clusters": [
                {
                    "cluster_id": cluster["cluster_id"],
                    "label": cluster["label"],
                    "page_ids": cluster["page_ids"],
                    "likely_current_page_id": cluster["likely_current_page_id"],
                    "likely_background_page_id": cluster["likely_background_page_id"],
                    "confidence": cluster["confidence"],
                }
                for cluster in clusters
            ],
            "trusted_data": trusted_data,
            "insights_summary": (insights_payload or {}).get("summary"),
            "review_summary": (review_payload or {}).get("summary"),
            "timeline": timeline[:50],
            "warnings": warnings,
        }
        with open(args.emit_json_summary, "w", encoding="utf-8") as handle:
            json.dump(summary_payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")

    feature_paths = persist_feature_state(
        args.data_dir,
        "curation-scoring",
        {
            "meta": {
                "generated_at": meta.get("fetched_at") or datetime.now(timezone.utc).astimezone().isoformat(),
                "input_path": os.path.abspath(args.input),
                "output_path": os.path.abspath(args.output),
                "summary_path": os.path.abspath(args.emit_json_summary) if args.emit_json_summary else None,
            },
            "weights": {
                "people_signal_weight": args.people_signal_weight,
                "freshness_weight": args.freshness_weight,
                "relationship_weight": args.relationship_weight,
                "recent_days_strong": args.recent_days_strong,
                "recent_days_medium": args.recent_days_medium,
                "title_similarity_threshold": args.title_similarity_threshold,
                "preferred_space_boost_default": 8,
                "topic_update_boost_primary": 8,
                "topic_update_boost_secondary": 4,
            },
            "applied_features": {
                "preferred_space_expansion_used": bool(meta.get("preferred_space_expansion", {}).get("used")),
                "data_artifacts_used": bool(meta.get("data_artifacts", {}).get("used")),
                "top_preferred_space_pages": [
                    {
                        "page_id": item.get("page_id"),
                        "preferred_space_boost": item.get("preferred_space_boost", 0),
                    }
                    for item in scored_pages
                    if item.get("preferred_space_boost", 0) > 0
                ][:10],
                "top_topic_update_pages": [
                    {
                        "page_id": item.get("page_id"),
                        "topic_update_boost": item.get("topic_update_boost", 0),
                    }
                    for item in scored_pages
                    if item.get("topic_update_boost", 0) > 0
                ][:10],
            },
        },
    )

    if args.emit_json_summary:
        with open(args.emit_json_summary, "r", encoding="utf-8") as handle:
            summary_payload = json.load(handle)
        summary_payload.setdefault("meta", {})
        summary_payload["meta"]["data_artifacts"] = {
            "feature_latest_path": feature_paths["latest_path"],
            "feature_history_path": feature_paths["history_path"],
        }
        with open(args.emit_json_summary, "w", encoding="utf-8") as handle:
            json.dump(summary_payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
