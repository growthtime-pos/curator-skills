# Confluence Curation Scoring

## Purpose

This reference defines how to score Confluence pages for:

- freshness
- trust
- uncertainty
- change relevance

These scores are heuristics.
They support human judgment rather than replace it.

## Scoring Model

Use four layers:

1. freshness score
2. trust score
3. uncertainty modifier
4. relationship signals

Keep scores in a simple `0-100` range.

## Freshness

Main signals:

- last updated time
- recent version activity
- repeated maintenance
- recent contributor diversity

Suggested interpretation:

- updated within 7 days: very strong freshness
- updated within 30 days: strong freshness
- updated within 90 days: moderate freshness
- updated within 180 days: weak freshness
- older than 180 days: stale unless other evidence offsets it

## Trust

Main signals:

- likely role relevance of author or recent editors
- likely team relevance of author or recent editors
- repeated edits by likely domain contributors
- linked or referenced by related pages
- hierarchy position

Important rules:

- higher title is not automatically higher trust
- repeated maintenance by practitioners can outweigh a single edit from leadership
- if team/title is inferred weakly, lower confidence instead of forcing certainty

## Uncertainty

Raise uncertainty when:

- author or editor profile fields are missing
- team/title is inferred from weak profile text
- multiple pages compete for the same topic
- a recent page is poorly connected
- trust and freshness conflict strongly

Confidence levels:

- `high`
- `medium`
- `low`

## Status Flags

- `fresh-and-trusted`
- `fresh-but-unverified`
- `trusted-but-stale`
- `likely-duplicate`
- `likely-superseded`
- `needs-review`

## Evidence Summary

Every scored page should include short evidence such as:

- `최근 14일 내 3회 수정`
- `Platform Team 참여 흔적 존재`
- `관련 문서에서 반복 참조`
- `직책 정보는 있으나 확신은 낮음`
