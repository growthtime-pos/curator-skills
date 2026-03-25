---
name: confluence-curation
description: Fetch Confluence pages and edit history, then curate which documents are most current, most trustworthy, and how related documents changed over time. Use when comparing overlapping Confluence docs, identifying likely source-of-truth candidates, ranking documents by freshness and trust signals, or summarizing document evolution with author team/title context from Confluence profiles.
---

# Confluence Curation

## Overview

Use this skill to turn a messy set of Confluence pages into a readable curation view.

The goal is not to declare one document as absolute truth.
The goal is to show:
- which pages look most current
- which pages look more trustworthy
- which pages appear stale, duplicated, or superseded
- how related pages changed over time

This skill assumes Confluence often lacks reliable labels or formal approval state.
When that happens, use author and editor context as a heuristic, not as a hard rule.

## Default Workflow

1. Define the scope first:
   - target space or all accessible spaces
   - seed page or page set
   - optional date window
2. Run `scripts/fetch_confluence.py` to collect page metadata, limited version history, body excerpts, and profile hints.
3. Read [references/scoring.md](references/scoring.md) if you need to tune trust or freshness interpretation.
4. Run `scripts/curate_confluence.py` on the fetched JSON.
5. Use [references/output-template.md](references/output-template.md) to keep the output Korean and easy to scan.
6. Call out ambiguity explicitly instead of hiding it.

## Core Judgment Rules

- Do not rely on labels or approval metadata unless they clearly exist.
- Treat title, team, and role from Confluence profiles as hints.
- Higher title does not always mean higher correctness.
- A page maintained repeatedly by the relevant working team may be more trustworthy than a page touched once by a senior person.
- A recent page is not automatically the best source of truth.
- An older page may still be useful if it is heavily referenced and still maintained.
- If evidence conflicts, report the conflict directly.

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

## Output Requirements

Always produce:
- a short Korean summary of the current best candidates
- a Korean synthesis of the underlying content when body text is available
- a section showing the most trustworthy data cleaned up into readable bullets
- a table of candidate pages
- a timeline or ordered change flow
- explicit warning flags
- a final recommendation with uncertainty noted

## Example Invocations

- `python3 confluence-curation/scripts/fetch_confluence.py --space-key ENG --output /tmp/confluence.json`
- `python3 confluence-curation/scripts/fetch_confluence.py --all-spaces --query "인공지능" --include-body --cache-dir ~/.confluence-curation-cache --output /tmp/confluence-ai.json`
- `python3 confluence-curation/scripts/fetch_confluence.py --all-spaces --query "인공지능" --include-body --cache-dir ~/.confluence-curation-cache --cache-only --output /tmp/confluence-ai.json`
- `python3 confluence-curation/scripts/curate_confluence.py --input /tmp/confluence.json --output /tmp/confluence.md`
- `Use $confluence-curation to compare overlapping architecture pages and explain which page should be treated as the current working reference.`

## Exit Criteria

Before finishing:
- confirm the scope of pages reviewed
- confirm what signals were available
- separate freshness from trust
- state uncertainty clearly
- avoid claiming a definitive source of truth unless the evidence is strong
