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
    "evidence-first-synthesis",
    "pyramid-synthesis",
    "hypothesis-driven-synthesis",
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


def reasoning_method_for_strategy(strategy: str) -> str:
    if strategy == "pyramid-synthesis":
        return "pyramid"
    if strategy == "hypothesis-driven-synthesis":
        return "hypothesis-driven"
    return "evidence-first"


def build_support_items(pack: Dict[str, Any]) -> List[str]:
    items: List[str] = []
    current = pack.get("current_candidate")
    trusted = pack.get("trusted_candidate")
    stale = pack.get("stale_candidate")

    if current:
        items.append(
            f"현재 작업 기준 후보는 `{current.get('title')}` 이며 최신성 신호는 {current.get('updated_days_ago')}일 전 업데이트 기준입니다."
        )
    if trusted and trusted.get("page_id") != (current or {}).get("page_id"):
        items.append(
            f"배경/정책 맥락은 `{trusted.get('title')}` 에 더 강하게 남아 있어 실행 문서와 참고 문서가 분리되어 있습니다."
        )
    if pack.get("recent_changes"):
        items.append(
            f"최근 변경 신호가 {len(pack.get('recent_changes', []))}건 있어 문서 운영 상태가 계속 변하고 있습니다."
        )
    if pack.get("conflict_notes"):
        items.append(
            f"충돌 또는 중복 신호가 {len(pack.get('conflict_notes', []))}건 있어 기준 문서 정리가 필요합니다."
        )
    if stale:
        items.append(f"`{stale.get('title')}` 는 오래된 참고 후보로 남아 있어 재사용 전에 검증이 필요합니다.")
    if pack.get("missing_signals"):
        items.append("근거 또는 프로필 신호가 일부 비어 있어 단정적 결론을 피해야 합니다.")

    deduped: List[str] = []
    for item in items:
        if item not in deduped:
            deduped.append(item)
    return deduped


def derive_key_supports(pack: Dict[str, Any], max_supports: int = 3) -> List[str]:
    return build_support_items(pack)[:max_supports]


def derive_wider_significance(pack: Dict[str, Any], purpose: str = "general") -> str:
    current = pack.get("current_candidate")
    trusted = pack.get("trusted_candidate")
    if pack.get("conflict_notes"):
        return "문서가 여러 갈래로 운영되고 있어 팀이 실제 작업 기준과 배경 정책 문서를 명시적으로 분리해야 합니다."
    if pack.get("missing_signals"):
        return "현재 문서 체계는 참고는 가능하지만, 운영 기준으로 쓰기 전에 추가 검증과 소유자 확인이 필요합니다."
    if current and trusted and current.get("page_id") == trusted.get("page_id"):
        if purpose == "onboarding":
            return "신규 인원이 한 문서에서 최신 정보와 배경 맥락을 함께 확보할 수 있어 진입 비용이 낮습니다."
        return "최신성과 신뢰가 한 문서에 수렴해 있어 팀 기준 문서로 통합 관리하기 좋은 상태입니다."
    if current and trusted:
        return "최신 실행 문서와 배경 정책 문서가 분리되어 있어 링크 정리나 읽기 순서 안내가 필요합니다."
    if current:
        return "실행 기준 후보는 보이지만 보강 근거가 약해 운영 리스크가 남아 있습니다."
    return "의미 있는 기준 문서를 특정하기 어려워 문서 구조 자체의 재정리가 필요합니다."


def derive_hypothesis(pack: Dict[str, Any], purpose: str = "general") -> str:
    current = pack.get("current_candidate")
    trusted = pack.get("trusted_candidate")
    if purpose == "change-tracking" and current:
        return f"이 주제의 운영 기준은 최근 변경이 집중된 `{current.get('title')}` 로 이동하고 있다."
    if current and trusted and current.get("page_id") == trusted.get("page_id"):
        return f"`{current.get('title')}` 가 현재 작업 기준과 배경 참고를 동시에 만족하는 단일 기준 문서다."
    if current and trusted:
        return f"`{current.get('title')}` 는 실행 기준이고 `{trusted.get('title')}` 는 배경 정책 문서다."
    if current:
        return f"`{current.get('title')}` 가 가장 유력한 작업 기준 문서다."
    return "이 주제는 아직 신뢰할 만한 기준 문서가 정리되지 않았다."


def derive_validation_points(pack: Dict[str, Any]) -> List[Dict[str, Any]]:
    points: List[Dict[str, Any]] = []
    current = pack.get("current_candidate")
    trusted = pack.get("trusted_candidate")

    if current:
        points.append(
            {
                "check": "최신성 신호",
                "result": f"`{current.get('title')}` 가 현재 후보로 가장 최근에 가깝습니다.",
                "status": "supports",
            }
        )
    if trusted:
        status = "supports" if trusted.get("page_id") == (current or {}).get("page_id") else "mixed"
        points.append(
            {
                "check": "신뢰/배경 신호",
                "result": f"`{trusted.get('title')}` 가 신뢰 또는 배경 문맥을 제공합니다.",
                "status": status,
            }
        )
    if pack.get("conflict_notes"):
        points.append(
            {
                "check": "충돌 신호",
                "result": pack.get("conflict_notes", [])[0],
                "status": "contradicts",
            }
        )
    if pack.get("missing_signals"):
        points.append(
            {
                "check": "근거 공백",
                "result": pack.get("missing_signals", [])[0],
                "status": "mixed",
            }
        )
    if pack.get("recent_changes"):
        points.append(
            {
                "check": "변경 흐름",
                "result": (pack.get("recent_changes", [])[0].get("summary") or "").strip() or "최근 변경이 감지되었습니다.",
                "status": "supports",
            }
        )
    return points[:4]


