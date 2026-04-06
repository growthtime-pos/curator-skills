#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="로컬 fixture 로 단계형 Confluence 인사이트 파이프라인을 점검합니다.")
    parser.add_argument(
        "--fixture",
        default="confluence-curation/fixtures/pipeline_fixture.json",
        help="스모크 테스트에 사용할 fixture JSON 경로입니다.",
    )
    parser.add_argument(
        "--workdir",
        default="data/smoke-pipeline",
        help="스모크 테스트 산출물을 저장할 디렉터리입니다.",
    )
    parser.add_argument(
        "--keep-artifacts",
        action="store_true",
        help="성공 후에도 생성된 산출물을 유지합니다.",
    )
    return parser.parse_args()


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def run_step(command: List[str], root: Path) -> None:
    subprocess.run(command, cwd=root, check=True)


def read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def assert_file_exists(path: Path) -> None:
    if not path.exists():
        raise RuntimeError(f"필수 산출물이 생성되지 않았습니다: {path}")


def assert_report_contents(report_path: Path, purpose: str = "general") -> None:
    text = report_path.read_text(encoding="utf-8")
    if purpose == "change-tracking":
        required_fragments = [
            "## 트렌드 신호",
            "## 변경 타임라인",
            "## 변경 주체 분석",
            "결론:",
        ]
    elif purpose == "onboarding":
        required_fragments = [
            "## 추천 읽기 순서",
            "## 핵심 내용 정리",
            "## 문서 맵",
            "결론:",
        ]
    else:
        required_fragments = [
            "## 지금 주목해야 할 주제",
            "## 우선 읽을 문서",
            "## 주제별 인사이트",
            "결론:",
            "확신도:",
            "권장 후속 조치:",
        ]
    for fragment in required_fragments:
        if fragment not in text:
            raise RuntimeError(f"최종 리포트에 필요한 문구가 없습니다 (purpose={purpose}): {fragment}")


def assert_merge_shape(workdir: Path) -> None:
    merged = read_json(workdir / "merged.json")
    meta = merged.get("meta", {})
    if "rounds" not in meta:
        raise RuntimeError("병합 결과에 rounds 메타데이터가 없습니다.")
    if meta.get("total_pages_after_dedup", 0) < 1:
        raise RuntimeError("병합 후 페이지가 없습니다.")
    pages = merged.get("pages", [])
    page_ids = [p.get("page_id") for p in pages]
    if len(page_ids) != len(set(page_ids)):
        raise RuntimeError("병합 결과에 중복 페이지가 존재합니다.")


def assert_artifact_shapes(workdir: Path) -> None:
    clusters = read_json(workdir / "clusters.json")
    insights = read_json(workdir / "insights.json")
    review = read_json(workdir / "review.json")
    brief = read_json(workdir / "brief.json")
    followup = read_json(workdir / "followup-action.json")

    if clusters.get("summary", {}).get("multi_page_cluster_count", 0) < 1:
        raise RuntimeError("다중 페이지 클러스터가 생성되지 않았습니다.")
    if not insights.get("insights"):
        raise RuntimeError("인사이트 결과가 비어 있습니다.")
    if not review.get("reviews"):
        raise RuntimeError("리뷰 결과가 비어 있습니다.")

    first_insight = insights["insights"][0]
    if "confidence_ko" not in first_insight:
        raise RuntimeError("인사이트 결과에 한글 확신도 필드가 없습니다.")

    first_review = review["reviews"][0]
    if "verdict_ko" not in first_review:
        raise RuntimeError("리뷰 결과에 한글 verdict 필드가 없습니다.")
    if not brief.get("attention_topics"):
        raise RuntimeError("브리핑 결과에 attention_topics 가 없습니다.")
    if not followup.get("best_explanation_ko"):
        raise RuntimeError("후속 질문 결과에 설명이 없습니다.")


def assert_feature_artifacts(workdir: Path) -> None:
    required = [
        workdir / "features" / "cluster-confluence" / "latest.json",
        workdir / "features" / "curation-scoring" / "latest.json",
    ]
    for path in required:
        assert_file_exists(path)


