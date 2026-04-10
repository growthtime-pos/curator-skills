#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List


CONFIDENCE_KO = {"high": "높음", "medium": "보통", "low": "낮음"}
VERDICT_KO = {"approved": "승인", "review": "추가 검토", "revise": "수정 필요"}
SEVERITY_KO = {"pass": "통과", "warn": "주의", "fail": "실패"}
REVIEWER_KO = {
    "freshness": "최신성 검토",
    "trust": "신뢰도 검토",
    "contradiction": "충돌 검토",
    "executive": "실행 관점 검토",
}
VALIDATION_STRATEGIES = {
    "balanced-validator",
    "strict-validator",
    "freshness-validator",
    "executive-validator",
}


def iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run second-pass review over synthesized Confluence insights.")
    parser.add_argument("--input", required=True, help="insights.json from synthesize_insights.py")
    parser.add_argument("--output", required=True)
    parser.add_argument("--purpose", default="general", choices=["general", "change-tracking", "onboarding"])
    parser.add_argument("--strategy", default="balanced-validator", choices=sorted(VALIDATION_STRATEGIES))
    return parser.parse_args()


def read_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def confidence_rank(level: str) -> int:
    return {"high": 3, "medium": 2, "low": 1}.get(level, 0)


def reasoning_method_from_insight(insight: Dict[str, Any]) -> str:
    method = insight.get("reasoning_method")
    if method:
        return method
    strategy = insight.get("strategy")
    if strategy == "pyramid-synthesis":
        return "pyramid"
    if strategy == "hypothesis-driven-synthesis":
        return "hypothesis-driven"
    return "evidence-first"


def freshness_review(insight: Dict[str, Any]) -> Dict[str, Any]:
    findings: List[str] = []
    severity = "pass"
    current = insight.get("current_reference") or {}
    stale = insight.get("stale_reference") or {}

    current_days = current.get("updated_days_ago")
    stale_days = stale.get("updated_days_ago")

    if current_days is None:
        findings.append("현재 기준 문서에 최신성 신호가 없습니다.")
        severity = "warn"
    elif current_days > 90:
        findings.append("현재 기준 문서가 작업 기준 문서치고는 오래되어 보입니다.")
        severity = "warn"

    if stale and stale_days is not None and current_days is not None and stale_days < current_days:
        findings.append("오래된 문서로 분류된 페이지가 현재 기준 문서보다 더 최신으로 보입니다.")
        severity = "fail"

    if not findings:
        findings.append("최신성 신호는 전반적으로 일관됩니다.")

    return {
        "reviewer": "freshness",
        "reviewer_ko": REVIEWER_KO["freshness"],
        "severity": severity,
        "severity_ko": SEVERITY_KO[severity],
        "findings": findings,
    }


def trust_review(insight: Dict[str, Any]) -> Dict[str, Any]:
    findings: List[str] = []
    severity = "pass"
    current = insight.get("current_reference") or {}
    background = insight.get("background_reference") or {}

    current_trust = current.get("trust_score")
    background_trust = background.get("trust_score")

    if current and current_trust is None:
        findings.append("현재 기준 문서에 신뢰도 점수가 없습니다.")
        severity = "warn"
    if background and background_trust is None:
        findings.append("배경 참고 문서에 신뢰도 점수가 없습니다.")
        severity = "warn"
    if current and background and current.get("page_id") != background.get("page_id"):
        if current_trust is not None and background_trust is not None and background_trust > current_trust + 10:
            findings.append("배경 참고 문서가 현재 기준 문서보다 의미 있게 더 신뢰됩니다.")
            severity = "warn"

    if not insight.get("evidence_page_ids"):
        findings.append("이 인사이트에는 근거 페이지가 인용되지 않았습니다.")
        severity = "fail"

    if not findings:
        findings.append("신뢰 신호가 존재하고 인용된 페이지와 연결되어 있습니다.")

    return {
        "reviewer": "trust",
        "reviewer_ko": REVIEWER_KO["trust"],
        "severity": severity,
        "severity_ko": SEVERITY_KO[severity],
        "findings": findings,
    }