def derive_hypothesis_status(pack: Dict[str, Any]) -> str:
    if pack.get("conflict_notes"):
        return "mixed"
    if pack.get("missing_signals") and not pack.get("current_candidate"):
        return "rejected"
    if pack.get("missing_signals"):
        return "mixed"
    if pack.get("current_candidate"):
        return "supported"
    return "rejected"


def derive_pivot_question(pack: Dict[str, Any], hypothesis_status: str) -> Optional[str]:
    if hypothesis_status == "supported":
        return None
    maintainers = pack.get("maintainer_signals", [])
    if maintainers:
        return f"`{maintainers[0].get('display_name')}` 에게 현재 기준 문서와 오래된 참고 문서의 역할 분리를 확인해야 합니다."
    if pack.get("conflict_notes"):
        return "겹치는 문서 중 어떤 문서를 실제 운영 기준으로 사용할지 팀 합의가 필요합니다."
    return "현재 문서를 기준 정보로 보기 전에 최신 본문 근거와 소유자 신호를 보강해야 합니다."


def derive_evidence_first_conclusion(
    pack: Dict[str, Any],
    purpose: str = "general",
    strategy: str = "balanced-synthesis",
) -> str:
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


def derive_conclusion(pack: Dict[str, Any], purpose: str = "general", strategy: str = "balanced-synthesis") -> str:
    reasoning_method = reasoning_method_for_strategy(strategy)
    if reasoning_method == "hypothesis-driven":
        hypothesis_status = derive_hypothesis_status(pack)
        hypothesis = derive_hypothesis(pack, purpose)
        if hypothesis_status == "supported":
            return f"가설이 대체로 지지됩니다: {hypothesis}"
        if hypothesis_status == "mixed":
            return f"가설은 부분적으로만 지지됩니다: {hypothesis}"
        return f"가설을 그대로 채택하기 어렵습니다: {hypothesis}"
    return derive_evidence_first_conclusion(pack, purpose, strategy)


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
    reasoning_method = reasoning_method_for_strategy(strategy)

    if reasoning_method == "hypothesis-driven":
        if maintainers:
            actions.append(f"`{maintainers[0].get('display_name')}` 에게 현재 기준 문서 가설을 확인하세요.")
        if conflict_notes:
            actions.append("상충하는 문서 중 실제 운영 기준이 무엇인지 검증 회의를 잡으세요.")
        if current:
            actions.append(f"`{current.get('title')}` 의 최신 본문이 실제 운영 절차와 일치하는지 검증하세요.")
        if pack.get("missing_signals"):
            actions.append("누락된 프로필 또는 본문 근거를 보강한 뒤 가설 상태를 다시 판단하세요.")
    elif purpose == "change-tracking":
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
    elif strategy == "pyramid-synthesis":
        actions = actions[: min(max_actions, 2)]

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
    reasoning_method = reasoning_method_for_strategy(strategy)
    current = pack.get("current_candidate")
    trusted = pack.get("trusted_candidate")
    stale = pack.get("stale_candidate")
    executive_answer = derive_evidence_first_conclusion(pack, purpose, strategy)
    conclusion = derive_conclusion(pack, purpose, strategy)
    confidence = calibrate_confidence(pack)
    evidence_page_ids = sorted(
        {
            item.get("page_id")
            for item in [current, trusted, stale]
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
        "strategy": strategy,
        "reasoning_method": reasoning_method,
        "conclusion": conclusion,
        "executive_answer": executive_answer if reasoning_method == "pyramid" else None,
        "key_supports": derive_key_supports(pack) if reasoning_method == "pyramid" else [],
        "wider_significance": derive_wider_significance(pack, purpose) if reasoning_method == "pyramid" else None,
        "working_hypothesis": derive_hypothesis(pack, purpose) if reasoning_method == "hypothesis-driven" else None,
        "validation_points": derive_validation_points(pack) if reasoning_method == "hypothesis-driven" else [],
        "hypothesis_status": derive_hypothesis_status(pack) if reasoning_method == "hypothesis-driven" else None,
        "pivot_question": derive_pivot_question(pack, derive_hypothesis_status(pack)) if reasoning_method == "hypothesis-driven" else None,
        "confidence": confidence,
        "confidence_ko": CONFIDENCE_KO.get(confidence, "알 수 없음"),
        "current_reference": summarize_candidate(current),
        "background_reference": summarize_candidate(trusted),
        "stale_reference": summarize_candidate(stale),
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
        max_actions = args.max_actions
        if args.strategy == "briefing-synthesis":
            max_snippets = min(max_snippets, 2)
        if args.strategy == "action-heavy-synthesis":
            max_actions = max(max_actions, 4)
        insights.append(synthesize_topic(pack, max_actions, max_snippets, args.purpose, args.strategy))

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
            "reasoning_method": reasoning_method_for_strategy(args.strategy),
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