def merge_expansion_payload(payload: Dict[str, Any], expansion_payload: Dict[str, Any]) -> Dict[str, Any]:
    pages = list(payload.get("pages", []))
    people = list(payload.get("people", []))
    relationships = list(payload.get("relationships", []))
    warnings = list(payload.get("warnings", []))
    preferred_spaces = expansion_payload.get("preferred_spaces", [])

    page_ids = {page.get("page_id") for page in pages}
    person_ids = {person.get("account_id") for person in people if person}
    relationship_keys = {
        (rel.get("from_page_id"), rel.get("to_page_id"), rel.get("type"))
        for rel in relationships
    }

    for page in pages:
        page.setdefault("discovery_source", "query_seed")
        page.setdefault("discovery_reasons", ["키워드 검색 시드"])
        page.setdefault(
            "preferred_space_match",
            page.get("space_key") in preferred_spaces if preferred_spaces else False,
        )
        page.setdefault("preferred_space_boost", 8 if page.get("preferred_space_match") else 0)

    for page in expansion_payload.get("expanded_pages", []):
        page_id = page.get("page_id")
        if not page_id or page_id in page_ids:
            continue
        expanded_page = dict(page)
        expanded_page.setdefault("discovery_source", "preferred_space_expansion")
        expanded_page.setdefault("preferred_space_match", True)
        expanded_page.setdefault("preferred_space_boost", 8)
        pages.append(expanded_page)
        page_ids.add(page_id)

    for person in expansion_payload.get("people", []):
        account_id = person.get("account_id") if person else None
        if account_id and account_id not in person_ids:
            people.append(person)
            person_ids.add(account_id)

    for rel in expansion_payload.get("links", []):
        key = (rel.get("from_page_id"), rel.get("to_page_id"), rel.get("type"))
        if key not in relationship_keys:
            relationships.append(rel)
            relationship_keys.add(key)

    for warning in expansion_payload.get("warnings", []):
        if warning not in warnings:
            warnings.append(warning)

    merged = dict(payload)
    merged["pages"] = pages
    merged["people"] = people
    merged["relationships"] = relationships
    merged["warnings"] = warnings
    merged_meta = dict(payload.get("meta", {}))
    merged_meta["preferred_space_expansion"] = {
        "used": True,
        "artifact_schema_version": ((expansion_payload.get("meta") or {}).get("schema_version")),
        "expanded_page_count": len(expansion_payload.get("expanded_pages", [])),
    }
    scope = dict(merged_meta.get("scope", {}))
    scope["preferred_spaces"] = preferred_spaces
    scope["expanded_page_ids"] = [
        page.get("page_id")
        for page in expansion_payload.get("expanded_pages", [])
        if page.get("page_id")
    ]
    merged_meta["scope"] = scope
    merged["meta"] = merged_meta
    return merged


