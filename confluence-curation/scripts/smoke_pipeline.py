#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List


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
            "## 주제별 인사이트",
            "결론:",
            "확신도:",
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


def assert_feature_artifacts(workdir: Path) -> None:
    required = [
        workdir / "features" / "cluster-confluence" / "latest.json",
        workdir / "features" / "curation-scoring" / "latest.json",
    ]
    for path in required:
        assert_file_exists(path)


def main() -> int:
    args = parse_args()
    root = repo_root()
    fixture = (root / args.fixture).resolve()
    workdir = (root / args.workdir).resolve()

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
        [python, "confluence-curation/scripts/normalize_confluence.py", "--input", str(workdir / "merged.json"), "--output", str(workdir / "normalized.json")],
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
            str(workdir / "merged.json"),
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

    for name in [
        "merged.json",
        "normalized.json",
        "clusters.json",
        "evidence-manifest.json",
        "insights.json",
        "review.json",
        "report.md",
        "summary.json",
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
