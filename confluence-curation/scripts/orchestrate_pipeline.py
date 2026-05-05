#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from data_store import write_json
from feedback_store import (
    FeedbackUploadError,
    append_feedback_record,
    build_feedback_record,
    collect_feedback_from_cli,
    create_github_feedback_issue,
    default_feedback_output,
    github_upload_config_from_env,
    github_upload_requested_from_env,
    new_run_id,
    summarize_artifact_counts,
)
from pipeline_registry import (
    default_method_for_purpose,
    load_stage_registry,
    method_by_id,
    stage_by_id,
)


STAGE_LABELS = {
    "stage0_pre_analysis": "pre_analysis",
    "stage1_extract": "extract",
    "stage2_cluster": "cluster",
    "stage3_analyze": "analyze",
    "stage4_synthesize": "synthesize",
    "stage5_validate": "validate",
}


def iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Confluence staged pipeline orchestrator with per-stage method selection."
    )
    parser.add_argument("--output-dir", required=True, help="Pipeline 산출물을 저장할 디렉터리")
    parser.add_argument(
        "--purpose",
        default="general",
        choices=["general", "change-tracking", "onboarding"],
        help="기본 목적 프로필",
    )
    parser.add_argument(
        "--fetch-input",
        action="append",
        dest="fetch_inputs",
        help="기존 fetch 또는 merge 결과 JSON 경로. 여러 번 지정 가능",
    )
    parser.add_argument(
        "--expansion-input",
        help="pre-analysis expand 단계에서 live fetch 대신 사용할 expansion artifact 경로",
    )
    parser.add_argument("--followup-question", action="append", dest="followup_questions")
    parser.add_argument("--non-interactive", action="store_true", help="질문 없이 default method 사용")
    parser.add_argument("--pre-analysis-method")
    parser.add_argument("--extract-method")
    parser.add_argument("--cluster-method")
    parser.add_argument("--analyze-method")
    parser.add_argument("--synthesize-method")
    parser.add_argument("--validate-method")
    parser.add_argument("--base-url")
    parser.add_argument(
        "--deployment-type",
        default="auto",
        choices=["auto", "cloud", "server", "datacenter"],
    )
    parser.add_argument("--email")
    parser.add_argument("--username")
    parser.add_argument("--api-token")
    parser.add_argument("--password")
    parser.add_argument("--space-key")
    parser.add_argument("--root-page-id")
    parser.add_argument("--all-spaces", action="store_true")
    parser.add_argument("--query")
    parser.add_argument("--label")
    parser.add_argument("--days", type=int)
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--include-body", action="store_true")
    parser.add_argument("--insecure", action="store_true")
    parser.add_argument("--cache-dir")
    parser.add_argument("--data-dir")
    parser.add_argument("--cache-ttl-hours", type=int)
    parser.add_argument("--refresh-cache", action="store_true")
    parser.add_argument("--cache-only", action="store_true")
    parser.add_argument("--rate-limit-rps", type=float)
    parser.add_argument("--report-output")
    parser.add_argument("--summary-output")
    parser.add_argument("--brief-output")
    parser.add_argument("--brief-markdown-output")
    parser.add_argument(
        "--feedback-output",
        help="피드백 JSONL append 저장 경로. 기본값은 <output-dir>/feedback/feedback.jsonl",
    )
    parser.add_argument("--no-feedback", action="store_true", help="완료 후 피드백 질문 생략")
    parser.add_argument(
        "--feedback-prompt",
        action="store_true",
        help="TTY가 아니어도 완료 후 피드백 질문을 표시합니다. --non-interactive 에서는 무시됩니다.",
    )
    return parser.parse_args()


def stage_method_overrides(args: argparse.Namespace) -> Dict[str, Optional[str]]:
    return {
        "stage0_pre_analysis": args.pre_analysis_method,
        "stage1_extract": args.extract_method,
        "stage2_cluster": args.cluster_method,
        "stage3_analyze": args.analyze_method,
        "stage4_synthesize": args.synthesize_method,
        "stage5_validate": args.validate_method,
    }


