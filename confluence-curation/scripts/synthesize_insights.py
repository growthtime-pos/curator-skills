#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


CONFIDENCE_KO = {"high": "높음", "medium": "보통", "low": "낮음"}
SYNTHESIS_STRATEGIES = {
    "balanced-synthesis",
    "briefing-synthesis",
    "action-heavy-synthesis",
}


def iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Synthesize topic-level insights from evidence packs.")
    parser.add_argument("--manifest", required=True, help="Manifest emitted by extract_evidence.py")
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-actions", type=int, default=3)
    parser.add_argument("--max-snippets", type=int, default=3)
    parser.add_argument("--purpose", default="general", choices=["general", "change-tracking", "onboarding"])
    parser.add_argument("--strategy", default="balanced-synthesis", choices=sorted(SYNTHESIS_STRATEGIES))
    return parser.parse_args()


def read_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def confidence_rank(level: str) -> int:
    return {"high": 3, "medium": 2, "low": 1}.get(level, 0)


def summarize_candidate(candidate: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not candidate:
        return None
    return {
        "page_id": candidate.get("page_id"),
        "title": candidate.get("title"),
        "updated_days_ago": candidate.get("updated_days_ago"),
        "freshness_score": candidate.get("freshness_score"),
        "trust_score": candidate.get("trust_score"),
        "keywords": candidate.get("keywords", []),
    }


def choose_evidence_snippets(pack: Dict[str, Any], max_snippets: int) -> List[Dict[str, Any]]:
    snippets: List[Dict[str, Any]] = []
    for item in pack.get("evidence_snippets", []):
        excerpt = item.get("snippets", [])[:max_snippets]
        if excerpt:
            snippets.append(
                {
                    "page_id": item.get("page_id"),
                    "title": item.get("title"),
                    "snippets": excerpt,
                }
            )
    return snippets[:max_snippets]


def derive_conclusion(pack: Dict[str, Any], purpose: str = "general", strategy: str = "balanced-synthesis") -> str:
    current = pack.get("current_candidate")
    trusted = pack.get("trusted_candidate")
    stale = pack.get("stale_candidate")
    recent_changes = pack.get("recent_changes", [])

    if purpose == "change-tracking":
        change_count = len(recent_changes)
        if current and change_count > 0:
            if strategy == "action-heavy-synthesis":
                return (
                    f"이 주제에서는 최근 {change_count}건의 변경이 감지되었고, "
                    f"`{current.get('title')}` 중심으로 추적과 후속 조치가 필요합니다."
                )
            return (
                f"이 주제에서는 최근 {change_count}건의 변경이 감지되었으며, "
                f"`{current.get('title')}` 를 중심으로 활발한 업데이트가 이루어지고 있습니다."
            )
        if current:
            return f"`{current.get('title')}` 가 이 주제의 가장 최근 문서이지만, 뚜렷한 변경 활동은 관측되지 않았습니다."
        return "이 주제에서는 최근 의미 있는 변경 활동이 관측되지 않았습니다."

    if purpose == "onboarding":
        if strategy == "briefing-synthesis" and current:
            return f"이 주제의 첫 읽기 문서로는 `{current.get('title')}` 를 추천합니다."
        if current and trusted and current.get("page_id") == trusted.get("page_id"):
            return f"이 주제를 처음 접한다면 `{current.get('title')}` 부터 읽는 것을 추천합니다. 가장 최신이면서 신뢰도도 높은 문서입니다."
        if current and trusted:
            return (
                f"이 주제의 시작점으로는 `{current.get('title')}` 를 먼저 읽고, "
                f"배경 맥락은 `{trusted.get('title')}` 에서 보충하는 것을 추천합니다."
            )
        if current:
            return f"이 주제를 처음 접한다면 `{current.get('title')}` 부터 시작하는 것이 좋지만, 추가 배경 자료를 함께 찾아보는 것을 권합니다."
        if stale:
            return f"이 주제의 문서는 `{stale.get('title')}` 가 있지만 오래되어, 최신 상황은 담당자에게 직접 확인하는 것이 좋습니다."
        return "이 주제는 시작점으로 삼을 만한 문서가 아직 충분하지 않습니다."

    # general (기존 로직)
    if strategy == "briefing-synthesis" and current:
        return f"현재 이 주제의 기준 문서는 `{current.get('title')}` 로 보는 편이 가장 안전합니다."
    if current and trusted and current.get("page_id") == trusted.get("page_id"):
        return f"이 주제의 현재 작업 기준 문서로는 `{current.get('title')}` 를 우선 참고하는 것이 적절합니다."
    if current and trusted:
        return (
            f"현재 실행 기준은 `{current.get('title')}` 를 우선 보고, 배경 정책이나 문맥은 `{trusted.get('title')}` 를 함께 참고하는 편이 좋습니다."
        )
    if current:
        return f"현재 기준으로는 `{current.get('title')}` 가 가장 유력한 작업 기준 문서지만, 보강 근거는 제한적입니다."
    if stale:
        return f"`{stale.get('title')}` 중심의 오래된 근거만 있어, 재사용 전에 추가 검증이 필요합니다."
    return "이 주제는 신뢰할 만한 작업 기준 문서를 고를 만큼 근거가 충분하지 않습니다."


def derive_change_summary(pack: Dict[str, Any]) -> List[str]:
    summaries: List[str] = []
    for change in pack.get("recent_changes", [])[:3]:
        text = (change.get("summary") or "").strip()
        if text:
            summaries.append(text)
    return summaries


def derive_gap_summary(pack: Dict[str, Any]) -> List[str]:
    gaps: List[str] = []
    for note in pack.get("missing_signals", [])[:3]:
        gaps.append(note)
    if not pack.get("evidence_snippets"):
        gaps.append("이 주제에서는 인용 가능한 근거 문장을 추출하지 못했습니다.")
    return gaps


def derive_actions(
    pack: Dict[str, Any],
    max_actions: int,
    purpose: str = "general",
    strategy: str = "balanced-synthesis",
) -> List[str]:
    actions: List[str] = []
    current = pack.get("current_candidate")
    trusted = pack.get("trusted_candidate")
    stale = pack.get("stale_candidate")
    conflict_notes = pack.get("conflict_notes", [])
    maintainers = pack.get("maintainer_signals", [])
    recent_changes = pack.get("recent_changes", [])

    if purpose == "change-tracking":
        if recent_changes:
            actions.append("이 주제의 변경 활동을 주기적으로 모니터링하세요.")
        if maintainers:
            top = maintainers[0]
            actions.append(f"`{top.get('display_name')}` 에게 최근 변경의 배경과 향후 계획을 확인하세요.")
        if current:
            actions.append(f"`{current.get('title')}` 의 업데이트 추이를 팔로업하세요.")
        if conflict_notes:
            actions.append("관련 프로젝트 간 문서 내용이 상충하는 부분이 있는지 확인하세요.")

    elif purpose == "onboarding":
        if current:
            actions.append(f"`{current.get('title')}` 를 먼저 읽으세요.")
        if trusted and (not current or trusted.get("page_id") != current.get("page_id")):
            actions.append(f"배경 맥락을 위해 `{trusted.get('title')}` 를 다음으로 읽으세요.")
        if maintainers:
            top = maintainers[0]
            actions.append(f"추가 질문은 `{top.get('display_name')}` 에게 문의하세요.")
        if stale:
            actions.append(f"`{stale.get('title')}` 는 오래되었으나 역사적 맥락 파악에 도움이 됩니다.")

    else:
        # general (기존 로직)
        if current and trusted and current.get("page_id") != trusted.get("page_id"):
            actions.append(
                f"`{current.get('title')}` 에 `{trusted.get('title')}` 의 정책/배경 문맥을 링크하거나 통합할지 검토하세요."
            )
        if stale:
            actions.append(f"`{stale.get('title')}` 를 아카이브, 리다이렉트, 또는 업데이트할지 확인하세요.")
        if conflict_notes:
            actions.append("겹치는 문서들을 검토하고 현재 기준 문서와 배경 문서를 어떻게 나눌지 명시하세요.")
        if maintainers:
            top = maintainers[0]
            actions.append(
                f"`{top.get('display_name')}` 에게 이 주제 클러스터의 소유자와 정확성을 확인해 달라고 요청하세요."
            )
        if pack.get("missing_signals"):
            actions.append("이 주제를 기준 정보로 보기 전에 누락된 프로필 또는 본문 근거를 보강하세요.")

    if strategy == "action-heavy-synthesis":
        if recent_changes:
            actions.append("최근 변경 내용을 담당자 확인 없이 운영 기준으로 바로 반영하지 말고 변경 의도를 검증하세요.")
        if conflict_notes:
            actions.append("충돌 메모가 남은 문서는 이번 주 안에 기준 문서/배경 문서로 역할을 분리하세요.")
    elif strategy == "briefing-synthesis":
        actions = actions[: max(1, min(max_actions, 2))]

    deduped: List[str] = []
    for action in actions:
        if action not in deduped:
            deduped.append(action)
    return deduped[:max_actions]


def calibrate_confidence(pack: Dict[str, Any]) -> str:
    base = confidence_rank(pack.get("confidence", "low"))
    if pack.get("missing_signals"):
        base -= 1
    if pack.get("conflict_notes"):
        base -= 1
    if pack.get("current_candidate") and pack.get("trusted_candidate"):
        current = pack["current_candidate"]
        trusted = pack["trusted_candidate"]
        if current.get("page_id") == trusted.get("page_id"):
            base += 1
    if pack.get("evidence_snippets"):
        base += 1

    if base >= 3:
        return "high"
    if base >= 2:
        return "medium"
    return "low"


def synthesize_topic(
    pack: Dict[str, Any],
    max_actions: int,
    max_snippets: int,
    purpose: str = "general",
    strategy: str = "balanced-synthesis",
) -> Dict[str, Any]:
    conclusion = derive_conclusion(pack, purpose, strategy)
    confidence = calibrate_confidence(pack)
    evidence_page_ids = sorted(
        {
            item.get("page_id")
            for item in [pack.get("current_candidate"), pack.get("trusted_candidate"), pack.get("stale_candidate")]
            if item and item.get("page_id")
        }
    )
    evidence_page_ids.extend(
        page_id
        for page_id in [snippet.get("page_id") for snippet in pack.get("evidence_snippets", [])]
        if page_id and page_id not in evidence_page_ids
    )

    return {
        "topic_id": pack.get("topic_id"),
        "label": pack.get("label"),
        "conclusion": conclusion,
        "strategy": strategy,
        "confidence": confidence,
        "confidence_ko": CONFIDENCE_KO.get(confidence, "알 수 없음"),
        "current_reference": summarize_candidate(pack.get("current_candidate")),
        "background_reference": summarize_candidate(pack.get("trusted_candidate")),
        "stale_reference": summarize_candidate(pack.get("stale_candidate")),
        "recent_change_summary": derive_change_summary(pack) if purpose != "change-tracking" else [
            (change.get("summary") or "").strip()
            for change in pack.get("recent_changes", [])[:10]
            if (change.get("summary") or "").strip()
        ],
        "conflict_notes": pack.get("conflict_notes", []),
        "evidence_gaps": derive_gap_summary(pack),
        "suggested_actions": derive_actions(pack, max_actions, purpose, strategy),
        "evidence_page_ids": evidence_page_ids,
        "evidence_snippets": choose_evidence_snippets(pack, max_snippets),
        "warnings": pack.get("warnings", []),
    }


def summarize_all(insights: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "topic_count": len(insights),
        "high_confidence_count": len([item for item in insights if item.get("confidence") == "high"]),
        "needs_attention_count": len(
            [
                item
                for item in insights
                if item.get("conflict_notes") or item.get("evidence_gaps") or item.get("confidence") == "low"
            ]
        ),
        "action_count": sum(len(item.get("suggested_actions", [])) for item in insights),
    }


def main() -> int:
    args = parse_args()
    manifest_payload = read_json(args.manifest)
    packs = manifest_payload.get("packs", [])

    insights: List[Dict[str, Any]] = []
    warnings: List[str] = list(manifest_payload.get("warnings", []))
    for item in packs:
        pack_path = item.get("output_path")
        if not pack_path:
            continue
        pack = read_json(pack_path)
        max_snippets = args.max_snippets if args.purpose != "onboarding" else max(args.max_snippets, 5)
        if args.strategy == "briefing-synthesis":
            max_snippets = min(max_snippets, 2)
        if args.strategy == "action-heavy-synthesis":
            args.max_actions = max(args.max_actions, 4)
        insights.append(synthesize_topic(pack, args.max_actions, max_snippets, args.purpose, args.strategy))

    insights.sort(
        key=lambda item: (
            confidence_rank(item.get("confidence", "low")),
            -len(item.get("conflict_notes", [])),
            item.get("label") or "",
        ),
        reverse=True,
    )

    result = {
        "meta": {
            "generated_at": iso_now(),
            "source_type": "synthesize_insights",
            "purpose": args.purpose,
            "strategy": args.strategy,
            "manifest": args.manifest,
            "topic_count": len(insights),
        },
        "summary": summarize_all(insights),
        "insights": insights,
        "warnings": warnings,
    }

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
