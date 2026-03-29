# Staged Insight Pipeline Release Notes

## 목적

이 문서는 개발자가 현재 `confluence-curation` 패키지가 어떤 방식으로 동작하는지 빠르게 이해할 수 있도록 정리한 릴리즈 노트 성격의 문서다.

이번 변경의 핵심은 기존의 단일 `fetch -> curate` 흐름을 유지하면서, 그 위에 단계형 인사이트 파이프라인을 추가한 것이다.

이제 시스템은 단순히 "어떤 문서가 최신인가"만 보는 것이 아니라, 다음 질문까지 다룰 수 있다.

- 어떤 페이지들이 같은 주제를 다루는가
- 현재 작업 기준 문서는 무엇인가
- 배경 참고 문서는 무엇인가
- 충돌, 중복, 오래된 문서는 무엇인가
- 어떤 후속 조치가 필요한가

## 이번 릴리즈에서 추가된 구성

- `scripts/normalize_confluence.py`
- `scripts/cluster_confluence.py`
- `scripts/extract_evidence.py`
- `scripts/synthesize_insights.py`
- `scripts/review_insights.py`
- `scripts/smoke_pipeline.py`
- `fixtures/pipeline_fixture.json`

기존 `scripts/curate_confluence.py` 는 유지되며, 이제 선택적으로 `--insights-input`, `--review-input` 을 받아 topic-level 결과를 함께 렌더링한다.

## 전체 동작 흐름

### 1. Fetch

입력:
- Confluence API

출력:
- raw fetch JSON

역할:
- 페이지 메타데이터 수집
- 버전 이력 일부 수집
- body excerpt 수집
- 사람/프로필 힌트 수집
- 관계 정보 수집

주의:
- 이 단계만 네트워크에 의존한다.
- 이후 단계는 모두 오프라인 artifact 처리다.

### 2. Normalize

스크립트:
- `confluence-curation/scripts/normalize_confluence.py`

입력:
- `fetch_confluence.py` 의 raw JSON

출력:
- `normalized.json`

역할:
- 페이지 shape 정규화
- sentence 분리
- keyword 추출
- claim candidate 추출
- maintainer signal 요약
- missing signal 기록

의도:
- 이후 단계가 fetch payload의 원시 구조에 직접 의존하지 않도록 중간 schema를 고정한다.

### 3. Cluster

스크립트:
- `confluence-curation/scripts/cluster_confluence.py`

입력:
- `normalized.json`

출력:
- `clusters.json`

사용 신호:
- title similarity
- shared keywords
- shared contributors
- shared labels
- shared ancestors
- explicit relationships

역할:
- 관련 페이지를 topic cluster로 묶는다.
- 각 cluster에 `likely_current_page_id`, `likely_background_page_id`, confidence를 부여한다.

현재 구현 메모:
- singleton도 cluster로 유지한다.
- background page 선택 로직은 current page와 동일한 최신 문서로 치우치지 않도록 보정되어 있다.

### 4. Evidence Extraction

스크립트:
- `confluence-curation/scripts/extract_evidence.py`

입력:
- `normalized.json`
- `clusters.json`

출력:
- `evidence/topic_<id>.json`
- `evidence-manifest.json`

역할:
- cluster별 evidence pack 생성
- 현재 후보, 신뢰 후보, 오래된 후보 식별
- maintainer signals 집계
- 최근 변경 요약 생성
- conflict notes 생성
- missing signals 유지

현재 구현 메모:
- manifest의 `output_path` 는 절대경로로 저장된다.
- 따라서 synthesis 단계는 실행 위치가 달라도 동일하게 동작한다.

### 5. Insight Synthesis

스크립트:
- `confluence-curation/scripts/synthesize_insights.py`

입력:
- `evidence-manifest.json`

출력:
- `insights.json`

역할:
- topic별 conclusion 생성
- current/background/stale reference 정리
- recent change summary 정리
- evidence gaps 정리
- suggested actions 생성
- confidence 산출

현재 구현 메모:
- 시스템이 생성하는 문장은 한국어로 출력된다.
- confidence는 `confidence` 와 `confidence_ko` 를 함께 가진다.

### 6. Review Pass

스크립트:
- `confluence-curation/scripts/review_insights.py`

입력:
- `insights.json`

출력:
- `review.json`

review lenses:
- freshness
- trust
- contradiction
- executive

