# Confluence Analyze Methods

## Purpose

This document defines the analysis methods used by the staged Confluence insight workflow.

The intent is to keep `analyze` explicit instead of hiding every reasoning style inside one default summary step.

## Supported Methods

### `evidence-first`

Use when:
- the user wants a reliable current-reference recommendation
- the team mainly needs conflict, gap, and ownership visibility
- a conservative default is better than an aggressive story

Output expectations:
- one concise conclusion
- cited evidence pages and snippets
- conflict notes and evidence gaps
- practical follow-up actions

### `pyramid`

Use when:
- the user wants an executive-style summary
- the answer should come first
- the reasoning should compress to a few non-overlapping supports

Output expectations:
- `executive_answer`
- up to 3 `key_supports`
- `wider_significance`
- actions directly tied to the implication

Internal quality rules:
- key supports should be as MECE as practical
- `wider_significance` should answer "So what?" at least twice
- do not bury the answer below the evidence

### `hypothesis-driven`

Use when:
- the user is trying to explain an inconsistency or recent change
- multiple plausible sources of truth exist
- the right next step is to validate or reject a working hypothesis

Output expectations:
- `working_hypothesis`
- `validation_points`
- `hypothesis_status`
- `pivot_question`

Internal quality rules:
- define the question in SCQA spirit before locking the hypothesis
- use Issue Tree / MECE logic to avoid overlapping checks
- preserve contradicting evidence instead of forcing a winner

## Split-Skill Mapping

- `extract` should only gather and merge source data.
- `cluster` should only group pages and assemble evidence packs.
- `analyze` should select one method and emit method-aware topic judgments.
- `synthesize` should render those judgments for humans.
- `validate` should challenge overconfident or malformed outputs for the chosen method.