def prompt_for_method(stage: Dict[str, Any], purpose: str, default_method: str) -> str:
    methods = stage.get("methods", [])
    print("")
    print(f"[{stage.get('label')}] {stage.get('selection_prompt')}")
    for index, method in enumerate(methods, start=1):
        marker = " (default)" if method.get("id") == default_method else ""
        print(f"  {index}. {method.get('label')} [{method.get('id')}] - {method.get('description')}{marker}")

    while True:
        response = input(f"{stage.get('label')} method 선택 [{default_method}]: ").strip()
        if not response:
            return default_method
        if response.isdigit():
            selected_index = int(response)
            if 1 <= selected_index <= len(methods):
                return methods[selected_index - 1]["id"]
        for method in methods:
            if response == method.get("id"):
                return response
        print(f"유효하지 않은 선택입니다. 목적={purpose}, 기본값={default_method}")


def resolve_stage_methods(args: argparse.Namespace, registry: Dict[str, Any]) -> Dict[str, str]:
    interactive = (not args.non_interactive) and sys.stdin.isatty()
    resolved: Dict[str, str] = {}

    for stage in registry.get("stages", []):
        stage_id = stage["id"]
        explicit = stage_method_overrides(args).get(stage_id)
        if explicit:
            method_by_id(stage, explicit)
            resolved[stage_id] = explicit
            continue

        default_method = default_method_for_purpose(stage, args.purpose)
        resolved[stage_id] = (
            prompt_for_method(stage, args.purpose, default_method)
            if interactive
            else default_method
        )
    return resolved


def artifact_paths(args: argparse.Namespace) -> Dict[str, str]:
    output_dir = os.path.abspath(args.output_dir)
    report_output = os.path.abspath(args.report_output) if args.report_output else os.path.join(output_dir, "report.md")
    summary_output = os.path.abspath(args.summary_output) if args.summary_output else os.path.join(output_dir, "summary.json")
    brief_output = os.path.abspath(args.brief_output) if args.brief_output else os.path.join(output_dir, "brief.json")
    brief_markdown_output = (
        os.path.abspath(args.brief_markdown_output)
        if args.brief_markdown_output
        else os.path.join(output_dir, "brief.md")
    )
    return {
        "output_dir": output_dir,
        "source_fetch": os.path.join(output_dir, "source-fetch.json"),
        "merged": os.path.join(output_dir, "merged.json"),
        "preferred_spaces": os.path.join(output_dir, "preferred-spaces.json"),
        "expanded": os.path.join(output_dir, "merged-expanded.json"),
        "normalized": os.path.join(output_dir, "normalized.json"),
        "clusters": os.path.join(output_dir, "clusters.json"),
        "evidence_dir": os.path.join(output_dir, "evidence"),
        "evidence_manifest": os.path.join(output_dir, "evidence-manifest.json"),
        "insights": os.path.join(output_dir, "insights.json"),
        "review": os.path.join(output_dir, "review.json"),
        "report": report_output,
        "summary": summary_output,
        "brief": brief_output,
        "brief_markdown": brief_markdown_output,
        "pipeline_plan": os.path.join(output_dir, "pipeline_plan.json"),
        "pipeline_result": os.path.join(output_dir, "pipeline_result.json"),
        "followup_dir": os.path.join(output_dir, "followups"),
    }


def ensure_parent(path: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)


def run_step(command: List[str], root: Path) -> None:
    subprocess.run(command, cwd=root, check=True)


def read_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def read_json_if_exists(path: str) -> Optional[Dict[str, Any]]:
    if not os.path.exists(path):
        return None
    return read_json(path)


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9가-힣]+", "-", value.lower()).strip("-")
    return slug or "question"


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


