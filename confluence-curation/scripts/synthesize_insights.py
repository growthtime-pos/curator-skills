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
    parser = argparse.ArgumentParser(description="Synthesize topic-level insights from evidence packs.")
    parser.add_argument("--manifest", required=True, help="Manifest emitted by extract_evidence.py")
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-actions", type=int, default=3)
    parser.add_argument("--max-snippets", type=int, default=3)
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


def derive_conclusion(pack: Dict[str, Any]) -> str:
    current = pack.get("current_candidate")
    trusted = pack.get("trusted_candidate")
    stale = pack.get("stale_candidate")

    if current and trusted and current.get("page_id") == trusted.get("page_id"):
        return f"Use `{current.get('title')}` as the current working reference for this topic."
    if current and trusted:
        return (
            f"Use `{current.get('title')}` for current execution, but keep `{trusted.get('title')}` as background or policy context."
        )
    if current:
        return f"`{current.get('title')}` is the best available working reference, but supporting context is limited."
    if stale:
        return f"Only stale evidence is available, led by `{stale.get('title')}`, so this topic needs verification before reuse."
    return "This topic lacks enough evidence to identify a reliable working reference."


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
        gaps.append("No evidence snippets were extracted for this topic.")
    return gaps


def derive_actions(pack: Dict[str, Any], max_actions: int) -> List[str]:
    actions: List[str] = []
    current = pack.get("current_candidate")
    trusted = pack.get("trusted_candidate")
    stale = pack.get("stale_candidate")
    conflict_notes = pack.get("conflict_notes", [])
    maintainers = pack.get("maintainer_signals", [])

    if current and trusted and current.get("page_id") != trusted.get("page_id"):
        actions.append(
            f"Review whether `{current.get('title')}` should link to or absorb policy context from `{trusted.get('title')}`."
        )
    if stale:
        actions.append(f"Check whether `{stale.get('title')}` should be archived, redirected, or updated.")
    if conflict_notes:
        actions.append("Review overlapping pages and document the official current-vs-background split.")
    if maintainers:
        top = maintainers[0]
        actions.append(
            f"Ask `{top.get('display_name')}` to confirm ownership and accuracy for this topic cluster."
        )
    if pack.get("missing_signals"):
        actions.append("Collect missing profile or body evidence before treating this topic as authoritative.")

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


def synthesize_topic(pack: Dict[str, Any], max_actions: int, max_snippets: int) -> Dict[str, Any]:
    conclusion = derive_conclusion(pack)
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
        "confidence": confidence,
        "current_reference": summarize_candidate(pack.get("current_candidate")),
        "background_reference": summarize_candidate(pack.get("trusted_candidate")),
        "stale_reference": summarize_candidate(pack.get("stale_candidate")),
        "recent_change_summary": derive_change_summary(pack),
        "conflict_notes": pack.get("conflict_notes", []),
        "evidence_gaps": derive_gap_summary(pack),
        "suggested_actions": derive_actions(pack, max_actions),
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
        insights.append(synthesize_topic(pack, args.max_actions, args.max_snippets))

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
