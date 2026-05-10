#!/usr/bin/env bash
# Install curator-skills into OpenCode's global locations via symlinks.
#
# Usage:
#   bash scripts/install.sh                 install (skill + plugin symlinks)
#   bash scripts/install.sh --uninstall     remove the symlinks created above
#   bash scripts/install.sh --force         overwrite if a target exists
#
# Targets (override OPENCODE_HOME to change the prefix):
#   $OPENCODE_HOME/skills/confluence-curation  -> <repo>/confluence-curation
#   $OPENCODE_HOME/plugins/skill-update-check.js -> <repo>/.opencode/plugins/skill-update-check.js

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OPENCODE_HOME="${OPENCODE_HOME:-$HOME/.config/opencode}"

SKILL_SOURCE="$REPO_ROOT/confluence-curation"
PLUGIN_SOURCE="$REPO_ROOT/.opencode/plugins/skill-update-check.js"

SKILL_TARGET="$OPENCODE_HOME/skills/confluence-curation"
PLUGIN_TARGET="$OPENCODE_HOME/plugins/skill-update-check.js"

MODE=install
FORCE=0

usage() {
  sed -n '2,11p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

for arg in "$@"; do
  case "$arg" in
    --uninstall) MODE=uninstall ;;
    --force) FORCE=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; usage; exit 2 ;;
  esac
done

remove_link() {
  local p="$1"
  if [ -L "$p" ]; then
    rm "$p"
    echo "  removed symlink: $p"
  elif [ -e "$p" ]; then
    echo "  skipping (not a symlink): $p" >&2
  else
    echo "  not present: $p"
  fi
}

place_link() {
  local target="$1" src="$2"
  if [ ! -e "$src" ]; then
    echo "  source missing: $src" >&2
    return 1
  fi
  if [ -L "$target" ]; then
    local current
    current="$(readlink "$target")"
    if [ "$current" = "$src" ]; then
      echo "  already linked: $target"
      return 0
    fi
    if [ "$FORCE" -eq 1 ]; then
      rm "$target"
    else
      echo "  exists with different target: $target -> $current" >&2
      echo "  use --force to overwrite" >&2
      return 1
    fi
  elif [ -e "$target" ]; then
    if [ "$FORCE" -eq 1 ]; then
      rm -rf "$target"
    else
      echo "  exists (not a symlink): $target" >&2
      echo "  use --force to overwrite" >&2
      return 1
    fi
  fi
  mkdir -p "$(dirname "$target")"
  ln -s "$src" "$target"
  echo "  linked: $target -> $src"
}

if [ "$MODE" = uninstall ]; then
  echo "Uninstalling curator-skills symlinks from $OPENCODE_HOME"
  remove_link "$SKILL_TARGET"
  remove_link "$PLUGIN_TARGET"
  exit 0
fi

echo "Installing curator-skills into $OPENCODE_HOME"
echo "Source repo: $REPO_ROOT"
place_link "$SKILL_TARGET" "$SKILL_SOURCE"
place_link "$PLUGIN_TARGET" "$PLUGIN_SOURCE"
echo "Done. Auto-update check runs once per hour at session start."
