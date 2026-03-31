# Curator Skills

Confluence 문서를 수집하고 분석하여 최신성, 신뢰도, 주제별 인사이트를 한글로 정리하는 AI 에이전트 스킬 패키지입니다.

## 목적

조직의 Confluence에는 같은 주제에 대해 여러 문서가 존재하고, 어떤 문서가 최신이고 신뢰할 만한지 판단하기 어려운 경우가 많습니다. 이 스킬은 다음을 자동으로 분석합니다:

- 어떤 페이지가 가장 최신인지
- 어떤 페이지가 더 신뢰할 만한지
- 어떤 페이지가 오래되었거나 중복·대체되었는지
- 관련 문서들 사이에 충돌이나 공백이 있는지
- 주제별로 어떤 후속 조치가 필요한지

## 요구사항

- Python 3.x (외부 패키지 불필요, 표준 라이브러리만 사용)
- Confluence 접속 정보 (Cloud: email + API token / Server: username + password)

## 빠른 시작

### 1. 연결 설정

```bash
# Confluence Cloud
python3 confluence-curation/scripts/configure_confluence.py set \
  base_url=https://your-org.atlassian.net/wiki \
  email=you@example.com \
  api_token=YOUR_API_TOKEN

# Confluence Server / Data Center
python3 confluence-curation/scripts/configure_confluence.py set \
  base_url=https://wiki.your-org.com \
  deployment_type=server \
  username=your_id \
  password=your_password
```

설정은 `~/.confluence-curation.json`에 저장됩니다. 우선순위: CLI 플래그 > 환경변수 > 설정 파일

### 2. 기본 사용 (간단 큐레이션)

```bash
# 특정 스페이스에서 문서 수집
python3 confluence-curation/scripts/fetch_confluence.py \
  --space-key ENG --include-body --output /tmp/confluence.json

# 큐레이션 리포트 생성
python3 confluence-curation/scripts/curate_confluence.py \
  --input /tmp/confluence.json --output /tmp/report.md
```

### 3. 키워드 검색 + 확장 (넓은 범위 탐색)

```bash
# Round 1: 초기 검색
python3 confluence-curation/scripts/fetch_confluence.py \
  --query "deploy" --include-body --output /tmp/fetch-r1.json

# 관련 키워드 발견
python3 confluence-curation/scripts/expand_keywords.py \
  --input /tmp/fetch-r1.json --original-query "deploy" \
  --output /tmp/keyword-expansion.json

# Round 2: 승인된 키워드별 추가 검색
python3 confluence-curation/scripts/fetch_confluence.py \
  --query "rollback" --include-body --output /tmp/fetch-r2a.json
python3 confluence-curation/scripts/fetch_confluence.py \
  --query "release" --include-body --output /tmp/fetch-r2b.json

# 결과 병합
python3 confluence-curation/scripts/merge_fetched.py \
  --inputs /tmp/fetch-r1.json /tmp/fetch-r2a.json /tmp/fetch-r2b.json \
  --output /tmp/fetch-merged.json
```

### 4. 전체 인사이트 파이프라인

```bash
# 1. 데이터 수집 (위의 fetch 또는 fetch+expand+merge 결과 사용)
INPUT=/tmp/fetch-merged.json  # 또는 /tmp/confluence.json

# 2. 정규화
python3 confluence-curation/scripts/normalize_confluence.py \
  --input $INPUT --output /tmp/normalized.json

# 3. 클러스터링
python3 confluence-curation/scripts/cluster_confluence.py \
  --input /tmp/normalized.json --output /tmp/clusters.json

# 4. 근거 팩 생성
python3 confluence-curation/scripts/extract_evidence.py \
  --normalized-input /tmp/normalized.json \
  --clusters-input /tmp/clusters.json \
  --output-dir /tmp/evidence \
  --emit-manifest /tmp/evidence-manifest.json

# 5. 인사이트 합성
python3 confluence-curation/scripts/synthesize_insights.py \
  --manifest /tmp/evidence-manifest.json --output /tmp/insights.json

# 6. 2차 리뷰
python3 confluence-curation/scripts/review_insights.py \
  --input /tmp/insights.json --output /tmp/review.json

# 7. 최종 리포트
python3 confluence-curation/scripts/curate_confluence.py \
  --input $INPUT \
  --insights-input /tmp/insights.json \
  --review-input /tmp/review.json \
  --output /tmp/report.md \
  --emit-json-summary /tmp/summary.json
```

