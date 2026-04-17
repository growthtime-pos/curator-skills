---
name: confluence-curation
description: Fetch Confluence pages and edit history, then curate which documents are most current, most trustworthy, and what insight clusters, conflicts, and action items emerge across related pages. Use when comparing overlapping Confluence docs, identifying likely source-of-truth candidates, ranking documents by freshness and trust signals, or synthesizing topic-level insights from Confluence history and profile context.
---

# Confluence Curation

## Overview

Use this skill to turn a messy set of Confluence pages into a readable curation and insight view.
The intended user experience is not only search and ranking.
It should also help the user understand recent 흐름, what people are implicitly paying attention to, what remains confusing, and what to do next.

When internal preferred spaces look strong, run the built-in `scripts/expand_preferred_space.py` step and merge its JSON artifact into the final curation flow.

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
공식 저장 경로는 `~/.config/confluence-curation/config.json` 입니다.
기존 `~/.confluence-curation.json` 은 fallback 으로만 읽습니다.
`references/` 폴더는 운영 문서용이며 실제 credential 값을 넣는 위치가 아닙니다.

```bash
python3 confluence-curation/scripts/configure_confluence.py set \
  base_url=https://wiki.example.com \
  username=user1 \
  password=mypassword \
  insecure=true
```

설정 가능한 키: `base_url`, `deployment_type`, `email`, `username`, `api_token`, `password`, `insecure`, `cache_dir`, `cache_ttl_hours`, `rate_limit_rps`

활성 설정 확인은 항상 아래 명령으로 시작합니다.
새 세션에서는 fetch 전에 이 상태를 먼저 확인하고, `config_found=true` 이고 `missing_required_fields` 가 비어 있으면 credential 을 다시 묻지 않습니다.

```bash
python3 confluence-curation/scripts/configure_confluence.py status --json
```

우선순위: CLI 플래그 > 환경변수 > `CONFLUENCE_CONFIG_PATH` > `~/.config/confluence-curation/config.json` > `~/.confluence-curation.json`

```bash
# 현재 설정 확인
python3 confluence-curation/scripts/configure_confluence.py show

# fetch 가 실제로 사용할 활성 설정 확인
python3 confluence-curation/scripts/configure_confluence.py status --json

# 특정 키 삭제
python3 confluence-curation/scripts/configure_confluence.py delete password

# 설정 전체 삭제
python3 confluence-curation/scripts/configure_confluence.py clear
```

## Default Workflow

1. Run `python3 confluence-curation/scripts/configure_confluence.py status --json`.
2. If `config_found=true` and `missing_required_fields` is empty, reuse the saved connection immediately.
3. If the saved config is missing or incomplete, ask only for the missing fields and write them with `configure_confluence.py set`.
4. Read [references/connection-bootstrap.md](references/connection-bootstrap.md) if you need the credential bootstrap contract.
5. Define the scope:
   - target space or all accessible spaces
   - seed page or page set
   - optional date window