def contradiction_review(insight: Dict[str, Any], reasoning_method: str) -> Dict[str, Any]:
    findings: List[str] = []
    severity = "pass"
    conflicts = insight.get("conflict_notes", [])

    if conflicts:
        findings.extend(conflicts[:3])
        severity = "warn"
    if insight.get("current_reference") and insight.get("background_reference"):
        current = insight["current_reference"]
        background = insight["background_reference"]
        if current.get("page_id") != background.get("page_id") and not conflicts:
            findings.append("현재 기준 문서와 배경 참고 문서가 다르지만 충돌 메모가 명시되지 않았습니다.")
            severity = "warn"
    if reasoning_method == "hypothesis-driven" and insight.get("hypothesis_status") == "supported" and conflicts:
        findings.append("반증 또는 충돌 근거가 있는데 가설 상태가 supported 로 유지되어 있습니다.")
        severity = "fail"

    if not findings:
        findings.append("해결되지 않은 충돌 신호는 뚜렷하지 않습니다.")

    return {
        "reviewer": "contradiction",
        "reviewer_ko": REVIEWER_KO["contradiction"],
        "severity": severity,
        "severity_ko": SEVERITY_KO[severity],
        "findings": findings,
    }


def executive_review(insight: Dict[str, Any], reasoning_method: str) -> Dict[str, Any]:
    findings: List[str] = []
    severity = "pass"

    if not insight.get("suggested_actions"):
        findings.append("인사이트에 실행 가능한 다음 조치가 없습니다.")
        severity = "warn"
    if not insight.get("evidence_gaps") and confidence_rank(insight.get("confidence", "low")) <= 1:
        findings.append("낮은 확신도의 인사이트인데 근거 공백 설명이 없습니다.")
        severity = "warn"
    if not insight.get("conclusion"):
        findings.append("인사이트에 명시적인 결론이 없습니다.")
        severity = "fail"

    if reasoning_method == "pyramid":
        key_supports = insight.get("key_supports", [])
        if not insight.get("executive_answer"):
            findings.append("피라미드 방식인데 답을 먼저 제시하는 executive_answer 가 없습니다.")
            severity = "fail"
        if len(key_supports) > 3:
            findings.append("피라미드 방식의 핵심 근거가 4개 이상으로 과도합니다.")
            severity = "fail"
        if len(key_supports) != len(set(key_supports)):
            findings.append("피라미드 방식의 핵심 근거가 중복됩니다.")
            severity = "fail"
        wider_significance = insight.get("wider_significance")
        if not wider_significance:
            findings.append("피라미드 방식인데 wider_significance 가 없습니다.")
            severity = "fail"
        elif wider_significance == insight.get("executive_answer"):
            findings.append("wider_significance 가 결론의 재서술에 머물러 있습니다.")
            severity = "warn"
    elif reasoning_method == "hypothesis-driven":
        if not insight.get("working_hypothesis"):
            findings.append("가설 기반 방식인데 working_hypothesis 가 없습니다.")
            severity = "fail"
        if not insight.get("validation_points"):
            findings.append("가설 기반 방식인데 validation_points 가 없습니다.")
            severity = "fail"
        if not insight.get("hypothesis_status"):
            findings.append("가설 기반 방식인데 hypothesis_status 가 없습니다.")
            severity = "fail"

    if not findings:
        findings.append("인사이트가 간결하고 실행 지향적으로 정리되어 있습니다.")

    return {
        "reviewer": "executive",
        "reviewer_ko": REVIEWER_KO["executive"],
        "severity": severity,
        "severity_ko": SEVERITY_KO[severity],
        "findings": findings,
    }