역할:
- 1차 synthesis가 과감하거나 과신하지 않았는지 재검토한다.
- verdict를 `approved`, `review`, `revise` 로 분류한다.
- confidence를 재보정한다.

현재 구현 메모:
- reviewer/severity/verdict에 대해 `_ko` 필드도 함께 저장한다.
- 경고가 많다고 무조건 confidence가 급락하지 않도록 감점 폭을 완화했다.

### 7. Final Report Rendering

스크립트:
- `confluence-curation/scripts/curate_confluence.py`

입력:
- fetch JSON
- optional `insights.json`
- optional `review.json`

출력:
- Markdown report
- optional JSON summary

역할:
- 기존 page-level curation 결과 유지
- `## 주제별 인사이트` 섹션 추가
- review 결과를 반영해 확신도와 검토 메모를 표시

현재 구현 메모:
- 기존 사용자와의 호환성을 위해 `--insights-input`, `--review-input` 이 없으면 legacy flow처럼 동작한다.

## 산출물 구조

권장 artifact layout:

```text
tmp/
  confluence.json
  normalized.json
  clusters.json
  evidence/
    topic_001.json
    singleton_102.json
  evidence-manifest.json
  insights.json
  review.json
  confluence-report.md
  confluence-summary.json
```

## 최종 사용 방식

### legacy flow

```bash
python confluence-curation/scripts/fetch_confluence.py --space-key ENG --output tmp/confluence.json
python confluence-curation/scripts/curate_confluence.py --input tmp/confluence.json --output tmp/report.md
```

### staged insight flow

```bash
python confluence-curation/scripts/fetch_confluence.py --space-key ENG --include-body --output tmp/confluence.json
python confluence-curation/scripts/normalize_confluence.py --input tmp/confluence.json --output tmp/normalized.json
python confluence-curation/scripts/cluster_confluence.py --input tmp/normalized.json --output tmp/clusters.json
python confluence-curation/scripts/extract_evidence.py --normalized-input tmp/normalized.json --clusters-input tmp/clusters.json --output-dir tmp/evidence --emit-manifest tmp/evidence-manifest.json
python confluence-curation/scripts/synthesize_insights.py --manifest tmp/evidence-manifest.json --output tmp/insights.json
python confluence-curation/scripts/review_insights.py --input tmp/insights.json --output tmp/review.json
python confluence-curation/scripts/curate_confluence.py --input tmp/confluence.json --insights-input tmp/insights.json --review-input tmp/review.json --output tmp/report.md --emit-json-summary tmp/summary.json
```

## 검증 전략

이번 릴리즈 기준으로 가장 빠른 회귀 검증은 다음 두 가지다.

- 문법 검증
  - `python -m py_compile confluence-curation/scripts/*.py`
- fixture 기반 스모크 테스트
  - `python confluence-curation/scripts/smoke_pipeline.py`

`smoke_pipeline.py` 는 아래를 검증한다.

- 전체 staged pipeline이 실행되는지
- 주요 artifact가 실제로 생성되는지
- `insights.json` 에 한글 confidence 필드가 있는지
- `review.json` 에 한글 verdict 필드가 있는지
- 최종 report에 `주제별 인사이트`, `결론`, `확신도`, `권장 후속 조치`가 있는지

## 현재 제약 사항

- 원본 Confluence 본문이 영어면 excerpt와 snippet은 그대로 영어일 수 있다.
- title, team, people name 같은 원문 데이터는 번역하지 않는다.
- heuristics는 explainable 하도록 단순하게 유지되어 있으며, semantic reasoning은 아직 보수적이다.
- review 단계는 현재 rule-based이며 LLM 기반 반박 패스는 아직 없다.

## 개발자가 알아야 할 운영 포인트

- `fetch_confluence.py` 만 네트워크 의존 단계다.
- 이후 스크립트는 artifact-first 방식으로 연결된다.
- artifact schema를 바꾸면 downstream 스크립트와 문서를 같이 업데이트해야 한다.
- user-facing 문구는 가능한 한 한국어를 유지해야 한다.
- generated `__pycache__` 는 커밋하지 않는다.

## 다음 확장 후보

- snippet의 선택적 한국어 번역 또는 요약
- fixture 추가와 smoke test 다양화
- report 템플릿의 topic insight section 고도화
- review pass의 정교화
- staged artifact schema 문서 별도 분리