## 파이프라인 아키텍처

```
┌─────────────────────────────────────────────────────────┐
│                   키워드 확장 (선택)                       │
│                                                         │
│  fetch (R1) → expand_keywords → fetch (R2) → merge     │
└────────────────────────┬────────────────────────────────┘
                         │
                         ▼
                   fetch.json (또는 merged.json)
                         │
          ┌──────────────┼──────────────┐
          │              │              │
          ▼              │              │
     간단 큐레이션        │      전체 인사이트 파이프라인
          │              │              │
          ▼              │              ▼
     curate_confluence   │      normalize → cluster
          │              │              │
          ▼              │              ▼
      report.md          │      extract_evidence
                         │              │
                         │              ▼
                         │      synthesize_insights
                         │              │
                         │              ▼
                         │      review_insights
                         │              │
                         │              ▼
                         └──► curate_confluence (+ insights + review)
                                        │
                                        ▼
                                   report.md + summary.json
```

## 스크립트 목록

| 스크립트 | 역할 | 네트워크 |
|---------|------|---------|
| `configure_confluence.py` | 연결 정보 관리 | - |
| `fetch_confluence.py` | Confluence API에서 페이지 수집 | O |
| `expand_keywords.py` | 검색 결과에서 확장 키워드 후보 추출 | - |
| `merge_fetched.py` | 여러 fetch 결과를 병합·중복 제거 | - |
| `normalize_confluence.py` | 문장 분리, 키워드 추출, 클레임 식별 | - |
| `cluster_confluence.py` | 관련 페이지를 주제 그룹으로 묶기 | - |
| `extract_evidence.py` | 주제별 근거 팩 생성 | - |
| `synthesize_insights.py` | 주제별 인사이트 합성 | - |
| `review_insights.py` | 4개 관점 검증 (최신성, 신뢰도, 모순, 실행가능성) | - |
| `curate_confluence.py` | 최종 한글 리포트 생성 | - |
| `smoke_pipeline.py` | fixture 기반 회귀 테스트 | - |

## 프로젝트 구조

```
curator-skills/
├── README.md                          # 이 파일
├── AGENTS.md                          # 개발 규칙 및 코딩 표준
├── confluence-curation/
│   ├── SKILL.md                       # 스킬 계약 및 워크플로우 정의
│   ├── agents/
│   │   └── openai.yaml                # 에이전트 메타데이터
│   ├── scripts/                       # 실행 가능한 Python 스크립트
│   ├── fixtures/
│   │   └── pipeline_fixture.json      # 스모크 테스트용 샘플 데이터
│   └── references/                    # 설계 문서 (실행 코드 아님)
│       ├── scoring.md                 # 최신성·신뢰도 채점 기준
│       ├── insight-architecture.md    # 단계별 분석 아키텍처
│       ├── review-rubric.md           # 리뷰 검증 체크리스트
│       ├── output-template.md         # 한글 출력 포맷 기준
│       ├── implementation-roadmap.md  # 구현 로드맵
│       └── staged-pipeline-release-notes.md  # 릴리즈 노트
└── tmp/                               # 임시 산출물
```

## 검증

```bash
# 문법 검사
python3 -m compileall confluence-curation

# 전체 파이프라인 스모크 테스트
python3 confluence-curation/scripts/smoke_pipeline.py

# 개별 스크립트 CLI 확인
python3 confluence-curation/scripts/fetch_confluence.py --help
python3 confluence-curation/scripts/expand_keywords.py --help
python3 confluence-curation/scripts/merge_fetched.py --help
python3 confluence-curation/scripts/curate_confluence.py --help
```

## 핵심 설계 원칙

- **최신성 =/= 신뢰도**: 최근 문서가 자동으로 정답은 아님. 오래되어도 꾸준히 관리되는 문서가 더 신뢰할 수 있음
- **충돌은 숨기지 않음**: 근거가 상충하면 양쪽 모두 보여주고, 억지로 승자를 결정하지 않음
- **증거 기반**: 모든 인사이트는 구체적인 페이지와 근거 스니펫에 연결됨
- **직책은 힌트일 뿐**: 높은 직급이 곧 높은 신뢰도를 의미하지 않음
- **한글 우선 출력**: 사용자 대면 결과는 한글로 제공
- **외부 의존성 없음**: Python 표준 라이브러리만 사용

## 라이선스

Private repository.
