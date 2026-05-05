#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple


def iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="1차 fetch 결과를 바탕으로 내부 preferred space 후보를 추론합니다."
    )
    parser.add_argument("--input", required=True, help="fetch 또는 merge 결과 JSON 경로")
    parser.add_argument("--output", required=True)
    parser.add_argument("--top-n", type=int, default=3, help="최대 preferred space 후보 수")
    parser.add_argument("--min-score", type=float, default=6.0, help="후보 채택 최소 점수")
    return parser.parse_args()


def read_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: str, payload: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def days_ago(value: str) -> int | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0, (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).days)


def normalize_team(team: str | None) -> str | None:
    if not team:
        return None
    return " ".join(team.split()).strip().lower()


def page_strength(page: Dict[str, Any], people_by_id: Dict[str, Dict[str, Any]]) -> Tuple[float, List[str]]:
    score = 0.0
    reasons: List[str] = []

    updated_days = days_ago(page.get("updated_at"))
    if updated_days is not None:
        if updated_days <= 14:
            score += 2.0
            reasons.append("최근 14일 내 갱신")
        elif updated_days <= 45:
            score += 1.2
            reasons.append("최근 45일 내 갱신")

    if len(page.get("version_events", [])) >= 2:
        score += 1.2
        reasons.append("버전 이력 반복")
    elif page.get("version_events"):
        score += 0.7

    if len(page.get("recent_contributors", [])) >= 2:
        score += 1.4
        reasons.append("복수 기여자 유지")

    if page.get("body_excerpt"):
        score += 0.8

    change = page.get("change_summary") or {}
    if change.get("changed"):
        score += min(float(change.get("importance_score", 0) or 0) / 8.0, 2.4)
        reasons.append(change.get("summary_ko") or "저장본 대비 변경 감지")

    team_hits = 0
    for account_id in page.get("recent_contributors", []):
        person = people_by_id.get(account_id) or {}
        org_hint = person.get("org_hint") or {}
        if org_hint.get("team"):
            team_hits += 1
        confidence = org_hint.get("confidence")
        role_band = org_hint.get("role_band")
        if confidence == "high":
            score += 0.6
        elif confidence == "medium":
            score += 0.3
        if role_band in {"lead", "director", "staff"}:
            score += 0.5
    if team_hits:
        reasons.append("기여자 팀 맥락 존재")

    if page.get("labels"):
        score += min(len(page["labels"]) * 0.2, 0.8)

    return score, reasons[:4]


def infer_spaces(payload: Dict[str, Any], top_n: int, min_score: float) -> Dict[str, Any]:
    pages = payload.get("pages", [])
    people_by_id = {
        person.get("account_id"): person
        for person in payload.get("people", [])
        if person.get("account_id")
    }

    space_scores: Dict[str, float] = defaultdict(float)
    space_reasons: Dict[str, List[str]] = defaultdict(list)
    space_candidate_pages: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    space_team_counter: Dict[str, Counter[str]] = defaultdict(Counter)

    for page in pages:
        space_key = page.get("space_key")
        if not space_key:
            continue
        score, reasons = page_strength(page, people_by_id)
        space_scores[space_key] += score
        space_reasons[space_key].extend(reasons)
        space_candidate_pages[space_key].append(
            {
                "page_id": page.get("page_id"),
                "title": page.get("title"),
                "updated_at": page.get("updated_at"),
                "change_summary": (page.get("change_summary") or {}).get("summary_ko"),
                "score": round(score, 2),
            }
        )
        for account_id in page.get("recent_contributors", []):
            person = people_by_id.get(account_id) or {}
            team = normalize_team(((person.get("org_hint") or {}).get("team")))
            if team:
                space_team_counter[space_key][team] += 1

    scored_spaces: List[Dict[str, Any]] = []
    for space_key, score in space_scores.items():
        if score < min_score:
            continue
        top_teams = [team for team, _count in space_team_counter[space_key].most_common(3)]
        unique_reasons: List[str] = []
        for reason in space_reasons[space_key]:
            if reason and reason not in unique_reasons:
                unique_reasons.append(reason)
        candidate_pages = sorted(
            space_candidate_pages[space_key],
            key=lambda item: (item.get("score", 0), item.get("updated_at") or ""),
            reverse=True,
        )[:5]
        if top_teams:
            unique_reasons.append("반복 등장 팀: " + ", ".join(top_teams))
        scored_spaces.append(
            {
                "space_key": space_key,
                "score": round(score, 2),
                "reasons": unique_reasons[:5],
                "candidate_pages": candidate_pages,
                "team_signals": top_teams,
            }
        )

    scored_spaces.sort(key=lambda item: (item["score"], item["space_key"]), reverse=True)
    preferred_spaces = [item["space_key"] for item in scored_spaces[:top_n]]
    confidence = "low"
    if scored_spaces and scored_spaces[0]["score"] >= 10:
        confidence = "high"
    elif scored_spaces and scored_spaces[0]["score"] >= 7:
        confidence = "medium"

    summary_reasons: List[str] = []
    for item in scored_spaces[:top_n]:
        if item["reasons"]:
            summary_reasons.append(f"{item['space_key']}: {item['reasons'][0]}")

    return {
        "meta": {
            "generated_at": iso_now(),
            "source_type": "infer_preferred_spaces",
            "input_path": os.path.abspath(payload.get("meta", {}).get("source_path", "")) if payload.get("meta", {}).get("source_path") else None,
            "page_count": len(pages),
            "top_n": top_n,
            "min_score": min_score,
        },
        "preferred_spaces": preferred_spaces,
        "confidence": confidence,
        "reasons": summary_reasons,
        "spaces": scored_spaces[:top_n],
        "candidate_pages": [
            candidate
            for item in scored_spaces[:top_n]
            for candidate in item.get("candidate_pages", [])[:2]
        ],
    }


def main() -> int:
    args = parse_args()
    payload = read_json(args.input)
    payload.setdefault("meta", {})
    payload["meta"]["source_path"] = os.path.abspath(args.input)
    result = infer_spaces(payload, args.top_n, args.min_score)
    write_json(args.output, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
