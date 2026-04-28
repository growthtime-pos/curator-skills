---
name: pipeline-cluster
description: Choose and run a topic clustering method for normalized Confluence pages.
---

# Pipeline Cluster

`stage2_cluster` 는 normalized corpus 를 topic cluster 로 묶는 skill stage다.

## Methods

- `heuristic-cluster`
- `keyword-heavy-cluster`
- `hierarchy-first-cluster`

## Current Implementation

- runner: `scripts/cluster_confluence.py --strategy <method>`
