---
name: confluence-curation
description: Fetch Confluence pages and edit history, then curate which documents are most current, most trustworthy, and what insight clusters, conflicts, and action items emerge across related pages. Use when comparing overlapping Confluence docs, identifying likely source-of-truth candidates, ranking documents by freshness and trust signals, or synthesizing topic-level insights from Confluence history and profile context.
---

# Confluence Curation

## Overview

Use this skill to turn a messy set of Confluence pages into a readable curation and insight view.

The goal is not to declare one document as absolute truth.
The goal is to show:
- which pages look most current
- which pages look more trustworthy
- which pages appear stale, duplicated, or superseded
- how related pages changed over time
- which topic clusters have meaningful conflicts, gaps, or follow-up actions

This skill assumes Confluence often lacks reliable labels or formal approval state.
When that happens, use author and editor context as a heuristic, not as a hard rule.

## 연결 설정 (최초 1회)

연결 정보를 로컬에 저장해두면 매번 입력할 필요가 없습니다.

```bash
python3 confluence-curation/scripts/configure_confluence.py set \
  base_url=https://wiki.example.com \
  username=user1 \
  password=mypassword \
  insecure=true
```

설정 가능한 키: `base_url`, `deployment_type`, `email`, `username`, `api_token`, `password`, `insecure`, `cache_dir`, `cache_ttl_hours`, `rate_limit_rps`

설정 파일은 `~/.confluence-curation.json`에 저장되며, 환경변수나 CLI 플래그가 있으면 설정 파일보다 우선합니다. 우선순위: CLI 플래그 > 환경변수 > 설정 파일

```bash
# 현재 설정 확인
python3 confluence-curation/scripts/configure_confluence.py show

# 특정 키 삭제
python3 confluence-curation/scripts/configure_confluence.py delete password

# 설정 전체 삭제
python3 confluence-curation/scripts/configure_confluence.py clear
```

## Default Workflow

1. Define the scope first:
   - target space or all accessible spaces
   - seed page or page set
   - optional date window
2. Run `scripts/fetch_confluence.py` to collect page metadata, limited version history, body excerpts, and profile hints.
3. Read [references/scoring.md](references/scoring.md) if you need to tune trust or freshness interpretation.
4. Read [references/insight-architecture.md](references/insight-architecture.md) if you need the staged insight pipeline and artifact model.
5. Read [references/review-rubric.md](references/review-rubric.md) before writing executive conclusions or conflict-heavy summaries.
6. Read [references/implementation-roadmap.md](references/implementation-roadmap.md) when planning staged implementation work.
7. Run `scripts/curate_confluence.py` on the fetched JSON.
8. Use [references/output-template.md](references/output-template.md) to keep the output Korean and easy to scan.
9. Call out ambiguity explicitly instead of hiding it.

## Staged Insight Workflow

When the user wants more than page ranking, use a staged workflow inspired by artifact-first analysis systems.

1. Fetch and normalize raw Confluence data.
2. Cluster related pages into topic groups.
3. Build evidence packs for each topic:
   - current candidate page
   - trusted background page
   - conflicting claims or duplicate pages
   - recent changes and likely maintainers
4. Synthesize topic-level insights with explicit evidence.
5. Run a second-pass review over freshness, trust, contradiction, and actionability.
6. Produce a final Korean report with confidence and open questions.

Prefer saving intermediate artifacts instead of hiding all reasoning inside one final summary.

## Core Judgment Rules

- Do not rely on labels or approval metadata unless they clearly exist.
- Treat title, team, and role from Confluence profiles as hints.
- Higher title does not always mean higher correctness.
- A page maintained repeatedly by the relevant working team may be more trustworthy than a page touched once by a senior person.
- A recent page is not automatically the best source of truth.
- An older page may still be useful if it is heavily referenced and still maintained.
- If evidence conflicts, report the conflict directly.
- Every major insight should point back to specific pages and short evidence snippets.
- If a topic cannot be resolved confidently, produce the disagreement instead of forcing a winner.

## Operational Rules

- All API calls must stay at or below one request per second.
- Use token-based authentication first.
- For Confluence Cloud, do not fall back to password auth.
- For Server or Data Center, try token-based auth first and only then fall back to username/password.
- Reuse cached profile results for the same person within one fetch run.
- Prefer metadata and relationship signals before pulling full body content.
- Use `--all-spaces` when the user wants cross-space search instead of a single space.
- Use `--include-body` when the user wants the skill to organize the content itself, not only metadata.
- Use `--cache-dir` to persist fetched results locally and reuse them later.
- Use `--cache-only` to work from saved data without making new API calls.
- Use `--refresh-cache` when the saved data should be ignored and fetched again.
- Keep fetched artifacts, normalized artifacts, and final reports separate so later passes can reuse them.

## Output Requirements

Always produce:
- a short Korean summary of the current best candidates
- a Korean synthesis of the underlying content when body text is available
- a section showing the most trustworthy data cleaned up into readable bullets
- a topic-level insight section with conflicts, gaps, or action items when enough evidence exists
- a table of candidate pages
- a timeline or ordered change flow
- explicit warning flags
- a final recommendation with uncertainty noted