6. Determine the curation purpose. Infer from the user's query using trigger phrases in [references/purpose-registry.md](references/purpose-registry.md). If confident, state the inferred purpose and proceed. If ambiguous, ask the user. Default to `general` if no clear match. Available purposes: `general`, `change-tracking`, `onboarding`.
7. Run `scripts/fetch_confluence.py` to collect page metadata, limited version history, body excerpts, and profile hints.
8. Infer internal preferred spaces from the first fetch result by running `scripts/infer_preferred_spaces.py`.
9. If preferred spaces were inferred, automatically run `scripts/expand_preferred_space.py` to fetch related pages from those spaces and merge them into the main flow. Do not ask the user to enumerate spaces manually unless the workflow is blocked.
10. **Keyword expansion (mandatory):** Analyze the fetch results and derive expansion keywords following the procedure in the "Keyword Expansion" section below. Present candidates to the user for approval, then run a second fetch with approved keywords and merge results using `scripts/merge_fetched.py`.
11. Read [references/scoring.md](references/scoring.md) if you need to tune trust or freshness interpretation.
12. Read [references/insight-architecture.md](references/insight-architecture.md) if you need the staged insight pipeline and artifact model.
13. Read [references/review-rubric.md](references/review-rubric.md) before writing executive conclusions or conflict-heavy summaries.
14. Read [references/implementation-roadmap.md](references/implementation-roadmap.md) when planning staged implementation work.
15. If the user wants per-stage method selection, run `scripts/orchestrate_pipeline.py` and let it choose methods for `pre_analysis / extract / cluster / analyze / synthesize / validate`, then persist `pipeline_plan.json`.
16. Build graph artifacts from the normalized corpus with `scripts/graphify_confluence.py` so later stages can use graph communities, bridge pages, and suggested questions.
17. Otherwise run `scripts/curate_confluence.py --purpose {purpose}` on the merged JSON, plus the optional preferred-space expansion artifact and preferred-space inference artifact when present. Pass the purpose determined in step 6.
18. Run `scripts/render_insight_brief.py` when the user wants a briefing-style first response.
19. Run `scripts/answer_followup.py` when the user asks a follow-up question about meaning, changes, or next actions.
20. Use the appropriate purpose template from [references/purpose-registry.md](references/purpose-registry.md) to keep the output Korean and easy to scan. For `general` purpose, use [references/output-template.md](references/output-template.md).
21. Call out ambiguity explicitly instead of hiding it.

## Staged Insight Workflow

When the user wants more than page ranking, use a staged workflow inspired by artifact-first analysis systems.

1. Fetch raw Confluence data.
2. Infer internal preferred spaces from the first-pass result.
3. If strong candidates exist, expand related pages from those spaces.
4. **Keyword expansion (mandatory):** Follow the procedure in the "Keyword Expansion" section below, then merge results.
5. Determine the curation purpose (same as Default Workflow step 6).
6. Normalize the merged data.
7. Build graph artifacts from the normalized corpus.
8. Cluster related pages into topic groups.
9. Build evidence packs for each topic:
   - current candidate page
   - trusted background page
   - conflicting claims or duplicate pages
   - recent changes and likely maintainers
   - graph communities and bridge pages when available
10. Synthesize topic-level insights with explicit evidence: `scripts/synthesize_insights.py --purpose {purpose}`
11. Run a second-pass review over freshness, trust, contradiction, and actionability: `scripts/review_insights.py --purpose {purpose}`
12. Produce a final Korean report with confidence and open questions: `scripts/curate_confluence.py --purpose {purpose}`
13. When needed, generate a separate briefing artifact and use saved artifacts to answer follow-up questions.

Prefer saving intermediate artifacts instead of hiding all reasoning inside one final summary.

## Stage-Selectable Pipeline

When the user wants stage-by-stage method choice, use the master orchestrator instead of hand-wiring every script.

Stage model:

1. `stage0_pre_analysis`
2. `stage1_extract`
3. `stage1_graphify`
4. `stage2_cluster`
5. `stage3_analyze`
6. `stage4_synthesize`
7. `stage5_validate`

Rules:

- treat `extract` and `analyze` as tool-first stages
- treat `pre_analysis`, `cluster`, `synthesize`, and `validate` as method-selectable stages
- keep stage outputs as JSON artifacts even when the stage behaves like a skill
- write `pipeline_plan.json` and `pipeline_result.json` for reruns and debugging

Primary entry point:

```bash
python3 confluence-curation/scripts/orchestrate_pipeline.py --fetch-input /tmp/confluence.json --output-dir /tmp/pipeline-run
```

Reference:

- [references/pipeline-stage-model.md](references/pipeline-stage-model.md)

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

