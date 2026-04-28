---
name: pipeline-pre-analysis
description: Decide how to interpret the initial fetch result, infer preferred spaces, and optionally expand related pages before downstream analysis.
---

# Pipeline Pre-analysis

`stage0_pre_analysis` 는 raw fetch 결과에서 확장 방향을 정하는 stage다.

## Methods

- `infer-expand`
- `infer-only`
- `disabled`

## Current Implementation

- preferred space 추론: `scripts/infer_preferred_spaces.py`
- preferred space 확장: `scripts/expand_preferred_space.py`
- expansion merge: orchestrator 내부 merge contract
