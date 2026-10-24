#!/usr/bin/env bash

# source_env evaluates this file from infra/nix/.
source_env environment.sh
cd "$RENODE_SYNTAX_ROOT" || return 1
# Read by direnv's layout helper.
# shellcheck disable=SC2034
direnv_layout_dir="$RENODE_SYNTAX_ROOT/.tmp/direnv"
watch_file flake.nix flake.lock infra/nix/flake.nix infra/nix/commands.nix \
    infra/nix/python-tools.nix infra/nix/environment.sh pyproject.toml uv.lock

renode_nix_direnv=$(nix build --no-link --print-out-paths --no-update-lock-file \
    .#nix-direnv)
# Load the pinned helper without changing the user's direnv configuration.
# shellcheck disable=SC1091
source "$renode_nix_direnv/share/nix-direnv/direnvrc"
nix_direnv_disallow_fallback
unset renode_nix_direnv
