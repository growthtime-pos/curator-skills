#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List


STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "have",
    "will",
    "your",
    "into",
    "page",
    "pages",
    "문서",
    "정리",
    "관련",
    "대한",
    "에서",
    "있는",
    "하기",
    "그리고",
    "으로",
    "합니다",
}

TOKEN_PATTERN = re.compile(r"[a-z0-9가-힣]{3,}")

MAX_SUGGESTED_TERMS = 5
MIN_SCORE_THRESHOLD = 1.5


def iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def tokenize(text: str) -> List[str]:
    return TOKEN_PATTERN.findall(text.lower())


def is_redundant_with_query(token: str, original_terms: List[str]) -> bool:
    for term in original_terms:
        if token == term:
            return True
        if len(term) >= 4 and len(token) >= 4:
            if token.startswith(term) or term.startswith(token):
                return True
    return False


def extract_label_tokens(pages: List[Dict[str, Any]]) -> Counter:
    counts: Counter = Counter()
    for page in pages:
        for label in page.get("labels", []):
            normalized = label.strip().lower()
            if len(normalized) >= 3 and normalized not in STOPWORDS:
                counts[normalized] += 1
    return counts


def extract_title_tokens(pages: List[Dict[str, Any]]) -> Counter:
    counts: Counter = Counter()
    for page in pages:
        title = page.get("title", "")
        for token in tokenize(title):
            if token not in STOPWORDS:
                counts[token] += 1
    return counts


def extract_ancestor_tokens(pages: List[Dict[str, Any]]) -> Counter:
    counts: Counter = Counter()
    for page in pages:
        for ancestor in page.get("ancestors", []):
            title = ancestor.get("title", "")
            for token in tokenize(title):
                if token not in STOPWORDS:
                    counts[token] += 1
    return counts


def extract_body_tokens(pages: List[Dict[str, Any]]) -> Counter:
    counts: Counter = Counter()
    for page in pages:
        body = page.get("body_excerpt", "")
        for token in tokenize(body):
            if token not in STOPWORDS:
                counts[token] += 1
    return counts


def find_sample_titles(keyword: str, pages: List[Dict[str, Any]], limit: int = 3) -> List[str]:
    titles: List[str] = []
    for page in pages:
        title = page.get("title", "")
        labels = [lb.lower() for lb in page.get("labels", [])]
        body = page.get("body_excerpt", "")
        ancestor_titles = " ".join(a.get("title", "") for a in page.get("ancestors", []))
        haystack = f"{title} {body} {ancestor_titles}".lower()
        if keyword in haystack or keyword in labels:
            titles.append(title)
            if len(titles) >= limit:
                break
    return titles


def score_candidates(
    pages: List[Dict[str, Any]],
    original_terms: List[str],
    min_frequency: int,
) -> List[Dict[str, Any]]:
    label_counts = extract_label_tokens(pages)
    title_counts = extract_title_tokens(pages)
    ancestor_counts = extract_ancestor_tokens(pages)
    body_counts = extract_body_tokens(pages)

    all_tokens = set(label_counts) | set(title_counts) | set(ancestor_counts) | set(body_counts)

    total_pages = max(len(pages), 1)
    candidates: List[Dict[str, Any]] = []

    for token in sorted(all_tokens):
        if is_redundant_with_query(token, original_terms):
            continue

        freq_label = label_counts.get(token, 0)
        freq_title = title_counts.get(token, 0)
        freq_ancestor = ancestor_counts.get(token, 0)
        freq_body = body_counts.get(token, 0)
        total_freq = freq_label + freq_title + freq_ancestor + freq_body

        if total_freq < min_frequency:
            continue

        label_score = 3.0 if freq_label > 0 else 0.0
        title_score = min(3.0, 3.0 * freq_title / total_pages)
        ancestor_score = 1.5 if freq_ancestor > 0 else 0.0
        body_score = min(1.0, 1.0 * freq_body / total_pages)
        score = label_score + title_score + ancestor_score + body_score

        if score < MIN_SCORE_THRESHOLD:
            continue

        sources: List[str] = []
        if freq_label > 0:
            sources.append("label")
        if freq_title > 0:
            sources.append("title")
        if freq_ancestor > 0:
            sources.append("ancestor")
        if freq_body > 0:
            sources.append("body")

        candidates.append({
            "keyword": token,
            "score": round(score, 2),
            "sources": sources,
            "frequency": {
                "label": freq_label,
                "title": freq_title,
                "body": freq_body,
                "ancestor": freq_ancestor,
            },
            "sample_page_titles": find_sample_titles(token, pages),
        })

    candidates.sort(key=lambda c: c["score"], reverse=True)
    return candidates


def parse_original_terms(query: str) -> List[str]:
    return [term.strip().lower() for term in re.split(r"\s*\|\s*|,", query) if term.strip()]


def build_suggested_query(candidates: List[Dict[str, Any]], max_terms: int) -> str:
    top = candidates[:max_terms]
    return "|".join(c["keyword"] for c in top)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="초기 Confluence 검색 결과에서 확장 키워드 후보를 추출합니다.",
    )
    parser.add_argument(
        "--input",
        required=True,
        help="초기 fetch 결과 JSON 파일 경로입니다.",
    )
    parser.add_argument(
        "--original-query",
        required=True,
        help="초기 검색에 사용한 원본 쿼리입니다.",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="키워드 확장 매니페스트 JSON 출력 경로입니다.",
    )
    parser.add_argument(
        "--max-candidates",
        type=int,
        default=20,
        help="출력할 최대 후보 키워드 수입니다. (기본값: 20)",
    )
    parser.add_argument(
        "--min-frequency",
        type=int,
        default=2,
        help="후보에 포함되려면 필요한 최소 출현 횟수입니다. (기본값: 2)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    pages = data.get("pages", [])
    original_terms = parse_original_terms(args.original_query)

    candidates = score_candidates(pages, original_terms, args.min_frequency)
    candidates = candidates[: args.max_candidates]

    suggested_query = build_suggested_query(candidates, MAX_SUGGESTED_TERMS)

    warnings: List[str] = []
    if not candidates:
        warnings.append("키워드 확장 후보가 발견되지 않았습니다.")

    result = {
        "meta": {
            "generated_at": iso_now(),
            "original_query": args.original_query,
            "source_fetch": os.path.abspath(args.input),
            "page_count_analyzed": len(pages),
            "candidate_count": len(candidates),
        },
        "original_terms": original_terms,
        "candidates": candidates,
        "suggested_query": suggested_query,
        "warnings": warnings,
    }

    out_dir = os.path.dirname(args.output)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"키워드 확장 완료: {len(candidates)}개 후보 발견 → {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
