# Confluence Insight Architecture

## Purpose

This document describes how to evolve Confluence curation into a staged insight-analysis workflow.

The design goal is not just to rank pages.
It is to produce topic-level understanding with evidence, uncertainty, and follow-up actions.

The architecture is inspired by artifact-first workflow systems such as `gstack`.
The main idea to borrow is staged analysis with explicit intermediate outputs.

## Design Principles

- Prefer small deterministic stages over one opaque end-to-end prompt.
- Persist intermediate artifacts so later passes can inspect, reuse, and challenge earlier conclusions.
- Keep retrieval and synthesis separate.
- Treat disagreement as a valid output, not as a failure.
- Link every final insight to evidence pages and short snippets.
- Preserve the distinction between freshness, trust, uncertainty, and actionability.

## Target Workflow

1. fetch
2. infer-preferred-space
3. preferred-space-expand
4. normalize
5. cluster
6. evidence-pack
7. synthesize
8. review
9. report
10. follow-up answer

Each stage should read a stable input artifact and write a stable output artifact.

## Stage Details

### 1. Fetch

Source: `scripts/fetch_confluence.py`

Collect:
- page metadata
- recent version events
- contributor IDs
- profile hints
- optional body excerpts
- page relationships

Primary output:
- `fetch.json`

### 2. Normalize

### 2. Infer Preferred Space

Source:
- `scripts/infer_preferred_spaces.py`

Role:
- inspect the initial fetch result
- infer which spaces appear more trustworthy or more context-rich
- choose a small set of preferred spaces without asking the user
- emit reasons and candidate pages for internal expansion

Primary output:
- `preferred-spaces.json`

### 3. Preferred Space Expand

Source:
- `scripts/expand_preferred_space.py`

Role:
- use the inferred preferred spaces as internal expansion targets
- fetch related pages from those spaces
- keep only meaningfully related pages
- preserve discovery reasons for later ranking and explanation

Primary output:
- `preferred-space-expanded.json`

### 4. Normalize

Convert raw fetched data into a corpus designed for downstream analysis.

Recommended normalized structures:
- pages
- people
- relationships
- sentence-level excerpts
- lightweight claims or key-statement candidates
- warnings

Primary output:
- `normalized.json`

### 5. Cluster

Group pages by topic rather than by page ID alone.

Signals to combine:
- title similarity
- ancestor or child relationships
- shared contributors
- shared labels
- shared keywords from excerpts
- explicit inter-page links when available

Primary output:
- `clusters.json`

Each cluster should include:
- cluster ID
- representative title
- page IDs
- likely current page
- likely background page
- confidence

### 4. Evidence Pack

For each cluster, assemble the minimum evidence needed for synthesis.

Include:
- current candidate pages
- trusted candidate pages
- stale or superseded candidates
- notable changes
- maintainer signals
- conflict candidates
- missing signals
- quoted or short paraphrased evidence

Primary output:
- `evidence/topic_<id>.json`

## 7. Synthesize

Generate topic-level insights, not just page rankings.

Questions to answer:
- Which page should the team use as the current working reference?
- Which page still matters as background or policy context?
- What changed recently?
- Which documents conflict or overlap?
- What evidence is weak or missing?
- What operational cleanup should happen next?

Primary output:
- `insights.json`

Each insight should carry:
- topic ID
- conclusion
- confidence
- evidence page IDs
- evidence snippets
- warnings
- suggested actions

### 8. Review

Run one or more second-pass reviewers over synthesized insights.

Suggested reviewer lenses:
- freshness reviewer
- trust reviewer
- contradiction reviewer
- executive-summary reviewer

The review stage should challenge unsupported claims and reduce overconfidence.

Primary output:
- `review_notes.json`

### 9. Report

Render a final Korean report for human decision-makers.

Recommended sections:
- overall summary
- topic-by-topic insights
- current vs trusted references
- conflict map
- recent change flow
- warning flags
- recommended actions

Primary output:
- `report.md`
- optional `summary.json`

The first response should be readable as a briefing, not just a ranking report.

### 10. Follow-Up Answer

Source:
- `scripts/answer_followup.py`

Role:
- interpret a user follow-up question against the saved artifacts
- find the most relevant topic cluster and supporting pages
- answer with explanation, evidence, uncertainty, and next actions

Primary output:
- `followup_answer.json`

## Artifact Layout

One possible working layout:

```text
tmp/
  fetch.json
  normalized.json
  clusters.json
  evidence/
    topic_001.json
    topic_002.json
  insights.json
  review_notes.json
  report.md
```

## MVP Scope

The minimum useful insight workflow should be able to:
- cluster related pages
- identify current, trusted, stale, and conflicting candidates per topic
- cite evidence for every major conclusion
- render a Korean report with uncertainty and next actions

## Non-Goals For The First Iteration

- heavy knowledge-graph infrastructure
- full semantic diffing across all versions
- perfect claim extraction
- replacing human judgment with a single score

Start with simple, explainable heuristics and expand only when the added complexity yields better decisions.