def build_plan(
    args: argparse.Namespace,
    registry: Dict[str, Any],
    selected_methods: Dict[str, str],
    artifacts: Dict[str, str],
    source_inputs: List[str],
    run_id: str,
) -> Dict[str, Any]:
    stages: List[Dict[str, Any]] = []
    for stage in registry.get("stages", []):
        method = method_by_id(stage, selected_methods[stage["id"]])
        stages.append(
            {
                "id": stage["id"],
                "label": stage["label"],
                "stage_key": STAGE_LABELS[stage["id"]],
                "method_id": method["id"],
                "method_label": method["label"],
                "runner_kind": method["runner_kind"],
                "status": "pending",
            }
        )
    return {
        "meta": {
            "run_id": run_id,
            "generated_at": iso_now(),
            "source_type": "pipeline_plan",
            "purpose": args.purpose,
            "output_dir": artifacts["output_dir"],
            "registry_version": registry.get("version"),
            "interactive": (not args.non_interactive) and sys.stdin.isatty(),
        },
        "source_inputs": source_inputs,
        "selected_methods": {
            "stage0_pre_analysis": selected_methods["stage0_pre_analysis"],
            "stage1_extract": selected_methods["stage1_extract"],
            "stage2_cluster": selected_methods["stage2_cluster"],
            "stage3_analyze": selected_methods["stage3_analyze"],
            "stage4_synthesize": selected_methods["stage4_synthesize"],
            "stage5_validate": selected_methods["stage5_validate"],
        },
        "artifacts": artifacts,
        "followup_questions": args.followup_questions or [],
        "stages": stages,
    }


def should_prompt_for_feedback(args: argparse.Namespace) -> bool:
    if args.no_feedback or args.non_interactive:
        return False
    return args.feedback_prompt or sys.stdin.isatty()


def record_feedback_if_requested(
    args: argparse.Namespace,
    artifacts: Dict[str, str],
    selected_methods: Dict[str, str],
    run_id: str,
) -> Dict[str, Any]:
    feedback_output = (
        os.path.abspath(args.feedback_output)
        if args.feedback_output
        else default_feedback_output(artifacts["output_dir"])
    )
    requested = should_prompt_for_feedback(args)
    status: Dict[str, Any] = {
        "feedback_requested": requested,
        "feedback_recorded": False,
        "feedback_output": feedback_output if requested else None,
        "feedback_upload_requested": False,
        "feedback_uploaded": False,
        "feedback_upload_target": None,
        "feedback_issue_url": None,
        "feedback_upload_error": None,
    }
    if not requested:
        return status

    responses = collect_feedback_from_cli()
    if responses is None:
        return status

    summary_counts = summarize_artifact_counts(
        read_json_if_exists(artifacts["expanded"]),
        read_json_if_exists(artifacts["insights"]),
        read_json_if_exists(artifacts["review"]),
    )
    record = build_feedback_record(
        run_id=run_id,
        purpose=args.purpose,
        selected_methods=selected_methods,
        artifacts=artifacts,
        responses=responses,
        summary_counts=summary_counts,
    )
    append_feedback_record(feedback_output, record)
    status["feedback_recorded"] = True
    status["feedback_output"] = feedback_output
    print(f"피드백이 저장되었습니다: {feedback_output}")

    status["feedback_upload_requested"] = github_upload_requested_from_env()
    try:
        upload_config = github_upload_config_from_env()
    except FeedbackUploadError as exc:
        status["feedback_upload_error"] = str(exc)
        print(f"피드백 GitHub Issue 업로드 설정 오류: {exc}")
        return status

    if not upload_config:
        return status

    status["feedback_upload_target"] = upload_config["repo"]
    try:
        upload_result = create_github_feedback_issue(record, upload_config)
    except FeedbackUploadError as exc:
        status["feedback_upload_error"] = str(exc)
        print(f"피드백 GitHub Issue 업로드 실패: {exc}")
        return status

    status["feedback_uploaded"] = True
    status["feedback_issue_url"] = upload_result["issue_url"]
    print(f"피드백 GitHub Issue가 생성되었습니다: {upload_result['issue_url']}")
    return status


def update_stage_status(plan: Dict[str, Any], stage_id: str, status: str) -> None:
    for stage in plan.get("stages", []):
        if stage.get("id") == stage_id:
            stage["status"] = status
            stage["updated_at"] = iso_now()
            return


