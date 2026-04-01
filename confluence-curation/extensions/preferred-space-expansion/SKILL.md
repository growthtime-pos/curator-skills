---
name: preferred-space-expansion
description: Expand a Confluence keyword-search result by exploring user-preferred spaces, finding related pages through title, keyword, and hierarchy signals, and emitting a JSON artifact that another curation skill can merge without tightly coupling implementations.
---

# Preferred Space Expansion

Use this skill after a Confluence keyword search has already produced a seed JSON artifact.

This skill does not produce the final Korean report.
Its job is to:

- read the seed fetch artifact
- fetch additional pages from one or more preferred spaces
- compare those pages against the seed set
- keep only meaningfully related pages
- write a merge-friendly JSON artifact with discovery reasons and preferred-space boost hints

## When To Use

Use this skill when:

- the user trusts certain spaces more than others
- the original keyword search is too narrow
- helpful pages may exist in the preferred space even without the exact keyword
- the final reporting step should stay in another skill or script

## Workflow

1. Start from an existing fetch artifact produced by `confluence-curation/scripts/fetch_confluence.py`.
2. Run `scripts/expand_preferred_space.py` with one or more `--preferred-space` values.
3. Let the script fetch candidate pages inside those spaces.
4. Score candidate relevance using:
   - title similarity
   - keyword overlap from title/body excerpt
   - hierarchy relationship or shared ancestry
5. Keep only candidates that cross the configured threshold.
6. Save a JSON artifact for later merge into the final curation flow.

## Rules

- Do not include a page just because it belongs to a preferred space.
- A direct keyword match is not required if mixed signals are strong enough.
- Hierarchy-connected pages may pass with a slightly lower threshold.
- Keep preferred-space boost separate from freshness and trust scores.
- Emit discovery reasons so downstream ranking remains explainable.

## Output Contract

The output JSON must always include:

- `meta`
- `preferred_spaces`
- `seed_page_ids`
- `expanded_pages`
- `warnings`

Read [references/artifact-schema.md](references/artifact-schema.md) when editing the artifact contract.

## Example

```bash
python3 confluence-curation/extensions/preferred-space-expansion/scripts/expand_preferred_space.py \
  --input /tmp/confluence.json \
  --preferred-space ENG \
  --preferred-space AI \
  --output /tmp/preferred-space-expanded.json
```
