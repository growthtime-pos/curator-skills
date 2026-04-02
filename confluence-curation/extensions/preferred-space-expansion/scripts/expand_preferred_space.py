#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


DEFAULT_SCHEMA_VERSION = "1.0"
DEFAULT_THRESHOLD = 2.6
DEFAULT_HIERARCHY_THRESHOLD = 1.6
DEFAULT_EXPANSION_LIMIT = 50
MAX_KEYWORDS = 12
STOP_WORDS = {
    "the",
    "and",
    "for",
    "with",
    "this",
    "that",
    "from",
    "into",
    "guide",
    "page",
    "policy",
    "process",
    "using",
    "about",
    "prod",
    "ops",
}


def load_fetch_module() -> Any:
    script_path = Path(__file__).resolve().parents[3] / "scripts" / "fetch_confluence.py"
    spec = importlib.util.spec_from_file_location("fetch_confluence_shared", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"fetch_confluence.py 를 불러올 수 없습니다: {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


FETCH = load_fetch_module()


def load_data_store_module() -> Any:
    script_path = Path(__file__).resolve().parents[3] / "scripts" / "data_store.py"
    spec = importlib.util.spec_from_file_location("confluence_data_store_shared", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"data_store.py 를 불러올 수 없습니다: {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


DATA_STORE = load_data_store_module()


def iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def config_str(config: Dict[str, Any], key: str, env_key: Optional[str] = None) -> Optional[str]:
    if env_key:
        value = os.getenv(env_key)
        if value:
            return value
    return config.get(key)


def parse_args() -> argparse.Namespace:
    config_path = os.getenv("CONFLUENCE_CONFIG_PATH", FETCH.DEFAULT_CONFIG_PATH)
    config = FETCH.load_saved_config(config_path)

    parser = argparse.ArgumentParser(
        description="기존 Confluence 검색 결과를 바탕으로 선호 스페이스 내부의 연관 문서를 확장 탐색합니다."
    )
    parser.add_argument("--input", required=True, help="기존 fetch_confluence.py 출력 JSON 경로")
    parser.add_argument("--output", required=True)
    parser.add_argument("--preferred-space", action="append", dest="preferred_spaces", required=True)
    parser.add_argument("--expansion-limit", type=int, default=DEFAULT_EXPANSION_LIMIT)
    parser.add_argument("--relatedness-threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--hierarchy-threshold", type=float, default=DEFAULT_HIERARCHY_THRESHOLD)
    parser.add_argument("--include-body", action="store_true", help="확장 후보 수집 시 body excerpt 도 함께 가져옵니다.")
    parser.add_argument("--base-url", default=config_str(config, "base_url", "CONFLUENCE_BASE_URL"))
    parser.add_argument(
        "--deployment-type",
        default=os.getenv("CONFLUENCE_DEPLOYMENT_TYPE") or config.get("deployment_type", "auto"),
        choices=["auto", "cloud", "server", "datacenter"],
    )
    parser.add_argument("--email", default=config_str(config, "email", "CONFLUENCE_EMAIL"))
    parser.add_argument("--username", default=config_str(config, "username", "CONFLUENCE_USERNAME"))
    parser.add_argument("--api-token", default=config_str(config, "api_token", "CONFLUENCE_API_TOKEN"))
    parser.add_argument("--password", default=config_str(config, "password", "CONFLUENCE_PASSWORD"))
    parser.add_argument(
        "--cache-dir",
        default=os.getenv("CONFLUENCE_CACHE_DIR") or config.get("cache_dir", os.path.expanduser("~/.confluence-curation-cache")),
    )
    parser.add_argument(
        "--data-dir",
        default=os.getenv("CONFLUENCE_DATA_DIR") or DATA_STORE.default_data_dir(),
    )
    parser.add_argument(
        "--cache-ttl-hours",
        type=int,
        default=int(os.getenv("CONFLUENCE_CACHE_TTL_HOURS") or config.get("cache_ttl_hours", 24)),
    )
    parser.add_argument("--refresh-cache", action="store_true")
    parser.add_argument("--cache-only", action="store_true")
    parser.add_argument(
        "--rate-limit-rps",
        type=float,
        default=float(os.getenv("CONFLUENCE_RATE_LIMIT_RPS") or config.get("rate_limit_rps", 1.0)),
    )
    insecure_default = config.get("insecure", False)
    parser.add_argument("--insecure", action="store_true", default=insecure_default)
    args = parser.parse_args()

    args._config_path = config_path
    args._config_used = bool(config)
    if args.rate_limit_rps <= 0 or args.rate_limit_rps > FETCH.MAX_RPS:
        parser.error("--rate-limit-rps must be > 0 and <= 1.0")
    return args


def tokenize(text: str) -> List[str]:
    return re.findall(r"[a-z0-9가-힣]{3,}", (text or "").lower())


def extract_keywords(title: str, body_excerpt: str, max_keywords: int = MAX_KEYWORDS) -> List[str]:
    counts: Counter[str] = Counter()
    for token in tokenize(" ".join([title or "", body_excerpt or ""])):
        if token in STOP_WORDS:
            continue
        counts[token] += 1
    return [token for token, _ in counts.most_common(max_keywords)]


def page_keywords(page: Dict[str, Any]) -> Set[str]:
    return set(extract_keywords(page.get("title", ""), page.get("body_excerpt", "")))


def ancestor_ids(page: Dict[str, Any]) -> Set[str]:
    return {str(item.get("page_id")) for item in page.get("ancestors", []) if item.get("page_id")}


def score_candidate(seed: Dict[str, Any], candidate: Dict[str, Any]) -> Tuple[float, List[str], bool]:
    reasons: List[str] = []
    score = 0.0

    title_similarity = FETCH.similarity(seed.get("title", ""), candidate.get("title", ""))
    if title_similarity >= 0.9:
        score += 2.6
        reasons.append(f"제목 유사도 높음 ({title_similarity:.2f})")
    elif title_similarity >= 0.82:
        score += 2.2
        reasons.append(f"제목 유사도 있음 ({title_similarity:.2f})")
    elif title_similarity >= 0.7:
        score += 1.4
        reasons.append(f"제목 일부 유사 ({title_similarity:.2f})")

    shared_keywords = sorted(page_keywords(seed) & page_keywords(candidate))
    if len(shared_keywords) >= 4:
        score += 1.8
        reasons.append(f"키워드 겹침 강함 ({', '.join(shared_keywords[:4])})")
    elif len(shared_keywords) >= 2:
        score += 1.2
        reasons.append(f"키워드 겹침 ({', '.join(shared_keywords[:3])})")
    elif len(shared_keywords) == 1:
        score += 0.5
        reasons.append(f"단일 키워드 연결 ({shared_keywords[0]})")

    seed_ancestors = ancestor_ids(seed)
    candidate_ancestors = ancestor_ids(candidate)
    direct_hierarchy = False
    if candidate.get("page_id") in seed_ancestors or seed.get("page_id") in candidate_ancestors:
        score += 2.0
        direct_hierarchy = True
        reasons.append("직접 상하위 계층 관계")
    else:
        shared_ancestors = seed_ancestors & candidate_ancestors
        if shared_ancestors:
            score += 1.3
            reasons.append("공통 상위 구조 안에 위치")

    return score, reasons, direct_hierarchy


def choose_matches(
    seeds: List[Dict[str, Any]],
    candidates: List[Dict[str, Any]],
    threshold: float,
    hierarchy_threshold: float,
) -> List[Dict[str, Any]]:
    seed_ids = {page.get("page_id") for page in seeds}
    kept: List[Dict[str, Any]] = []

    for candidate in candidates:
        if candidate.get("page_id") in seed_ids:
            continue
        best_score = 0.0
        best_reasons: List[str] = []
        best_seed_ids: List[str] = []
        best_direct_hierarchy = False

        for seed in seeds:
            score, reasons, direct_hierarchy = score_candidate(seed, candidate)
            if score > best_score:
                best_score = score
                best_reasons = reasons
                best_seed_ids = [seed["page_id"]]
                best_direct_hierarchy = direct_hierarchy
            elif score and abs(score - best_score) < 0.01:
                best_seed_ids.append(seed["page_id"])
                for reason in reasons:
                    if reason not in best_reasons:
                        best_reasons.append(reason)
                best_direct_hierarchy = best_direct_hierarchy or direct_hierarchy

        required_threshold = hierarchy_threshold if best_direct_hierarchy else threshold
        if best_score < required_threshold:
            continue

        kept.append(
            {
                **candidate,
                "related_seed_page_ids": best_seed_ids,
                "relatedness_score": round(best_score, 2),
                "discovery_reasons": best_reasons,
                "preferred_space_match": True,
                "preferred_space_boost": 8,
            }
        )

    kept.sort(key=lambda item: (item["relatedness_score"], item.get("updated_at") or ""), reverse=True)
    return kept


def dedupe_pages(pages: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    deduped: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for page in pages:
        page_id = str(page.get("page_id"))
        if not page_id or page_id in seen:
            continue
        seen.add(page_id)
        deduped.append(page)
    return deduped


def build_fetch_args(args: argparse.Namespace, space_key: str, include_body: bool) -> argparse.Namespace:
    namespace = argparse.Namespace(
        base_url=args.base_url,
        deployment_type=args.deployment_type,
        email=args.email,
        username=args.username,
        api_token=args.api_token,
        password=args.password,
        space_key=space_key,
        root_page_id=None,
        all_spaces=False,
        query=None,
        label=None,
        days=None,
        limit=args.expansion_limit,
        include_body=include_body,
        insecure=args.insecure,
        cache_dir=args.cache_dir,
        cache_ttl_hours=args.cache_ttl_hours,
        refresh_cache=args.refresh_cache,
        cache_only=args.cache_only,
        rate_limit_rps=args.rate_limit_rps,
        output=args.output,
    )
    return namespace


def fetch_space_pages(
    args: argparse.Namespace,
    preferred_spaces: List[str],
    include_body: bool,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
    warnings: List[str] = []
    limiter = FETCH.RateLimiter(args.rate_limit_rps)
    deployment_type = FETCH.detect_deployment_type(args.base_url, args.deployment_type)
    auth = FETCH.maybe_retry_with_password(args, deployment_type, limiter, warnings)
    client = FETCH.ConfluenceClient(args.base_url, auth, limiter, warnings, insecure=args.insecure)

    expanded_pages: List[Dict[str, Any]] = []
    contributor_ids: List[str] = []
    combined_for_links: List[Dict[str, Any]] = []

    for space in preferred_spaces:
        fetch_args = build_fetch_args(args, space, include_body)
        raw_pages = FETCH.fetch_page_batch(client, fetch_args)
        normalized_pages, ids = FETCH.normalize_pages(raw_pages, client, fetch_args, warnings)
        expanded_pages.extend(normalized_pages)
        combined_for_links.extend(normalized_pages)
        contributor_ids.extend(ids)

    people: List[Dict[str, Any]] = []
    seen_people: Set[str] = set()
    for account_id in contributor_ids:
        if account_id in seen_people:
            continue
        seen_people.add(account_id)
        person = FETCH.fetch_person(client, deployment_type, account_id, warnings)
        if person:
            people.append(person)

    links = FETCH.build_relationships(dedupe_pages(combined_for_links))
    FETCH.estimate_runtime_warning(client.request_count, args.rate_limit_rps, warnings)
    return dedupe_pages(expanded_pages), people, links, warnings


def merge_link_sets(seed_payload: Dict[str, Any], expansion_pages: List[Dict[str, Any]], expansion_links: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    combined_pages = dedupe_pages(list(seed_payload.get("pages", [])) + expansion_pages)
    combined_links = FETCH.build_relationships(combined_pages)
    existing = {
        (item.get("from_page_id"), item.get("to_page_id"), item.get("type"))
        for item in seed_payload.get("relationships", [])
    }
    merged: List[Dict[str, Any]] = []
    for item in combined_links + expansion_links:
        key = (item.get("from_page_id"), item.get("to_page_id"), item.get("type"))
        if key in existing:
            continue
        existing.add(key)
        merged.append(item)
    return merged


def main() -> int:
    args = parse_args()
    seed_payload = load_json(args.input)
    meta = seed_payload.get("meta", {})
    if not args.base_url:
        args.base_url = meta.get("base_url")
    if not args.base_url:
        raise FETCH.FetchError("--base-url 또는 seed artifact 의 meta.base_url 이 필요합니다.")

    include_body = args.include_body or bool(meta.get("include_body"))
    preferred_spaces = list(dict.fromkeys(args.preferred_spaces or []))
    seed_pages = list(seed_payload.get("pages", []))

    fetched_pages, people, links, warnings = fetch_space_pages(args, preferred_spaces, include_body)
    matched_pages = choose_matches(
        seed_pages,
        fetched_pages,
        args.relatedness_threshold,
        args.hierarchy_threshold,
    )
    merged_links = merge_link_sets(seed_payload, matched_pages, links)

    artifact = {
        "meta": {
            "schema_version": DEFAULT_SCHEMA_VERSION,
            "generated_at": iso_now(),
            "source_fetch_path": os.path.abspath(args.input),
            "base_url": args.base_url.rstrip("/"),
            "include_body": include_body,
            "expansion_limit": args.expansion_limit,
            "relatedness_threshold": args.relatedness_threshold,
            "hierarchy_threshold": args.hierarchy_threshold,
        },
        "preferred_spaces": preferred_spaces,
        "seed_page_ids": [page.get("page_id") for page in seed_pages if page.get("page_id")],
        "expanded_pages": matched_pages,
        "people": people,
        "links": merged_links,
        "warnings": warnings,
    }

    feature_paths = DATA_STORE.persist_feature_state(
        args.data_dir,
        "preferred-space-expansion",
        {
            "meta": {
                "generated_at": artifact["meta"]["generated_at"],
                "source_fetch_path": os.path.abspath(args.input),
            },
            "weights": {
                "preferred_space_boost": 8,
                "relatedness_threshold": args.relatedness_threshold,
                "hierarchy_threshold": args.hierarchy_threshold,
                "expansion_limit": args.expansion_limit,
            },
            "preferred_spaces": preferred_spaces,
            "seed_page_ids": artifact["seed_page_ids"],
            "expanded_page_count": len(matched_pages),
            "output_path": os.path.abspath(args.output),
        },
        generated_at=artifact["meta"]["generated_at"],
    )
    artifact["meta"]["data_artifacts"] = {
        "feature_latest_path": feature_paths["latest_path"],
        "feature_history_path": feature_paths["history_path"],
    }

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(artifact, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except FETCH.FetchError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