def build_fetch_command(args: argparse.Namespace, output_path: str) -> List[str]:
    command = [sys.executable, "confluence-curation/scripts/fetch_confluence.py", "--output", output_path]
    if args.base_url:
        command.extend(["--base-url", args.base_url])
    if args.deployment_type:
        command.extend(["--deployment-type", args.deployment_type])
    if args.email:
        command.extend(["--email", args.email])
    if args.username:
        command.extend(["--username", args.username])
    if args.api_token:
        command.extend(["--api-token", args.api_token])
    if args.password:
        command.extend(["--password", args.password])
    if args.space_key:
        command.extend(["--space-key", args.space_key])
    if args.root_page_id:
        command.extend(["--root-page-id", args.root_page_id])
    if args.all_spaces:
        command.append("--all-spaces")
    if args.query:
        command.extend(["--query", args.query])
    if args.label:
        command.extend(["--label", args.label])
    if args.days is not None:
        command.extend(["--days", str(args.days)])
    if args.limit is not None:
        command.extend(["--limit", str(args.limit)])
    if args.include_body:
        command.append("--include-body")
    if args.insecure:
        command.append("--insecure")
    if args.cache_dir:
        command.extend(["--cache-dir", args.cache_dir])
    if args.data_dir:
        command.extend(["--data-dir", args.data_dir])
    if args.cache_ttl_hours is not None:
        command.extend(["--cache-ttl-hours", str(args.cache_ttl_hours)])
    if args.refresh_cache:
        command.append("--refresh-cache")
    if args.cache_only:
        command.append("--cache-only")
    if args.rate_limit_rps is not None:
        command.extend(["--rate-limit-rps", str(args.rate_limit_rps)])
    return command


def materialize_source_fetch(args: argparse.Namespace, artifacts: Dict[str, str], root: Path) -> List[str]:
    source_inputs = [os.path.abspath(path) for path in (args.fetch_inputs or [])]
    if source_inputs:
        return source_inputs

    ensure_parent(artifacts["source_fetch"])
    run_step(build_fetch_command(args, artifacts["source_fetch"]), root)
    return [artifacts["source_fetch"]]


def merge_inputs(source_inputs: List[str], merged_path: str, root: Path) -> None:
    ensure_parent(merged_path)
    if len(source_inputs) == 1:
        shutil.copyfile(source_inputs[0], merged_path)
        return
    run_step(
        [
            sys.executable,
            "confluence-curation/scripts/merge_fetched.py",
            "--inputs",
            *source_inputs,
            "--output",
            merged_path,
        ],
        root,
    )


def run_pre_analysis(
    args: argparse.Namespace,
    method: str,
    artifacts: Dict[str, str],
    root: Path,
) -> str:
    ensure_parent(artifacts["preferred_spaces"])
    ensure_parent(artifacts["expanded"])

    if method == "disabled":
        shutil.copyfile(artifacts["merged"], artifacts["expanded"])
        return artifacts["expanded"]

    run_step(
        [
            sys.executable,
            "confluence-curation/scripts/infer_preferred_spaces.py",
            "--input",
            artifacts["merged"],
            "--output",
            artifacts["preferred_spaces"],
        ],
        root,
    )

    if method == "infer-only":
        shutil.copyfile(artifacts["merged"], artifacts["expanded"])
        return artifacts["expanded"]

    inference = read_json(artifacts["preferred_spaces"])
    preferred_spaces = inference.get("preferred_spaces", [])
    if not preferred_spaces:
        shutil.copyfile(artifacts["merged"], artifacts["expanded"])
        return artifacts["expanded"]

    if args.expansion_input:
        expansion_payload = read_json(os.path.abspath(args.expansion_input))
    else:
        expansion_output = os.path.join(artifacts["output_dir"], "preferred-space-expanded.json")
        command = [
            sys.executable,
            "confluence-curation/scripts/expand_preferred_space.py",
            "--input",
            artifacts["merged"],
            "--output",
            expansion_output,
            "--data-dir",
            args.data_dir or os.path.join(artifacts["output_dir"], "data"),
        ]
        for space in preferred_spaces:
            command.extend(["--preferred-space", space])
        if args.include_body:
            command.append("--include-body")
        if args.base_url:
            command.extend(["--base-url", args.base_url])
        if args.deployment_type:
            command.extend(["--deployment-type", args.deployment_type])
        if args.email:
            command.extend(["--email", args.email])
        if args.username:
            command.extend(["--username", args.username])
        if args.api_token:
            command.extend(["--api-token", args.api_token])
        if args.password:
            command.extend(["--password", args.password])
        if args.cache_dir:
            command.extend(["--cache-dir", args.cache_dir])
        if args.cache_ttl_hours is not None:
            command.extend(["--cache-ttl-hours", str(args.cache_ttl_hours)])
        if args.refresh_cache:
            command.append("--refresh-cache")
        if args.cache_only:
            command.append("--cache-only")
        if args.rate_limit_rps is not None:
            command.extend(["--rate-limit-rps", str(args.rate_limit_rps)])
        if args.insecure:
            command.append("--insecure")
        run_step(command, root)
        expansion_payload = read_json(expansion_output)

    merged_payload = read_json(artifacts["merged"])
    write_json(artifacts["expanded"], merge_expansion_payload(merged_payload, expansion_payload))
    return artifacts["expanded"]


