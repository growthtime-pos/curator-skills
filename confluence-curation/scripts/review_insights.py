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
        findings.append("Current reference has no recency signal.")
        severity = "warn"
    elif current_days > 90:
        findings.append("Current reference looks old for a working document.")
        severity = "warn"

    if stale and stale_days is not None and current_days is not None and stale_days < current_days:
        findings.append("A stale-designated page appears newer than the current reference.")
        severity = "fail"

    if not findings:
        findings.append("Freshness signals are directionally consistent.")

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
        findings.append("Current reference has no trust score.")
        severity = "warn"
    if background and background_trust is None:
        findings.append("Background reference has no trust score.")
        severity = "warn"
    if current and background and current.get("page_id") != background.get("page_id"):
        if current_trust is not None and background_trust is not None and background_trust > current_trust + 10:
            findings.append("Background reference is materially more trusted than the current reference.")
            severity = "warn"

    if not insight.get("evidence_page_ids"):
        findings.append("No evidence pages are cited for this insight.")
        severity = "fail"

    if not findings:
        findings.append("Trust signals are present and tied to cited pages.")

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
            findings.append("Current and background references differ but no explicit conflict note is present.")
            severity = "warn"

    if not findings:
        findings.append("No unresolved contradiction signals were detected.")

    return {
        "reviewer": "contradiction",
        "severity": severity,
        "findings": findings,
    }


def executive_review(insight: Dict[str, Any]) -> Dict[str, Any]:
    findings: List[str] = []
    severity = "pass"

    if not insight.get("suggested_actions"):
        findings.append("Insight does not include actionable next steps.")
        severity = "warn"
    if not insight.get("evidence_gaps") and confidence_rank(insight.get("confidence", "low")) <= 1:
        findings.append("Low-confidence insight does not explain its evidence gaps.")
        severity = "warn"
    if not insight.get("conclusion"):
        findings.append("Insight has no explicit conclusion.")
        severity = "fail"

    if not findings:
        findings.append("Insight is concise and action-oriented.")

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
    for review in reviews:
        if review.get("severity") == "fail":
            score -= 2
        elif review.get("severity") == "warn":
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
