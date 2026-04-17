#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


QUESTION_PATTERNS = {
    "change": [r"변화", r"바뀌", r"업데이트", r"최근", r"history", r"change"],
    "meaning": [r"무슨 뜻", r"의미", r"이해", r"설명", r"왜", r"뜻"],
    "action": [r"뭘 해야", r"무엇을 해야", r"next", r"다음", r"액션", r"어떻게"],
}


def iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="artifact 기반 후속 질문 응답 JSON 을 생성합니다.")
    parser.add_argument("--insights-input", required=True)
    parser.add_argument("--review-input", required=True)
    parser.add_argument("--normalized-input", required=True)
    parser.add_argument("--graph-context-input")
    parser.add_argument("--question", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def read_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: str, payload: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def tokenize(text: str) -> List[str]:
    return re.findall(r"[a-z0-9가-힣]{2,}", text.lower())


def infer_question_mode(question: str) -> str:
    for mode, patterns in QUESTION_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, question, re.IGNORECASE):
                return mode
    return "meaning"


def score_insight(insight: Dict[str, Any], question_tokens: List[str], mode: str) -> float:
    score = 0.0
    haystacks = [
        insight.get("label") or "",
        insight.get("conclusion") or "",
        " ".join(insight.get("conflict_notes", [])),
        " ".join(insight.get("evidence_gaps", [])),
        " ".join(insight.get("suggested_actions", [])),
    ]
    blob = " ".join(haystacks).lower()
    for token in question_tokens:
        if token in blob:
            score += 2.0
    if mode == "change" and insight.get("recent_change_summary"):
        score += 3.0
    if mode == "action" and insight.get("suggested_actions"):
        score += 2.5
    if mode == "meaning" and insight.get("evidence_snippets"):
        score += 2.0
    return score


def choose_best_insight(insights: List[Dict[str, Any]], question: str, mode: str) -> Dict[str, Any]:
    question_tokens = tokenize(question)
    ranked = sorted(
        insights,
        key=lambda item: (score_insight(item, question_tokens, mode), item.get("confidence") == "high"),
        reverse=True,
    )
    return ranked[0] if ranked else {}


def build_graph_summary(insight: Dict[str, Any], graph_context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not graph_context or not ((graph_context.get("meta") or {}).get("graphify_available")):
        return {}
    graph_summary = insight.get("graph_context") or {}
    return {
        "communities": graph_summary.get("communities", [])[:3],
        "bridge_pages": graph_summary.get("bridge_pages", [])[:3],
        "suggested_questions": graph_summary.get("suggested_questions", [])[:3],
    }


def build_supporting_pages(insight: Dict[str, Any], page_lookup: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    pages: List[Dict[str, Any]] = []
    for key in ["current_reference", "background_reference", "stale_reference"]:
        ref = insight.get(key) or {}
        page = page_lookup.get(ref.get("page_id")) or {}
        if not ref.get("page_id"):
            continue
        pages.append(
            {
                "page_id": ref.get("page_id"),
                "title": ref.get("title"),
                "space_key": page.get("space_key"),
                "updated_at": page.get("updated_at"),
                "change_summary": (page.get("change_summary") or {}).get("summary_ko"),
            }
        )
    deduped: List[Dict[str, Any]] = []
    seen = set()
    for item in pages:
        page_id = item.get("page_id")
        if page_id and page_id not in seen:
            seen.add(page_id)
            deduped.append(item)
    return deduped


def build_best_explanation(insight: Dict[str, Any], mode: str, graph_summary: Optional[Dict[str, Any]] = None) -> str:
    label = insight.get("label") or "이 주제"
    if mode == "change":
        recent = (insight.get("recent_change_summary") or [None])[0]
        base = recent or f"{label} 관련 문서들은 최근 업데이트 흐름을 기준으로 다시 검토할 필요가 있습니다."
    elif mode == "action":
        action = (insight.get("suggested_actions") or [None])[0]
        base = action or f"{label} 주제에서는 현재 기준 문서와 배경 문서를 나눠 확인한 뒤 정리 방향을 결정하는 것이 좋습니다."
    else:
        snippet_groups = insight.get("evidence_snippets") or []
        if snippet_groups:
            snippets = snippet_groups[0].get("snippets", [])
            if snippets:
                base = (
                    f"{label} 문맥에서 가장 직접적인 설명은 다음 근거에서 잡을 수 있습니다: "
                    + snippets[0]
                )
            else:
                base = insight.get("conclusion") or f"{label} 주제는 관련 문서를 비교해 맥락을 함께 봐야 이해가 쉬운 상태입니다."
        else:
            base = insight.get("conclusion") or f"{label} 주제는 관련 문서를 비교해 맥락을 함께 봐야 이해가 쉬운 상태입니다."
    if graph_summary and graph_summary.get("communities"):
        return base + f" 이 주제는 graph 상에서 `{', '.join(graph_summary['communities'])}` 커뮤니티와 연결됩니다."
    return base


def build_question_interpretation(question: str, mode: str, insight: Dict[str, Any]) -> str:
    label = insight.get("label") or "관련 주제"
    if mode == "change":
        return f"질문을 '{label}' 주제에서 최근 무엇이 바뀌었는지 묻는 것으로 해석했습니다."
    if mode == "action":
        return f"질문을 '{label}' 주제에서 지금 어떤 후속 조치를 취해야 하는지 묻는 것으로 해석했습니다."
    return f"질문을 '{label}' 주제의 의미와 배경을 설명해 달라는 요청으로 해석했습니다."


def main() -> int:
    args = parse_args()
    insights_payload = read_json(args.insights_input)
    review_payload = read_json(args.review_input)
    normalized_payload = read_json(args.normalized_input)
    graph_context = read_json(args.graph_context_input) if args.graph_context_input and os.path.exists(args.graph_context_input) else None

    mode = infer_question_mode(args.question)
    best_insight = choose_best_insight(insights_payload.get("insights", []), args.question, mode)
    graph_summary = build_graph_summary(best_insight, graph_context)
    page_lookup = {
        page.get("page_id"): page
        for page in normalized_payload.get("pages", [])
        if page.get("page_id")
    }
    review_lookup = {
        item.get("topic_id"): item
        for item in review_payload.get("reviews", [])
        if item.get("topic_id")
    }
    review = review_lookup.get(best_insight.get("topic_id"), {})

    result = {
        "meta": {
            "generated_at": iso_now(),
            "source_type": "answer_followup",
            "mode": mode,
            "insights_input": os.path.abspath(args.insights_input),
            "review_input": os.path.abspath(args.review_input),
            "normalized_input": os.path.abspath(args.normalized_input),
        },
        "question": args.question,
        "question_interpretation": build_question_interpretation(args.question, mode, best_insight),
        "best_explanation_ko": build_best_explanation(best_insight, mode, graph_summary),
        "supporting_pages": build_supporting_pages(best_insight, page_lookup),
        "supporting_snippets": best_insight.get("evidence_snippets", [])[:3],
        "conflicting_points": best_insight.get("conflict_notes", [])[:3],
        "what_to_verify": (
            best_insight.get("evidence_gaps", [])[:3]
            or [note for reviewer in review.get("reviewers", []) for note in reviewer.get("findings", [])[:1]][:3]
        ),
        "suggested_next_actions": best_insight.get("suggested_actions", [])[:3],
        "graph_context_summary": graph_summary,
    }
    write_json(args.output, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
