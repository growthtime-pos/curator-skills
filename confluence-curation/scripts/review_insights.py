#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run second-pass review over synthesized Confluence insights.")
    parser.add_argument("--input", required=True, help="insights.json from synthesize_insights.py")
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def read_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def confidence_rank(level: str) -> int:
    return {"high": 3, "medium": 2, "low": 1}.get(level, 0)


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
        "severity": severity,
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
        "severity": severity,
        "findings": findings,
    }


def contradiction_review(insight: Dict[str, Any]) -> Dict[str, Any]:
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

    if not findings:
        findings.append("해결되지 않은 충돌 신호는 뚜렷하지 않습니다.")

    return {
        "reviewer": "contradiction",
        "severity": severity,
        "findings": findings,
    }


def executive_review(insight: Dict[str, Any]) -> Dict[str, Any]:
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

    if not findings:
        findings.append("인사이트가 간결하고 실행 지향적으로 정리되어 있습니다.")

    return {
        "reviewer": "executive",
        "severity": severity,
        "findings": findings,
    }


def combine_reviews(reviews: List[Dict[str, Any]]) -> str:
    severities = [review.get("severity") for review in reviews]
    if "fail" in severities:
        return "revise"
    if "warn" in severities:
        return "review"
    return "approved"


def adjust_confidence(original: str, reviews: List[Dict[str, Any]]) -> str:
    score = confidence_rank(original)
    warn_count = 0
    fail_count = 0
    for review in reviews:
        if review.get("severity") == "fail":
            fail_count += 1
        elif review.get("severity") == "warn":
            warn_count += 1

    score -= min(fail_count, 1)
    if warn_count >= 2:
        score -= 1
    if fail_count >= 2:
        score -= 1

    if score >= 3:
        return "high"
    if score >= 2:
        return "medium"
    return "low"


def review_topic(insight: Dict[str, Any]) -> Dict[str, Any]:
    reviews = [
        freshness_review(insight),
        trust_review(insight),
        contradiction_review(insight),
        executive_review(insight),
    ]
    verdict = combine_reviews(reviews)
    adjusted_confidence = adjust_confidence(insight.get("confidence", "low"), reviews)
    requires_follow_up = verdict != "approved"

    return {
        "topic_id": insight.get("topic_id"),
        "label": insight.get("label"),
        "original_confidence": insight.get("confidence"),
        "adjusted_confidence": adjusted_confidence,
        "verdict": verdict,
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

    reviewed = [review_topic(insight) for insight in insights]
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
