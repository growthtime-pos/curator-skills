#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple


DEFAULT_MAX_PAGES = 500


def iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def _page_richness(page: Dict[str, Any]) -> int:
    score = 0
    if page.get("body_excerpt"):
        score += 2
    if page.get("version_events"):
        score += len(page["version_events"])
    if page.get("recent_contributors"):
        score += len(page["recent_contributors"])
    if page.get("labels"):
        score += len(page["labels"])
    return score


def merge_pages(
    all_pages: List[Tuple[str, Dict[str, Any]]],
    max_pages: int,
) -> Tuple[List[Dict[str, Any]], int, int]:
    seen: Dict[str, Dict[str, Any]] = {}
    total_before = 0
    for _source, page in all_pages:
        total_before += 1
        page_id = str(page.get("page_id", ""))
        if not page_id:
            continue
        existing = seen.get(page_id)
        if existing is None:
            seen[page_id] = page
        else:
            existing_ver = existing.get("version_number", 0) or 0
            new_ver = page.get("version_number", 0) or 0
            if new_ver > existing_ver:
                seen[page_id] = page
            elif new_ver == existing_ver and _page_richness(page) > _page_richness(existing):
                seen[page_id] = page
    pages = list(seen.values())[:max_pages]
    return pages, total_before, len(pages)


def merge_people(all_people: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: Dict[str, Dict[str, Any]] = {}
    for person in all_people:
        account_id = person.get("account_id", "")
        if account_id and account_id not in seen:
            seen[account_id] = person
    return list(seen.values())


def merge_relationships(all_rels: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: set = set()
    merged: List[Dict[str, Any]] = []
    for rel in all_rels:
        key = (
            rel.get("from_page_id", ""),
            rel.get("to_page_id", ""),
            rel.get("type", ""),
        )
        if key not in seen:
            seen.add(key)
            merged.append(rel)
    return merged


def merge_warnings(all_warnings: List[str]) -> List[str]:
    seen: set = set()
    merged: List[str] = []
    for w in all_warnings:
        if w not in seen:
            seen.add(w)
            merged.append(w)
    return merged


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="여러 Confluence fetch 결과 JSON 파일을 병합하고 중복을 제거합니다.",
    )
    parser.add_argument(
        "--inputs",
        nargs="+",
        required=True,
        help="병합할 fetch 결과 JSON 파일 목록입니다.",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="병합된 결과를 저장할 JSON 파일 경로입니다.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=DEFAULT_MAX_PAGES,
        help=f"병합 후 유지할 최대 페이지 수입니다. (기본값: {DEFAULT_MAX_PAGES})",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    datasets: List[Dict[str, Any]] = []
    for path in args.inputs:
        with open(path, "r", encoding="utf-8") as f:
            datasets.append(json.load(f))

    if not datasets:
        print("병합할 파일이 없습니다.", flush=True)
        return 1

    all_pages: List[Tuple[str, Dict[str, Any]]] = []
    all_people: List[Dict[str, Any]] = []
    all_rels: List[Dict[str, Any]] = []
    all_warnings: List[str] = []
    rounds: List[Dict[str, Any]] = []

    for path, data in zip(args.inputs, datasets):
        pages = data.get("pages", [])
        all_pages.extend((path, p) for p in pages)
        all_people.extend(data.get("people", []))
        all_rels.extend(data.get("relationships", []))
        all_warnings.extend(data.get("warnings", []))

        source_meta = data.get("meta", {})
        scope = source_meta.get("scope", {})
        rounds.append({
            "file": os.path.abspath(path),
            "query": scope.get("query", ""),
            "page_count": len(pages),
        })

    merged_pages, total_before, total_after = merge_pages(all_pages, args.max_pages)
    merged_people = merge_people(all_people)
    merged_rels = merge_relationships(all_rels)
    merged_warnings = merge_warnings(all_warnings)

    base_meta = datasets[0].get("meta", {})
    merged_meta = {
        **base_meta,
        "merged_at": iso_now(),
        "source_files": [os.path.abspath(p) for p in args.inputs],
        "rounds": rounds,
        "total_pages_before_dedup": total_before,
        "total_pages_after_dedup": total_after,
    }

    result = {
        "meta": merged_meta,
        "pages": merged_pages,
        "people": merged_people,
        "relationships": merged_rels,
        "warnings": merged_warnings,
    }

    out_dir = os.path.dirname(args.output)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(
        f"병합 완료: {len(args.inputs)}개 파일, "
        f"{total_before}→{total_after} 페이지 (중복 제거 후) → {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
