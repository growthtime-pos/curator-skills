# Confluence Insight Implementation Roadmap

## Goal

Evolve the repository from page-level curation into topic-level insight analysis while preserving explainability and low operational risk.

## Phase 1: Strengthen The Existing Pipeline

Objective:
- keep the current `fetch -> curate -> report` path working
- define the new artifact model without breaking existing users

Deliverables:
- architecture reference
- review rubric
- updated skill and prompt wording
- updated output template for topic-level insight sections

Success criteria:
- current users can still run the old workflow
- future contributors understand the staged direction clearly

## Phase 2: Add Normalization

Objective:
- create a stable analysis-friendly schema between fetch and curation

Suggested script:
- `scripts/normalize_confluence.py`

Responsibilities:
- normalize pages, people, and relationships
- extract sentence-level snippets from body excerpts
- preserve warnings and missing signals

Primary output:
- `normalized.json`

Success criteria:
- downstream stages no longer depend directly on raw fetch shape

## Phase 3: Add Topic Clustering

Objective:
- group related pages into comparable topic clusters

Suggested script:
- `scripts/cluster_confluence.py`

Signals:
- title similarity
- hierarchy links
- shared contributors
- shared labels
- excerpt keyword overlap

Primary output:
- `clusters.json`

Success criteria:
- overlapping documents are grouped well enough for human review

## Phase 4: Add Evidence Packs

Objective:
- build compact evidence bundles for each topic

Suggested script:
- `scripts/extract_evidence.py`

Each pack should include:
- current candidate
- trusted candidate
- stale or superseded candidate
- maintainer signals
- recent change summary
- conflict notes
- evidence snippets

Primary output:
- `evidence/topic_<id>.json`

Success criteria:
- synthesis can run on compact topic inputs instead of the whole corpus

## Phase 5: Add Insight Synthesis

Objective:
- generate topic-level conclusions and recommended actions

Suggested script:
- `scripts/synthesize_insights.py`

Questions to answer:
- what is the current working reference?
- what is still useful as background?
- what conflicts remain unresolved?
- what should be merged, archived, or verified next?

Primary output:
- `insights.json`

Success criteria:
- each cluster yields a concise evidence-backed insight summary

## Phase 6: Add Review Passes

Objective:
- challenge overconfident or weakly supported conclusions

Suggested script:
- `scripts/review_insights.py`

Suggested review lenses:
- freshness
- trust
- contradiction
- executive actionability

Primary output:
- `review_notes.json`

Success criteria:
- final report confidence is better calibrated than first-pass synthesis

## Phase 7: Upgrade Final Reporting

Objective:
- extend the final markdown output from page ranking to decision support

Possible approach:
- extend `scripts/curate_confluence.py`
- or add a dedicated `scripts/render_report.py`

Recommended sections:
- overall summary
- topic-by-topic insight cards
- current vs trusted references
- conflict map
- recent change flow
- action items
- uncertainty and data gaps

Success criteria:
- a team lead can use the report directly in documentation cleanup or operating review

## Validation Strategy

At each phase, prefer lightweight validation:

- `python -m py_compile ...`
- smallest relevant `--help` invocation
- manual fixture runs on small cached fetch outputs
- visual inspection of JSON artifact shape

When sample corpora exist, keep one or two small deterministic fixtures for regression checks.

## Guardrails

- Preserve Korean output expectations in final reports.
- Keep the fetch stage network-aware and the later stages offline.
- Avoid introducing opaque scoring that cannot be explained back to the user.
- Prefer stable schemas and reviewable diffs over broad rewrites.
