# Confluence Insight Review Rubric

## Purpose

This rubric is for second-pass review of Confluence insight outputs.

Use it when the workflow has already produced topic clusters or synthesized conclusions and you need to validate whether those conclusions are well-supported.

## Review Philosophy

- Do not reward confident language without evidence.
- Do not collapse conflicts into a single winner too early.
- Do not confuse recent edits with trustworthy ownership.
- Prefer a partial but evidenced conclusion over a complete but speculative one.

## Reviewer Lenses

### 1. Freshness Reviewer

Check:
- Is the claimed current document actually more recent?
- Does version activity support the freshness claim?
- Are there newer competing pages in the same topic?
- Is the conclusion too dependent on one timestamp?

Red flags:
- recent edit with no supporting relationship signals
- old page declared stale despite ongoing maintenance
- latest page treated as authoritative without context

### 2. Trust Reviewer

Check:
- Are maintainer or contributor signals relevant to the topic?
- Is higher seniority being overweighted?
- Is team relevance explicit or only guessed?
- Does the page appear repeatedly maintained by practitioners?

Red flags:
- title or role used as proof instead of a hint
- missing profile data ignored
- trust claim unsupported by maintainership or relationship signals

### 3. Contradiction Reviewer

Check:
- Are overlapping pages actually duplicates, or just adjacent docs?
- Are conflicts named explicitly?
- Does the output preserve both sides when evidence is split?
- Are missing links or missing body text being mistaken for agreement?

Red flags:
- duplicate claim based only on similar titles
- conflict omitted because the model preferred one page
- recommendation stated without the losing evidence being shown

### 4. Executive Reviewer

Check:
- Is the final report easy to act on?
- Are next actions concrete?
- Are uncertainty and evidence gaps visible?
- Does the report distinguish current working reference from background reference?

Red flags:
- too much scoring, not enough recommendation
- no action item despite obvious cleanup need
- ambiguity hidden behind polished wording

## Required Outputs Per Insight

Each topic-level insight should include:
- one concise conclusion
- one confidence level
- cited evidence pages
- short evidence snippets or paraphrases
- warning flags when applicable
- one or more next actions when practical

## Confidence Calibration

Use `high` only when:
- freshness signals are strong
- trust signals are strong
- conflict is low or well-resolved
- evidence is directly cited

Use `medium` when:
- the likely answer is clear but one or two key signals are incomplete

Use `low` when:
- there are unresolved conflicts
- maintainer or body evidence is weak
- the recommendation mostly depends on heuristics

## Failure Conditions

Revise the insight output if any of these are true:
- conclusion has no evidence references
- confidence is high but evidence is weak
- trust and freshness are merged into one unexplained score
- a topic has multiple plausible sources of truth and only one is shown
- there is no warning despite obvious data gaps

## Final Review Question

Before approving an insight, ask:

`If a team lead challenged this conclusion in a meeting, could we point to concrete page evidence and explain our uncertainty honestly?`

If the answer is no, the insight needs another pass.