def main() -> int:
    args = parse_args()
    root = repo_root()
    fixture = (root / args.fixture).resolve()
    workdir = (root / args.workdir).resolve()
    expansion_fixture = (
        root / "confluence-curation/fixtures/preferred_space_expanded_fixture.json"
    ).resolve()

    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    evidence_dir = workdir / "evidence"

    python = sys.executable

    # -- merge step (self-merge to test dedup) --
    run_step(
        [
            python,
            "confluence-curation/scripts/merge_fetched.py",
            "--inputs",
            str(fixture),
            str(fixture),
            "--output",
            str(workdir / "merged.json"),
        ],
        root,
    )

    run_step(
        [
            python,
            "confluence-curation/scripts/infer_preferred_spaces.py",
            "--input",
            str(workdir / "merged.json"),
            "--output",
            str(workdir / "preferred-spaces.json"),
        ],
        root,
    )

    merged_payload = read_json(workdir / "merged.json")
    expansion_payload = read_json(expansion_fixture)
    merged_with_expansion = merge_expansion_payload(merged_payload, expansion_payload)
    with (workdir / "merged-expanded.json").open("w", encoding="utf-8") as handle:
        json.dump(merged_with_expansion, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    run_step(
        [python, "confluence-curation/scripts/normalize_confluence.py", "--input", str(workdir / "merged-expanded.json"), "--output", str(workdir / "normalized.json")],
        root,
    )
    run_step(
        [python, "confluence-curation/scripts/cluster_confluence.py", "--input", str(workdir / "normalized.json"), "--output", str(workdir / "clusters.json"), "--data-dir", str(workdir)],
        root,
    )
    run_step(
        [
            python,
            "confluence-curation/scripts/extract_evidence.py",
            "--normalized-input",
            str(workdir / "normalized.json"),
            "--clusters-input",
            str(workdir / "clusters.json"),
            "--output-dir",
            str(evidence_dir),
            "--emit-manifest",
            str(workdir / "evidence-manifest.json"),
        ],
        root,
    )
    run_step(
        [python, "confluence-curation/scripts/synthesize_insights.py", "--manifest", str(workdir / "evidence-manifest.json"), "--output", str(workdir / "insights.json")],
        root,
    )
    run_step(
        [python, "confluence-curation/scripts/review_insights.py", "--input", str(workdir / "insights.json"), "--output", str(workdir / "review.json")],
        root,
    )
    run_step(
        [
            python,
            "confluence-curation/scripts/curate_confluence.py",
            "--input",
            str(workdir / "merged-expanded.json"),
            "--preferred-space-inference-input",
            str(workdir / "preferred-spaces.json"),
            "--insights-input",
            str(workdir / "insights.json"),
            "--review-input",
            str(workdir / "review.json"),
            "--output",
            str(workdir / "report.md"),
            "--emit-json-summary",
            str(workdir / "summary.json"),
            "--data-dir",
            str(workdir),
        ],
        root,
    )
    run_step(
        [
            python,
            "confluence-curation/scripts/render_insight_brief.py",
            "--fetch-input",
            str(workdir / "merged-expanded.json"),
            "--insights-input",
            str(workdir / "insights.json"),
            "--review-input",
            str(workdir / "review.json"),
            "--summary-input",
            str(workdir / "summary.json"),
            "--preferred-space-inference-input",
            str(workdir / "preferred-spaces.json"),
            "--output",
            str(workdir / "brief.json"),
            "--markdown-output",
            str(workdir / "brief.md"),
        ],
        root,
    )
    run_step(
        [
            python,
            "confluence-curation/scripts/answer_followup.py",
            "--insights-input",
            str(workdir / "insights.json"),
            "--review-input",
            str(workdir / "review.json"),
            "--normalized-input",
            str(workdir / "normalized.json"),
            "--question",
            "최근 뭐가 바뀌었나",
            "--output",
            str(workdir / "followup-change.json"),
        ],
        root,
    )
    run_step(
        [
            python,
            "confluence-curation/scripts/answer_followup.py",
            "--insights-input",
            str(workdir / "insights.json"),
            "--review-input",
            str(workdir / "review.json"),
            "--normalized-input",
            str(workdir / "normalized.json"),
            "--question",
            "이 표현은 무슨 뜻인가",
            "--output",
            str(workdir / "followup-meaning.json"),
        ],
        root,
    )
    run_step(
        [
            python,
            "confluence-curation/scripts/answer_followup.py",
            "--insights-input",
            str(workdir / "insights.json"),
            "--review-input",
            str(workdir / "review.json"),
            "--normalized-input",
            str(workdir / "normalized.json"),
            "--question",
            "그래서 내가 뭘 해야 하나",
            "--output",
            str(workdir / "followup-action.json"),
        ],
        root,
    )

    for name in [
        "merged.json",
        "merged-expanded.json",
        "preferred-spaces.json",
        "normalized.json",
        "clusters.json",
        "evidence-manifest.json",
        "insights.json",
        "review.json",
        "report.md",
        "summary.json",
        "brief.json",
        "brief.md",
        "followup-change.json",
        "followup-meaning.json",
        "followup-action.json",
    ]:
        assert_file_exists(workdir / name)

    assert_merge_shape(workdir)
    assert_artifact_shapes(workdir)
    assert_feature_artifacts(workdir)
    assert_report_contents(workdir / "report.md", "general")

    # -- purpose-specific report tests --
    for purpose in ["change-tracking", "onboarding"]:
        purpose_report = workdir / f"report-{purpose}.md"
        purpose_insights = workdir / f"insights-{purpose}.json"
        purpose_review = workdir / f"review-{purpose}.json"
        run_step(
            [python, "confluence-curation/scripts/synthesize_insights.py",
             "--manifest", str(workdir / "evidence-manifest.json"),
             "--output", str(purpose_insights),
             "--purpose", purpose],
            root,
        )
        run_step(
            [python, "confluence-curation/scripts/review_insights.py",
             "--input", str(purpose_insights),
             "--output", str(purpose_review),
             "--purpose", purpose],
            root,
        )
        run_step(
            [python, "confluence-curation/scripts/curate_confluence.py",
             "--input", str(workdir / "merged.json"),
             "--insights-input", str(purpose_insights),
             "--review-input", str(purpose_review),
             "--output", str(purpose_report),
             "--purpose", purpose],
            root,
        )
        assert_file_exists(purpose_report)
        assert_report_contents(purpose_report, purpose)

    if not args.keep_artifacts:
        shutil.rmtree(workdir)

    print("Confluence 인사이트 파이프라인 스모크 테스트가 통과했습니다 (general + change-tracking + onboarding).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