When the user asks for deeper insight analysis, also produce:
- topic clusters or comparable document groups
- evidence-backed conflict notes
- likely owner or maintainer signals
- suggested next actions for cleanup, migration, or verification

## Keyword Expansion Workflow

When the user's initial query may not cover all relevant pages, use iterative keyword expansion to broaden search coverage.

1. Run an initial fetch with the user's query.
2. Run `scripts/expand_keywords.py` on the initial results to discover related keywords from labels, titles, ancestor pages, and body text.
3. Present the discovered keyword candidates to the user for approval.
4. Run a second fetch with the approved expanded keywords.
5. Run `scripts/merge_fetched.py` to combine and deduplicate both rounds of results.
6. Continue with the normal staged pipeline using the merged output.

Bounds:
- Limit to at most 2 search rounds (original + 1 expansion).
- The suggested query contains at most 5 expanded terms.
- Merge output is capped at 500 pages by default.

Example keyword expansion flow:
```bash
# Round 1: initial search
python3 confluence-curation/scripts/fetch_confluence.py --query "deploy" --include-body --output /tmp/fetch-r1.json

# Discover expanded keywords
python3 confluence-curation/scripts/expand_keywords.py --input /tmp/fetch-r1.json --original-query "deploy" --output /tmp/keyword-expansion.json

# (Agent reads suggested_terms and presents candidates to user for approval)

# Round 2: one fetch per approved keyword
python3 confluence-curation/scripts/fetch_confluence.py --query "rollback" --include-body --output /tmp/fetch-r2a.json
python3 confluence-curation/scripts/fetch_confluence.py --query "release" --include-body --output /tmp/fetch-r2b.json

# Merge all rounds
python3 confluence-curation/scripts/merge_fetched.py --inputs /tmp/fetch-r1.json /tmp/fetch-r2a.json /tmp/fetch-r2b.json --output /tmp/fetch-merged.json

# Continue pipeline with merged output
python3 confluence-curation/scripts/normalize_confluence.py --input /tmp/fetch-merged.json --output /tmp/normalized.json
```

## Example Invocations

- `python3 confluence-curation/scripts/fetch_confluence.py --space-key ENG --output /tmp/confluence.json`
- `python3 confluence-curation/scripts/fetch_confluence.py --all-spaces --query "인공지능" --include-body --cache-dir ~/.confluence-curation-cache --output /tmp/confluence-ai.json`
- `python3 confluence-curation/scripts/fetch_confluence.py --all-spaces --query "인공지능" --include-body --cache-dir ~/.confluence-curation-cache --cache-only --output /tmp/confluence-ai.json`
- `python3 confluence-curation/scripts/curate_confluence.py --input /tmp/confluence.json --output /tmp/confluence.md`
- `Use $confluence-curation to compare overlapping architecture pages and explain which page should be treated as the current working reference.`

## End-To-End Insight Pipeline Example

Use the staged pipeline when you want topic-level insight instead of only page ranking.

1. Fetch raw data:
   - `python3 confluence-curation/scripts/fetch_confluence.py --space-key ENG --include-body --output /tmp/confluence.json`
2. Normalize the fetched corpus:
   - `python3 confluence-curation/scripts/normalize_confluence.py --input /tmp/confluence.json --output /tmp/normalized.json`
3. Cluster related pages into topics:
   - `python3 confluence-curation/scripts/cluster_confluence.py --input /tmp/normalized.json --output /tmp/clusters.json`
4. Build evidence packs:
   - `python3 confluence-curation/scripts/extract_evidence.py --normalized-input /tmp/normalized.json --clusters-input /tmp/clusters.json --output-dir /tmp/evidence --emit-manifest /tmp/evidence-manifest.json`
5. Synthesize topic insights:
   - `python3 confluence-curation/scripts/synthesize_insights.py --manifest /tmp/evidence-manifest.json --output /tmp/insights.json`
6. Run the second-pass review:
   - `python3 confluence-curation/scripts/review_insights.py --input /tmp/insights.json --output /tmp/review.json`
7. Render the final Markdown report:
   - `python3 confluence-curation/scripts/curate_confluence.py --input /tmp/confluence.json --insights-input /tmp/insights.json --review-input /tmp/review.json --output /tmp/confluence-report.md --emit-json-summary /tmp/confluence-summary.json`
8. Run the fixture-based smoke test when changing the staged pipeline:
   - `python3 confluence-curation/scripts/smoke_pipeline.py`

Recommended artifact layout:
- `/tmp/confluence.json` (or `/tmp/fetch-r1.json`, `/tmp/fetch-r2.json`, `/tmp/fetch-merged.json` when using keyword expansion)
- `/tmp/keyword-expansion.json` (when using keyword expansion)
- `/tmp/normalized.json`
- `/tmp/clusters.json`
- `/tmp/evidence/`
- `/tmp/evidence-manifest.json`
- `/tmp/insights.json`
- `/tmp/review.json`
- `/tmp/confluence-report.md`

## Exit Criteria

Before finishing:
- confirm the scope of pages reviewed
- confirm what signals were available
- separate freshness from trust
- separate page-level evidence from topic-level insight
- state uncertainty clearly
- avoid claiming a definitive source of truth unless the evidence is strong
