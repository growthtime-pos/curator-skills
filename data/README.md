This directory stores reusable Confluence artifacts for the workspace.

Recommended usage:
- Keep fetched JSON, normalized artifacts, and reports here for local reuse.
- Treat `pages/<page_id>/latest.json` as the latest saved background snapshot.
- Treat `pages/<page_id>/history/` as append-only page history snapshots.
- Treat `runs/` as per-fetch run artifacts.
- Treat `features/<feature-name>/latest.json` as the latest saved weight or feature-state snapshot.
- Treat `features/<feature-name>/history/` as append-only feature-state history.
- Treat `artifacts/<stage-name>/` as stage-specific reusable outputs for future pipeline features.

These artifacts are inputs to later curation passes, not authoritative source-of-truth by themselves.
Always confirm whether the upstream Confluence page changed before trusting a saved snapshot.
