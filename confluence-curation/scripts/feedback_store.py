#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional


SENSITIVE_INFORMATION_NOTICE = (
    "피드백에는 비밀번호, 토큰, 개인 민감정보, Confluence 원문을 붙여넣지 마세요."
)


def iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def new_run_id() -> str:
    return f"run_{uuid.uuid4().hex}"


def new_feedback_id() -> str:
    return f"feedback_{uuid.uuid4().hex}"


def default_feedback_output(output_dir: str) -> str:
    return os.path.join(os.path.abspath(output_dir), "feedback", "feedback.jsonl")


def append_feedback_record(path: str, record: Dict[str, Any]) -> str:
    output_path = os.path.abspath(path)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "a", encoding="utf-8") as handle:
        json.dump(record, handle, ensure_ascii=False, sort_keys=True)
        handle.write("\n")
    return output_path


def prompt_rating(label: str) -> int:
    while True:
        response = input(f"{label} (1-5): ").strip()
        if response in {"1", "2", "3", "4", "5"}:
            return int(response)
        print("1부터 5 사이의 숫자로 입력해 주세요.")


def prompt_missing_content() -> str:
    while True:
        response = input("빠진 내용이 있었나요? (yes/no/unsure): ").strip().lower()
        if response in {"yes", "no", "unsure"}:
            return response
        print("yes, no, unsure 중 하나로 입력해 주세요.")


def collect_feedback_from_cli() -> Optional[Dict[str, Any]]:
    print("")
    print("파이프라인 결과에 대한 짧은 피드백을 남겨 주세요.")
    print(SENSITIVE_INFORMATION_NOTICE)
    try:
        return {
            "usefulness_score": prompt_rating("유용성 점수"),
            "accuracy_score": prompt_rating("정확성/신뢰도 점수"),
            "missing_content": prompt_missing_content(),
            "free_text": input("자유 의견 (선택, 한 줄): ").strip(),
        }
    except EOFError:
        print("")
        print("입력이 종료되어 피드백 수집을 건너뜁니다.")
        return None


def summarize_artifact_counts(
    fetch_payload: Optional[Dict[str, Any]],
    insights_payload: Optional[Dict[str, Any]],
    review_payload: Optional[Dict[str, Any]],
) -> Dict[str, int]:
    fetch_payload = fetch_payload or {}
    insights_payload = insights_payload or {}
    review_payload = review_payload or {}
    return {
        "page_count": len(fetch_payload.get("pages", [])),
        "people_count": len(fetch_payload.get("people", [])),
        "relationship_count": len(fetch_payload.get("relationships", [])),
        "warning_count": len(fetch_payload.get("warnings", [])),
        "insight_count": len(insights_payload.get("insights", [])),
        "review_count": len(review_payload.get("reviews", [])),
    }


def build_feedback_record(
    *,
    run_id: str,
    purpose: str,
    selected_methods: Dict[str, str],
    artifacts: Dict[str, str],
    responses: Dict[str, Any],
    summary_counts: Dict[str, int],
) -> Dict[str, Any]:
    return {
        "feedback_id": new_feedback_id(),
        "run_id": run_id,
        "created_at": iso_now(),
        "purpose": purpose,
        "selected_methods": {
            "stage0_pre_analysis": selected_methods.get("stage0_pre_analysis"),
            "stage1_extract": selected_methods.get("stage1_extract"),
            "stage2_cluster": selected_methods.get("stage2_cluster"),
            "stage3_analyze": selected_methods.get("stage3_analyze"),
            "stage4_synthesize": selected_methods.get("stage4_synthesize"),
            "stage5_validate": selected_methods.get("stage5_validate"),
        },
        "artifacts": {
            "report": artifacts.get("report"),
            "brief": artifacts.get("brief"),
            "pipeline_result": artifacts.get("pipeline_result"),
        },
        "responses": {
            "usefulness_score": responses.get("usefulness_score"),
            "accuracy_score": responses.get("accuracy_score"),
            "missing_content": responses.get("missing_content"),
            "free_text": responses.get("free_text", ""),
        },
        "summary_counts": summary_counts,
    }