- Before the first fetch in a new session, run `configure_confluence.py status --json`.
- If stored config is complete, do not ask for credentials again.
- All API calls must stay at or below one request per second.
- Use token-based authentication first.
- For Confluence Cloud, do not fall back to password auth.
- For Server or Data Center, try token-based auth first and only then fall back to username/password.
- Reuse cached profile results for the same person within one fetch run.
- Prefer metadata and relationship signals before pulling full body content.
- Infer preferred spaces internally from the first search result instead of asking the user to list all spaces.
- Use preferred-space expansion as an internal retrieval step when the inferred spaces look strong enough.
- Use `--all-spaces` when the user wants cross-space search instead of a single space.
- Use `--include-body` when the user wants the skill to organize the content itself, not only metadata.
- Use `--cache-dir` to persist fetched results locally and reuse them later.
- Use `--data-dir` to persist reusable page snapshots, history, and run artifacts inside the workspace.
- Use `--cache-only` to work from saved data without making new API calls.
- Use `--refresh-cache` when the saved data should be ignored and fetched again.
- Keep fetched artifacts, normalized artifacts, page snapshots, and final reports separate so later passes can reuse them.
- Treat saved snapshots as background reference, then confirm whether the Confluence page has changed before trusting the saved content.
- If a page changed relative to the saved snapshot, surface what changed and give that change more weight within the same topic cluster.
- Treat snapshot/history data as a primary input for "what changed recently" and "what should I read now", not as a minor side note.

## Output Requirements

Always produce:
- a short Korean summary of the current best candidates
- a briefing-style summary of what recently changed and what currently deserves attention
- a Korean synthesis of the underlying content when body text is available
- a section showing the most trustworthy data cleaned up into readable bullets
- a topic-level insight section with conflicts, gaps, or action items when enough evidence exists
- a table of candidate pages
- a timeline or ordered change flow
- explicit warning flags
- a final recommendation with uncertainty noted

Output structure varies by purpose. See [references/purpose-registry.md](references/purpose-registry.md) for purpose-specific section definitions.

### `general` (기본값)
Always produce: Korean summary, briefing-style summary of recent changes and attention topics, synthesized content, trusted data bullets, topic-level insight section, candidate page table, change flow timeline, warning flags, recommendation with uncertainty.

### `change-tracking`
Always produce: trend summary, trend signals (new docs, update frequency, contributor growth), expanded timeline (30 entries), contributor analysis, document table with change frequency column, follow-up items.

### `onboarding`
Always produce: topic summary for newcomers, recommended reading order, key content bullets, background context, document map by cluster, exploration suggestions (related spaces/labels).

When the user asks for deeper insight analysis, also produce:
- topic clusters or comparable document groups
- evidence-backed conflict notes
- likely owner or maintainer signals
- suggested next actions for cleanup, migration, or verification

When the user asks a follow-up question, prefer answering in this shape:
- how the question was interpreted
- the best explanation in Korean
- supporting pages and snippets
- conflicting points
- what still needs verification
- next actions

## Preferred Space Inference (Internal Step)

After the first fetch, the agent should infer whether some spaces appear more trustworthy or more context-rich than others.
This is an internal retrieval decision.
Do not require the user to know or list all spaces.

### Signals

- repeated strong candidate pages in the same space
- recent meaningful changes in that space
- maintainer/team signals that align with the topic
- pages that provide both current execution context and background context
- spaces that reduce ambiguity or explain conflicts better than others

### Output

Use `scripts/infer_preferred_spaces.py` to emit:
- `preferred_spaces`
- `reasons`
- `candidate_pages`
- `confidence`

If the inference is weak, continue without preferred-space expansion instead of forcing it.

## Briefing And Follow-Up

The first response should read like a briefing, not just a ranked result list.

Preferred briefing sections:
- `지금 최근 관련 내용`
- `지금 주목해야 할 주제`
- `우선 읽을 문서`
- `신뢰할 만한 기준 문서와 배경 문서`
- `문서 간 충돌/중복`
- `최근 변경 흐름`
- `이해가 어려운 개념 또는 애매한 정리`
- `바로 할 수 있는 다음 행동`

