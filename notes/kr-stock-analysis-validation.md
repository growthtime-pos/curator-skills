# kr-stock-analysis Validation Note

Date: 2026-04-04

## Scope

This note records the local validation work completed for the installed `kr-stock-analysis` skill. The skill itself is not vendored in this repository. The validated install target is:

- `~/.codex/skills/kr-stock-analysis`

This repository now tracks the operational note only, so the actual installed skill files still live under the local Codex skills directory.

## Applied Local Changes

The installed `kr-stock-analysis` skill was updated with the following behavior changes:

- Removed `quick view` from the supported mode list.
- Defaulted general single-stock requests to `full memo`.
- Made PNG chart generation the default expectation for single-stock outputs, with explicit text or numeric fallback when OHLCV is insufficient or chart generation fails.
- Clarified that `pair compare` remains supported but does not require PNG output by default.

The installed scripts were also aligned with their documented input contracts:

- `scripts/chart-basics.js` now recognizes both `ticker` and `symbol` when labeling the output.
- `scripts/valuation-bands.js` now accepts both:
  - metric-keyed `series` objects such as `series.pe`, `series.evEbitda`, `series.pb`
  - backward-compatible flat row input with `series: [{ date, pe, evEbitda, pb }]`
- `references/script-inputs.md` was updated to match the supported formats.

## Saved Network Approval Rules

The following Codex command prefixes were approved so the local shell can run real Yahoo Finance fetches for this skill family without repeated sandbox prompts:

- `node /home/sh/.codex/skills/kr-stock-analysis/scripts/fetch-kr-chart.js`
- `node /home/sh/.codex/skills/kr-stock-analysis/scripts/portfolio-snapshot.js`

These approvals are environment-level, not repository-level. In a fresh Codex environment they may need to be approved again.

## Validation Performed

### Contract and docs

- Confirmed no remaining `quick view` references under `~/.codex/skills/kr-stock-analysis`
- Confirmed the updated prompt and reference docs route general single-stock requests to `full memo`
- Confirmed the updated docs describe PNG chart generation as the default single-stock behavior with fallback text when unavailable

### Script CLI checks

- `node ~/.codex/skills/kr-stock-analysis/scripts/fetch-kr-chart.js --help`
- `node ~/.codex/skills/kr-stock-analysis/scripts/chart-basics.js --help`
- `node ~/.codex/skills/kr-stock-analysis/scripts/valuation-bands.js --help`
- `node ~/.codex/skills/kr-stock-analysis/scripts/portfolio-snapshot.js --help`

### Real-data validation

- Fetched Samsung Electronics 1-year daily chart data with `fetch-kr-chart.js`
- Generated a PNG chart from the fetched JSON with `chart-basics.js`
- Generated a Yahoo Finance-backed portfolio snapshot with `portfolio-snapshot.js`

Observed local artifacts during validation:

- `/tmp/005930-chart.json`
- `/tmp/005930-chart.png`
- `/tmp/kr-portfolio-snapshot.md`

### Sample-data validation

- Verified `chart-basics.js` PNG generation from synthetic OHLCV input
- Verified `valuation-bands.js` for both documented metric-keyed input and backward-compatible flat row input

Observed local artifacts during validation:

- `/tmp/kr-chart-sample.json`
- `/tmp/kr-chart-sample.png`
- `/tmp/kr-valuation-sample.json`
- `/tmp/kr-valuation-flat-sample.json`

## Current Practical State

For this Codex environment, `kr-stock-analysis` and the `kr-portfolio-monitor` fallback path are now practically ready for live shell-based validation:

- `kr-stock-analysis` live chart fetch is enabled through `fetch-kr-chart.js`
- `kr-portfolio-monitor` fallback is enabled through `portfolio-snapshot.js`

No additional shell-networked scripts were found under:

- `~/.codex/skills/kr-stock-data-pack`
- `~/.codex/skills/kr-stock-update`
- `~/.codex/skills/us-stock-analysis`

## Limitation

This repository does not currently vendor the `kr-stock-analysis` skill itself. Pushing this note does not publish the installed skill changes. It only records:

- what was changed locally
- which network paths were approved
- how the installed skill was validated
