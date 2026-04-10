# Confluence Pipeline Stage Model

이 문서는 `confluence-curation` 을 stage-selectable pipeline 으로 운영할 때의 기준 모델을 설명한다.

## 목표

- stage 경계를 stable artifact 로 유지한다
- stage별 방법론 선택은 master orchestrator 가 담당한다
- 복잡한 stage만 별도 skill 로 승격한다
- deterministic tool stage 와 policy-heavy skill stage 를 섞어 쓴다

## Stage 정의

1. `stage0_pre_analysis`
   - raw fetch 결과를 보고 preferred space 추론, expansion 여부, 후속 분석 힌트를 결정
   - 기본 method: `infer-expand`

2. `stage1_extract`
   - raw fetch/merge 결과를 normalize schema 로 변환
   - 기본 method: `standard-extract`

3. `stage2_cluster`
   - normalized corpus 를 topic cluster 로 묶음
   - 기본 method: `heuristic-cluster`

4. `stage3_analyze`
   - cluster 를 evidence pack 으로 변환
   - 기본 method: `balanced-analysis`

5. `stage4_synthesize`
   - evidence pack 을 conclusion/action 으로 압축
   - 기본 method: `balanced-synthesis`
   - consultant-style method examples: `evidence-first-synthesis`, `pyramid-synthesis`, `hypothesis-driven-synthesis`

6. `stage5_validate`
   - synthesized insight 를 second-pass review
   - 기본 method: `balanced-validator`
   - validator 는 synthesized insight 안의 `reasoning_method` 에 따라 추가 shape 검증을 수행할 수 있다

## Registry

- stage와 method 목록은 [pipeline/stage_registry.json](../pipeline/stage_registry.json) 에 저장한다.
- orchestrator 는 이 registry 를 읽어 interactive selection 또는 default selection 을 수행한다.

## Master Entry Point

- CLI: `python3 confluence-curation/scripts/orchestrate_pipeline.py ...`
- skill package: `confluence-curation/extensions/pipeline-orchestrator/`

## Artifact Contract

권장 산출물:

```text
tmp/
  source-fetch.json
  merged.json
  preferred-spaces.json
  merged-expanded.json
  normalized.json
  clusters.json
  evidence/
  evidence-manifest.json
  insights.json
  review.json
  summary.json
  report.md
  brief.json
  brief.md
  pipeline_plan.json
  pipeline_result.json
```
