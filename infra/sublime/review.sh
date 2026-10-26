#!/usr/bin/env bash
set -euo pipefail

: "${RENODE_SYNTAX_ROOT:?Enter the Nix development shell first}"
if ! command -v smerge >/dev/null 2>&1; then
    printf 'Sublime Merge (smerge) is not installed\n' >&2
    exit 1
fi
if [[ -z ${DISPLAY:-} ]]; then
    printf 'Sublime Merge review needs an X display\n' >&2
    exit 1
fi

review_state="$RENODE_SYNTAX_ROOT/.tmp/sublime-merge"
export XDG_CONFIG_HOME="$review_state/config"
export XDG_CACHE_HOME="$review_state/cache"
export XDG_DATA_HOME="$review_state/data"
export XDG_RUNTIME_DIR="$review_state/runtime"
unset WAYLAND_DISPLAY

package="$XDG_CONFIG_HOME/sublime-merge/Packages/Renode"
mkdir -p "$package" "$XDG_CACHE_HOME" "$XDG_DATA_HOME" "$XDG_RUNTIME_DIR"
chmod 700 "$XDG_RUNTIME_DIR"
cp -- "$RENODE_SYNTAX_ROOT/integrations/sublime/RenodePlatform.sublime-syntax" "$package/"
cp -- "$RENODE_SYNTAX_ROOT/integrations/sublime/RenodeScript.sublime-syntax" "$package/"

cd "$RENODE_SYNTAX_ROOT"
if [[ -n ${1:-} ]]; then
    if [[ ! -f $1 ]]; then
        printf 'Review file does not exist: %s\n' "$1" >&2
        exit 1
    fi
    exec smerge blame "$1"
fi
printf 'Review infra/fixtures/scope-boundaries.repl and review.resc in Sublime Merge Changes\n'
exec smerge "$RENODE_SYNTAX_ROOT"
