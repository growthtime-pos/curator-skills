---
name: pipeline-orchestrator
description: Orchestrate the Confluence curation pipeline by asking for stage-specific methods, writing a pipeline plan artifact, and executing each stage runner in order.
---

# Confluence Pipeline Orchestrator

## Use When

- 사용자가 stage별 방법론을 고르고 싶을 때
- `pre_analysis / extract / cluster / analyze / synthesize / validate` 를 하나의 흐름으로 실행하고 싶을 때
- intermediate artifact 와 final report 를 함께 남기고 싶을 때

## Workflow

1. 목적(`general`, `change-tracking`, `onboarding`)을 정한다.
2. stage registry 를 읽고 stage별 recommended method 를 제시한다.
3. 사용자 선택 또는 default selection 으로 `pipeline_plan.json` 을 만든다.
4. `scripts/orchestrate_pipeline.py` 로 pipeline 을 실행한다.
5. interactive 실행이면 완료 후 내장 4문항 피드백 프롬프트를 진행하고 저장된 JSONL 경로를 확인한다. `--non-interactive` 또는 `--no-feedback` 실행이면 생략한다.
6. 최종 `report.md`, `brief.json`, `pipeline_result.json` 을 확인한다.

## Important Rules

- 모든 stage 를 독립 skill 로 만들지 않는다.
- `extract`, `analyze` 는 우선 tool runner 로 유지한다.
- `pre_analysis`, `cluster`, `synthesize`, `validate` 는 method 교체 가치가 큰 skill stage 로 취급한다.
- 실패 시 어느 stage artifact 에서 멈췄는지 명시한다.
- `pipeline_result.json` 에는 피드백 답변 본문을 넣지 않고 `feedback_requested`, `feedback_recorded`, `feedback_output` 만 확인한다.
