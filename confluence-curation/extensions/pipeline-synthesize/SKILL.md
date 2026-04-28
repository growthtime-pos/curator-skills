---
name: pipeline-synthesize
description: Convert evidence packs into topic-level conclusions and actions with a selectable synthesis strategy.
---

# Pipeline Synthesize

`stage4_synthesize` 는 evidence pack 을 사람이 읽을 결론과 action 으로 압축하는 skill stage다.

## Methods

- `balanced-synthesis`
- `briefing-synthesis`
- `action-heavy-synthesis`

## Current Implementation

- runner: `scripts/synthesize_insights.py --strategy <method> --purpose <purpose>`