When the user follows up with questions such as:
- `최근 뭐가 바뀌었나`
- `이 표현은 무슨 뜻인가`
- `그래서 내가 뭘 해야 하나`

reuse saved artifacts and answer with explanation, evidence, uncertainty, and next actions.

## Keyword Expansion (Mandatory Step)

After the initial fetch, the agent must always perform keyword expansion to broaden search coverage. Do not skip this step.

### Procedure

1. **Analyze fetch results**: Read the fetch result JSON file and comprehensively examine:
   - All page titles and their patterns
   - Labels attached to pages
   - Ancestor (parent) page hierarchy
   - Body content and its semantic themes
   - The original query's intent and scope

2. **Derive expansion keywords using your own judgment**:
   - Identify related topics, synonyms, and super/sub-concepts that the original query would miss
   - Consider the semantic context of documents, not just token frequency
   - Include both Korean and English keywords when the content is bilingual
   - Exclude keywords that are redundant with the original query
   - Select up to 5 expansion keywords

3. **Present candidates to the user for approval**:
   - For each keyword, explain why additional search with this term would find relevant pages not yet discovered
   - Include example page titles from the initial results that informed the keyword choice

4. **Run a second fetch** with the approved keywords:
   ```bash
   # One fetch per approved keyword
   python3 confluence-curation/scripts/fetch_confluence.py --query "{keyword}" --include-body --output /tmp/fetch-r2a.json
   ```

5. **Merge all rounds** using `scripts/merge_fetched.py`:
   ```bash
   python3 confluence-curation/scripts/merge_fetched.py --inputs /tmp/fetch-r1.json /tmp/fetch-r2a.json /tmp/fetch-r2b.json --output /tmp/fetch-merged.json
   ```

### Bounds

- Limit to at most 2 search rounds (original + 1 expansion).
- Select at most 5 expanded keywords.
- Merge output is capped at 500 pages by default.

### Example flow

```bash
# Round 1: initial search
python3 confluence-curation/scripts/fetch_confluence.py --query "deploy" --include-body --data-dir data --output data/fetch-r1.json

# (Agent reads data/fetch-r1.json, analyzes content, and proposes keywords like "rollback", "release")
# (User approves keywords)

# Round 2: one fetch per approved keyword
python3 confluence-curation/scripts/fetch_confluence.py --query "rollback" --include-body --data-dir data --output data/fetch-r2a.json
python3 confluence-curation/scripts/fetch_confluence.py --query "release" --include-body --data-dir data --output data/fetch-r2b.json

# Merge all rounds
python3 confluence-curation/scripts/merge_fetched.py --inputs data/fetch-r1.json data/fetch-r2a.json data/fetch-r2b.json --output data/fetch-merged.json

# Continue pipeline with merged output
python3 confluence-curation/scripts/normalize_confluence.py --input data/fetch-merged.json --output data/normalized.json
```

## Example Invocations

- `python3 confluence-curation/scripts/configure_confluence.py status --json`
- `python3 confluence-curation/scripts/fetch_confluence.py --space-key ENG --data-dir data --output data/confluence.json`
- `python3 confluence-curation/scripts/fetch_confluence.py --all-spaces --query "인공지능" --include-body --cache-dir ~/.confluence-curation-cache --data-dir data --output data/confluence-ai.json`
- `python3 confluence-curation/scripts/infer_preferred_spaces.py --input data/confluence-ai.json --output data/preferred-spaces.json`
- `python3 confluence-curation/scripts/render_insight_brief.py --fetch-input data/fetch-merged.json --insights-input data/insights.json --review-input data/review.json --summary-input data/summary.json --output data/brief.json`
- `python3 confluence-curation/scripts/answer_followup.py --insights-input data/insights.json --review-input data/review.json --normalized-input data/normalized.json --question "최근 뭐가 바뀌었나" --output data/followup.json`
- `python3 confluence-curation/scripts/expand_preferred_space.py --input data/confluence-ai.json --preferred-space ENG --preferred-space AI --output data/confluence-ai-expanded.json`
- `python3 confluence-curation/scripts/fetch_confluence.py --all-spaces --query "인공지능" --include-body --cache-dir ~/.confluence-curation-cache --data-dir data --cache-only --output data/confluence-ai.json`
- `python3 confluence-curation/scripts/curate_confluence.py --input data/confluence.json --expansion-input data/confluence-ai-expanded.json --output data/confluence.md`
- `python3 confluence-curation/scripts/curate_confluence.py --input data/confluence.json --output data/report.md --purpose change-tracking`
- `python3 confluence-curation/scripts/curate_confluence.py --input data/confluence.json --output data/report.md --purpose onboarding`
- `Use $confluence-curation to compare overlapping architecture pages and explain which page should be treated as the current working reference.`

