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
    parser = argparse.ArgumentParser(description="브리핑형 Confluence 인사이트 요약을 생성합니다.")
    parser.add_argument("--fetch-input", required=True)
    parser.add_argument("--insights-input", required=True)
    parser.add_argument("--review-input", required=True)
    parser.add_argument("--summary-input", help="curate_confluence.py 의 JSON summary")
    parser.add_argument("--preferred-space-inference-input")
    parser.add_argument("--output", required=True)
    parser.add_argument("--markdown-output")
    return parser.parse_args()


def read_json(path: Optional[str]) -> Optional[Dict[str, Any]]:
    if not path:
        return None
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: str, payload: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def days_ago(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0, (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).days)


def build_recent_updates(fetch_payload: Dict[str, Any]) -> List[str]:
    pages = fetch_payload.get("pages", [])
    changed = []
    for page in pages:
        change = page.get("change_summary") or {}
        if change.get("changed"):
            changed.append(
                {
                    "title": page.get("title"),
                    "updated_at": page.get("updated_at"),
                    "summary": change.get("summary_ko") or f"{page.get('title')} 문서에 변경이 있었습니다.",
                }
            )
    changed.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
    return [item["summary"] for item in changed[:5]]


def build_attention_topics(insights_payload: Dict[str, Any], review_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    review_lookup = {
        item.get("topic_id"): item
        for item in review_payload.get("reviews", [])
        if item.get("topic_id")
    }
    topics = []
    for insight in insights_payload.get("insights", [])[:6]:
        review = review_lookup.get(insight.get("topic_id"), {})
        topics.append(
            {
                "topic_id": insight.get("topic_id"),
                "label": insight.get("label"),
                "why_now": (
                    (insight.get("recent_change_summary") or [None])[0]
                    or (insight.get("conflict_notes") or [None])[0]
                    or "최근 관련 판단 근거가 축적된 주제입니다."
                ),
                "confidence": review.get("adjusted_confidence_ko") or insight.get("confidence_ko"),
                "recommended_action": (insight.get("suggested_actions") or [None])[0],
            }
        )
    return topics


def build_reading_order(summary_payload: Optional[Dict[str, Any]], insights_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    ordered: List[Dict[str, Any]] = []
    scored_pages = (summary_payload or {}).get("scored_pages", [])
    for item in scored_pages[:5]:
        ordered.append(
            {
                "page_id": item.get("page_id"),
                "title": item.get("title"),
                "why": (item.get("evidence") or ["우선순위 상위 문서입니다."])[0],
                "status": item.get("status_flag"),
            }
        )
    if ordered:
        return ordered

    for insight in insights_payload.get("insights", [])[:5]:
        current = insight.get("current_reference") or {}
        if not current:
            continue
        ordered.append(
            {
                "page_id": current.get("page_id"),
                "title": current.get("title"),
                "why": insight.get("conclusion"),
                "status": "topic-current",
            }
        )
    return ordered


def build_conflicts(insights_payload: Dict[str, Any]) -> List[str]:
    conflicts: List[str] = []
    for insight in insights_payload.get("insights", []):
        for note in insight.get("conflict_notes", [])[:2]:
            if note not in conflicts:
                conflicts.append(note)
    return conflicts[:6]


def build_unclear_concepts(insights_payload: Dict[str, Any], review_payload: Dict[str, Any]) -> List[str]:
    items: List[str] = []
    for insight in insights_payload.get("insights", []):
        for gap in insight.get("evidence_gaps", [])[:2]:
            if gap not in items:
                items.append(gap)
    for review in review_payload.get("reviews", []):
        for reviewer in review.get("reviewers", []):
            if reviewer.get("severity") in {"warn", "fail"}:
                for finding in reviewer.get("findings", [])[:1]:
                    if finding not in items:
                        items.append(finding)
    return items[:6]


def build_recommended_actions(insights_payload: Dict[str, Any]) -> List[str]:
    actions: List[str] = []
    for insight in insights_payload.get("insights", []):
        for action in insight.get("suggested_actions", [])[:2]:
            if action not in actions:
                actions.append(action)
    return actions[:6]


def render_markdown(brief: Dict[str, Any]) -> str:
    lines = ["# Confluence 인사이트 브리핑", ""]
    lines.append("## 지금 최근 관련 내용")
    for item in brief.get("summary", []):
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## 지금 주목해야 할 주제")
    for topic in brief.get("attention_topics", []):
        line = f"- **{topic.get('label')}**: {topic.get('why_now')}"
        if topic.get("recommended_action"):
            line += f" 다음 행동: {topic.get('recommended_action')}"
        lines.append(line)
    lines.append("")
    lines.append("## 우선 읽을 문서")
    for item in brief.get("reading_order", []):
        lines.append(f"- **{item.get('title')}**: {item.get('why')}")
    lines.append("")
    lines.append("## 최근 변경 흐름")
    for item in brief.get("change_flow", []):
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## 이해가 어려운 개념 또는 애매한 정리")
    for item in brief.get("unclear_concepts", []):
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## 바로 할 수 있는 다음 행동")
    for item in brief.get("recommended_actions", []):
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    fetch_payload = read_json(args.fetch_input) or {}
    insights_payload = read_json(args.insights_input) or {}
    review_payload = read_json(args.review_input) or {}
    summary_payload = read_json(args.summary_input)
    preferred_payload = read_json(args.preferred_space_inference_input)

    brief = {
        "meta": {
            "generated_at": iso_now(),
            "source_type": "render_insight_brief",
            "fetch_input": os.path.abspath(args.fetch_input),
            "insights_input": os.path.abspath(args.insights_input),
            "review_input": os.path.abspath(args.review_input),
            "summary_input": os.path.abspath(args.summary_input) if args.summary_input else None,
            "preferred_space_inference_input": (
                os.path.abspath(args.preferred_space_inference_input)
                if args.preferred_space_inference_input
                else None
            ),
        },
        "summary": [],
        "attention_topics": build_attention_topics(insights_payload, review_payload),
        "reading_order": build_reading_order(summary_payload, insights_payload),
        "conflicts": build_conflicts(insights_payload),
        "change_flow": build_recent_updates(fetch_payload),
        "unclear_concepts": build_unclear_concepts(insights_payload, review_payload),
        "recommended_actions": build_recommended_actions(insights_payload),
    }

    if preferred_payload and preferred_payload.get("preferred_spaces"):
        brief["summary"].append(
            "초기 검색 결과를 바탕으로 내부적으로 신뢰할 만한 space 를 추론해 확장 탐색했습니다: "
            + ", ".join(preferred_payload["preferred_spaces"])
        )
    data_artifacts = (fetch_payload.get("meta") or {}).get("data_artifacts", {})
    if data_artifacts.get("used"):
        brief["summary"].append(
            "저장된 기준본과 비교해 신규 "
            f"{data_artifacts.get('new_page_count', 0)}개 / 갱신 {data_artifacts.get('updated_page_count', 0)}개 / 유지 "
            f"{data_artifacts.get('unchanged_page_count', 0)}개를 반영했습니다."
        )
    if not brief["summary"]:
        brief["summary"].append("이번 브리핑은 최신 검색 결과, 저장된 히스토리, 주제별 인사이트를 함께 기준으로 정리했습니다.")
    if not brief["change_flow"]:
        brief["change_flow"].append("저장된 기준본 대비 눈에 띄는 변경 흐름은 많지 않았습니다.")
    if not brief["unclear_concepts"]:
        brief["unclear_concepts"].append("현재 기준으로 설명 불가능할 만큼 큰 공백은 많지 않습니다.")

    write_json(args.output, brief)
    if args.markdown_output:
        os.makedirs(os.path.dirname(os.path.abspath(args.markdown_output)), exist_ok=True)
        with open(args.markdown_output, "w", encoding="utf-8") as handle:
            handle.write(render_markdown(brief))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
