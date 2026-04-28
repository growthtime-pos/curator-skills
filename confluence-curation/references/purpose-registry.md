# 큐레이션 목적 레지스트리

## 사용 가능한 목적

| ID | 한글 라벨 | 설명 | 대표 트리거 문구 |
|---|---|---|---|
| `general` | 일반 큐레이션 | 기존 6섹션 구조 (기본값) | 명시적 목적 없을 때 |
| `change-tracking` | 변경 추적 | 변경 타임라인 + 트렌드 감지 | "최근 변경", "트렌드", "활동 증가", "새로 생긴" |
| `onboarding` | 온보딩 | 읽기 순서 + 핵심 요약 + 배경 문맥 | "처음", "정리해줘", "어디서부터", "온보딩" |

## 에이전트 자동 추론 절차

1. 사용자 쿼리에서 위 트리거 문구와 매칭
2. 매칭 확신이 높으면 추론된 목적을 명시하고 바로 진행
3. 매칭이 애매하면 사용자에게 목적을 확인
4. 매칭 없으면 `general`로 진행

## CLI 플래그

파이프라인 스크립트에 `--purpose` 플래그로 전달:

```bash
python3 scripts/synthesize_insights.py --manifest /tmp/manifest.json --output /tmp/insights.json --purpose change-tracking
python3 scripts/review_insights.py --input /tmp/insights.json --output /tmp/review.json --purpose change-tracking
python3 scripts/curate_confluence.py --input /tmp/merged.json --output /tmp/report.md --purpose change-tracking
```

## 참조 파일

- 공통 규칙: [purposes/_base.md](purposes/_base.md)
- 변경 추적: [purposes/change-tracking.md](purposes/change-tracking.md)
- 온보딩: [purposes/onboarding.md](purposes/onboarding.md)
- 일반 (기본값): [output-template.md](output-template.md)