## End-To-End Insight Pipeline Example

Use the staged pipeline when you want topic-level insight instead of only page ranking.

1. Fetch raw data:
   - `python3 confluence-curation/scripts/configure_confluence.py status --json`
   - `python3 confluence-curation/scripts/fetch_confluence.py --space-key ENG --include-body --data-dir data --output data/fetch-r1.json`
2. Keyword expansion (mandatory):
   - Agent reads `data/fetch-r1.json`, analyzes content, and proposes expansion keywords
   - User approves keywords
   - Run additional fetches per approved keyword
   - `python3 confluence-curation/scripts/merge_fetched.py --inputs data/fetch-r1.json data/fetch-r2a.json ... --output data/fetch-merged.json`
3. Normalize the fetched corpus:
   - `python3 confluence-curation/scripts/normalize_confluence.py --input data/fetch-merged.json --output data/normalized.json`
4. Cluster related pages into topics:
   - `python3 confluence-curation/scripts/cluster_confluence.py --input data/normalized.json --output data/clusters.json`
5. Build evidence packs:
   - `python3 confluence-curation/scripts/extract_evidence.py --normalized-input data/normalized.json --clusters-input data/clusters.json --output-dir data/evidence --emit-manifest data/evidence-manifest.json`
6. Synthesize topic insights (replace `{purpose}` with `general`, `change-tracking`, or `onboarding`):
   - `python3 confluence-curation/scripts/synthesize_insights.py --manifest data/evidence-manifest.json --output data/insights.json --purpose {purpose}`
7. Run the second-pass review:
   - `python3 confluence-curation/scripts/review_insights.py --input data/insights.json --output data/review.json --purpose {purpose}`
8. Render the final Markdown report:
   - `python3 confluence-curation/scripts/curate_confluence.py --input data/fetch-merged.json --insights-input data/insights.json --review-input data/review.json --output data/confluence-report.md --emit-json-summary data/confluence-summary.json --purpose {purpose}`
9. Run the fixture-based smoke test when changing the staged pipeline:
   - `python3 confluence-curation/scripts/smoke_pipeline.py`

Recommended artifact layout:
- `data/confluence.json` (or `data/fetch-r1.json`, `data/fetch-r2.json`, `data/fetch-merged.json` when using keyword expansion)
- `data/normalized.json`
- `data/clusters.json`
- `data/evidence/`
- `data/evidence-manifest.json`
- `data/insights.json`
- `data/review.json`
- `data/confluence-report.md`
- `data/pages/<page_id>/latest.json`
- `data/pages/<page_id>/history/*.json`
- `data/runs/fetch_<timestamp>.json`
- `data/features/preferred-space-expansion/latest.json`
- `data/features/cluster-confluence/latest.json`
- `data/features/curation-scoring/latest.json`

## Exit Criteria

Before finishing:
- confirm the scope of pages reviewed
- confirm what signals were available
- separate freshness from trust
- separate page-level evidence from topic-level insight
- state uncertainty clearly
- avoid claiming a definitive source of truth unless the evidence is strong