def normalize_with_method(method: str, input_path: str, output_path: str, root: Path) -> None:
    command = [
        sys.executable,
        "confluence-curation/scripts/normalize_confluence.py",
        "--input",
        input_path,
        "--output",
        output_path,
    ]
    if method == "dense-extract":
        command.extend(["--max-sentences", "18", "--max-keywords", "18", "--min-sentence-length", "12"])
    run_step(command, root)


def render_outputs(
    args: argparse.Namespace,
    artifacts: Dict[str, str],
    root: Path,
    pre_analysis_used: bool,
) -> None:
    curate_command = [
        sys.executable,
        "confluence-curation/scripts/curate_confluence.py",
        "--input",
        artifacts["expanded"],
        "--insights-input",
        artifacts["insights"],
        "--review-input",
        artifacts["review"],
        "--output",
        artifacts["report"],
        "--emit-json-summary",
        artifacts["summary"],
        "--purpose",
        args.purpose,
        "--data-dir",
        args.data_dir or os.path.join(artifacts["output_dir"], "data"),
    ]
    if pre_analysis_used and os.path.exists(artifacts["preferred_spaces"]):
        curate_command.extend(["--preferred-space-inference-input", artifacts["preferred_spaces"]])
    run_step(curate_command, root)

    brief_command = [
        sys.executable,
        "confluence-curation/scripts/render_insight_brief.py",
        "--fetch-input",
        artifacts["expanded"],
        "--insights-input",
        artifacts["insights"],
        "--review-input",
        artifacts["review"],
        "--summary-input",
        artifacts["summary"],
        "--output",
        artifacts["brief"],
        "--markdown-output",
        artifacts["brief_markdown"],
    ]
    if pre_analysis_used and os.path.exists(artifacts["preferred_spaces"]):
        brief_command.extend(["--preferred-space-inference-input", artifacts["preferred_spaces"]])
    run_step(brief_command, root)

    os.makedirs(artifacts["followup_dir"], exist_ok=True)
    for index, question in enumerate(args.followup_questions or [], start=1):
        followup_output = os.path.join(
            artifacts["followup_dir"],
            f"{index:02d}-{slugify(question)}.json",
        )
        run_step(
            [
                sys.executable,
                "confluence-curation/scripts/answer_followup.py",
                "--insights-input",
                artifacts["insights"],
                "--review-input",
                artifacts["review"],
                "--normalized-input",
                artifacts["normalized"],
                "--question",
                question,
                "--output",
                followup_output,
            ],
            root,
        )