def combine_reviews(reviews: List[Dict[str, Any]]) -> str:
    severities = [review.get("severity") for review in reviews]
    if "fail" in severities:
        return "revise"
    if "warn" in severities:
        return "review"
    return "approved"


def adjust_confidence(original: str, reviews: List[Dict[str, Any]], strategy: str) -> str:
    score = confidence_rank(original)
    warn_count = 0
    fail_count = 0
    for review in reviews:
        if review.get("severity") == "fail":
            fail_count += 1
        elif review.get("severity") == "warn":
            warn_count += 1

    score -= min(fail_count, 1 if strategy == "balanced-validator" else 2)
    warn_threshold = 2
    if strategy == "strict-validator":
        warn_threshold = 1
    elif strategy in {"freshness-validator", "executive-validator"}:
        warn_threshold = 2
    if warn_count >= warn_threshold:
        score -= 1
    if fail_count >= 2:
        score -= 1

    if score >= 3:
        return "high"
    if score >= 2:
        return "medium"
    return "low"


def review_topic(
    insight: Dict[str, Any],
    purpose: str = "general",
    strategy: str = "balanced-validator",
) -> Dict[str, Any]:
    reasoning_method = reasoning_method_from_insight(insight)
    reviews = [
        freshness_review(insight),
        trust_review(insight),
        contradiction_review(insight, reasoning_method),
        executive_review(insight, reasoning_method),
    ]

    if strategy == "strict-validator":
        reviews.extend(
            [
                freshness_review(insight),
                contradiction_review(insight, reasoning_method),
                executive_review(insight, reasoning_method),
            ]
        )
    elif strategy == "freshness-validator":
        reviews.append(freshness_review(insight))
    elif strategy == "executive-validator":
        reviews.append(executive_review(insight, reasoning_method))
    elif purpose == "change-tracking":
        reviews.append(freshness_review(insight))
    elif purpose == "onboarding":
        reviews.append(executive_review(insight, reasoning_method))

    verdict = combine_reviews(reviews)
    adjusted_confidence = adjust_confidence(insight.get("confidence", "low"), reviews, strategy)
    requires_follow_up = verdict != "approved"

    return {
        "topic_id": insight.get("topic_id"),
        "label": insight.get("label"),
        "strategy": strategy,
        "reasoning_method": reasoning_method,
        "original_confidence": insight.get("confidence"),
        "original_confidence_ko": CONFIDENCE_KO.get(insight.get("confidence"), "알 수 없음"),
        "adjusted_confidence": adjusted_confidence,
        "adjusted_confidence_ko": CONFIDENCE_KO.get(adjusted_confidence, "알 수 없음"),
        "verdict": verdict,
        "verdict_ko": VERDICT_KO[verdict],
        "requires_follow_up": requires_follow_up,
        "reviewers": reviews,
        "recommended_actions": insight.get("suggested_actions", []),
    }


def summarize_reviews(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "topic_count": len(results),
        "approved_count": len([item for item in results if item.get("verdict") == "approved"]),
        "review_count": len([item for item in results if item.get("verdict") == "review"]),
        "revise_count": len([item for item in results if item.get("verdict") == "revise"]),
        "follow_up_count": len([item for item in results if item.get("requires_follow_up")]),
    }


def main() -> int:
    args = parse_args()
    payload = read_json(args.input)
    insights = payload.get("insights", [])

    reviewed = [review_topic(insight, args.purpose, args.strategy) for insight in insights]
    reviewed.sort(
        key=lambda item: (
            item.get("verdict") == "approved",
            confidence_rank(item.get("adjusted_confidence", "low")),
            item.get("label") or "",
        )
    )

    result = {
        "meta": {
            "generated_at": iso_now(),
            "source_type": "review_insights",
            "purpose": args.purpose,
            "strategy": args.strategy,
            "input": args.input,
            "topic_count": len(reviewed),
        },
        "summary": summarize_reviews(reviewed),
        "reviews": reviewed,
        "warnings": payload.get("warnings", []),
    }

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
