---
name: pipeline-validate
description: Run a second-pass validation strategy over synthesized insights and recalibrate confidence or verdicts.
---

# Pipeline Validate

`stage5_validate` 는 synthesized insight 를 second-pass 로 재검토하는 skill stage다.

## Methods

- `balanced-validator`
- `strict-validator`
- `freshness-validator`
- `executive-validator`

## Current Implementation

- runner: `scripts/review_insights.py --strategy <method> --purpose <purpose>`