def main() -> int:
    args = parse_args()
    root = repo_root()
    run_id = new_run_id()
    registry = load_stage_registry()
    selected_methods = resolve_stage_methods(args, registry)
    artifacts = artifact_paths(args)
    os.makedirs(artifacts["output_dir"], exist_ok=True)

    source_inputs = materialize_source_fetch(args, artifacts, root)
    plan = build_plan(args, registry, selected_methods, artifacts, source_inputs, run_id)
    write_json(artifacts["pipeline_plan"], plan)

    merge_inputs(source_inputs, artifacts["merged"], root)

    try:
        update_stage_status(plan, "stage0_pre_analysis", "in_progress")
        write_json(artifacts["pipeline_plan"], plan)
        stage0_output = run_pre_analysis(args, selected_methods["stage0_pre_analysis"], artifacts, root)
        update_stage_status(plan, "stage0_pre_analysis", "completed")
        write_json(artifacts["pipeline_plan"], plan)

        update_stage_status(plan, "stage1_extract", "in_progress")
        write_json(artifacts["pipeline_plan"], plan)
        normalize_with_method(selected_methods["stage1_extract"], stage0_output, artifacts["normalized"], root)
        update_stage_status(plan, "stage1_extract", "completed")
        write_json(artifacts["pipeline_plan"], plan)

        update_stage_status(plan, "stage2_cluster", "in_progress")
        write_json(artifacts["pipeline_plan"], plan)
        run_step(
            [
                sys.executable,
                "confluence-curation/scripts/cluster_confluence.py",
                "--input",
                artifacts["normalized"],
                "--output",
                artifacts["clusters"],
                "--strategy",
                selected_methods["stage2_cluster"],
                "--data-dir",
                args.data_dir or os.path.join(artifacts["output_dir"], "data"),
            ],
            root,
        )
        update_stage_status(plan, "stage2_cluster", "completed")
        write_json(artifacts["pipeline_plan"], plan)

        update_stage_status(plan, "stage3_analyze", "in_progress")
        write_json(artifacts["pipeline_plan"], plan)
        run_step(
            [
                sys.executable,
                "confluence-curation/scripts/extract_evidence.py",
                "--normalized-input",
                artifacts["normalized"],
                "--clusters-input",
                artifacts["clusters"],
                "--output-dir",
                artifacts["evidence_dir"],
                "--emit-manifest",
                artifacts["evidence_manifest"],
                "--strategy",
                selected_methods["stage3_analyze"],
            ],
            root,
        )
        update_stage_status(plan, "stage3_analyze", "completed")
        write_json(artifacts["pipeline_plan"], plan)

        update_stage_status(plan, "stage4_synthesize", "in_progress")
        write_json(artifacts["pipeline_plan"], plan)
        run_step(
            [
                sys.executable,
                "confluence-curation/scripts/synthesize_insights.py",
                "--manifest",
                artifacts["evidence_manifest"],
                "--output",
                artifacts["insights"],
                "--purpose",
                args.purpose,
                "--strategy",
                selected_methods["stage4_synthesize"],
            ],
            root,
        )
        update_stage_status(plan, "stage4_synthesize", "completed")
        write_json(artifacts["pipeline_plan"], plan)

        update_stage_status(plan, "stage5_validate", "in_progress")
        write_json(artifacts["pipeline_plan"], plan)
        run_step(
            [
                sys.executable,
                "confluence-curation/scripts/review_insights.py",
                "--input",
                artifacts["insights"],
                "--output",
                artifacts["review"],
                "--purpose",
                args.purpose,
                "--strategy",
                selected_methods["stage5_validate"],
            ],
            root,
        )
        update_stage_status(plan, "stage5_validate", "completed")
        write_json(artifacts["pipeline_plan"], plan)

        render_outputs(
            args,
            artifacts,
            root,
            selected_methods["stage0_pre_analysis"] != "disabled",
        )
    except subprocess.CalledProcessError as exc:
        plan["meta"]["failed_at"] = iso_now()
        plan["meta"]["failure"] = {
            "returncode": exc.returncode,
            "command": exc.cmd,
        }
        write_json(artifacts["pipeline_plan"], plan)
        raise

    result = {
        "meta": {
            "run_id": run_id,
            "generated_at": iso_now(),
            "source_type": "orchestrate_pipeline",
            "purpose": args.purpose,
            "output_dir": artifacts["output_dir"],
        },
        "selected_methods": plan["selected_methods"],
        "artifacts": artifacts,
        "followup_outputs": sorted(
            os.path.join(artifacts["followup_dir"], name)
            for name in os.listdir(artifacts["followup_dir"])
        )
        if os.path.isdir(artifacts["followup_dir"])
        else [],
    }
    result.update(record_feedback_if_requested(args, artifacts, plan["selected_methods"], run_id))
    write_json(artifacts["pipeline_result"], result)
    print(f"Confluence pipeline orchestration completed: {artifacts['pipeline_result']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
