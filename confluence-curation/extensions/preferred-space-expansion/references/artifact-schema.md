# Preferred Space Expansion Artifact

## Required Top-Level Fields

- `meta.schema_version`
- `meta.source_fetch_path`
- `meta.generated_at`
- `preferred_spaces`
- `seed_page_ids`
- `expanded_pages`
- `warnings`

## Expanded Page Fields

Each item in `expanded_pages` must include:

- `page_id`
- `title`
- `space_key`
- `related_seed_page_ids`
- `relatedness_score`
- `discovery_reasons`
- `preferred_space_match`

It may also include the normalized page fields needed by downstream curation, such as:

- `url`
- `status`
- `created_at`
- `updated_at`
- `version_number`
- `ancestors`
- `labels`
- `version_events`
- `recent_contributors`
- `body_excerpt`

## Optional Supporting Fields

- `people`
- `links`
- `warnings`

`links` is reserved for relationship edges that the downstream curation flow can merge into its own `relationships` array.

## Compatibility Rules

- Treat the artifact as append-only where practical.
- Keep freshness/trust scores out of this artifact.
- Keep preferred-space boost as a hint field, not a final ranking decision.
- Prefer stable field names over nested restructuring so multiple implementations can merge safely.
