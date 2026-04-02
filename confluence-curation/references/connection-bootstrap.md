# Connection Bootstrap

This note defines how the skill should discover saved Confluence credentials at the start of every new session.

## Required Bootstrap Step

Always run:

```bash
python3 confluence-curation/scripts/configure_confluence.py status --json
```

If `config_found` is `true` and `missing_required_fields` is empty, reuse the saved configuration immediately.
Do not ask the user to re-enter credentials in that case.

If the config is missing or incomplete, ask only for the missing values and store them with `configure_confluence.py set`.

## Config Resolution Order

The active config source is resolved in this order:

1. `CONFLUENCE_CONFIG_PATH`
2. `~/.config/confluence-curation/config.json`
3. `~/.confluence-curation.json`

The first existing file wins.
If the winning file is invalid JSON or empty, treat it as the active location and surface the problem instead of silently falling through.

## Storage Rules

- Store new values in `~/.config/confluence-curation/config.json` unless `--config` or `CONFLUENCE_CONFIG_PATH` explicitly overrides the location.
- Do not store secrets in `references/`.
- Do not copy secrets into prompt references or checked-in files.
