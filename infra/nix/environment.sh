#!/usr/bin/env bash
# Sourced by direnv and the Nix development shell.

renode_repository_root=${RENODE_SYNTAX_ROOT:-$PWD}
while [[ ! -f "$renode_repository_root/infra/nix/flake.nix" ]]; do
    if [[ $renode_repository_root == / ]]; then
        printf 'Run Renode tooling from its repository.\n' >&2
        return 1
    fi
    renode_repository_root=$(dirname -- "$renode_repository_root")
done

if [[ -n ${RENODE_DEVELOPER_CARGO_HOME:-} ]]; then
    renode_developer_cargo_home=$RENODE_DEVELOPER_CARGO_HOME
elif [[ -n ${CARGO_HOME:-} && $CARGO_HOME != "$renode_repository_root/.tmp/cache/cargo" ]]; then
    renode_developer_cargo_home=$CARGO_HOME
else
    renode_developer_cargo_home=${HOME:-}/.cargo
fi

export RENODE_SYNTAX_ROOT="$renode_repository_root"
export RENODE_DEVELOPER_CARGO_HOME="$renode_developer_cargo_home"
export XDG_CACHE_HOME="$RENODE_SYNTAX_ROOT/.tmp/cache"
export TMPDIR="$RENODE_SYNTAX_ROOT/.tmp/scratch"
export CARGO_HOME="$XDG_CACHE_HOME/cargo"
export CARGO_TARGET_DIR="$RENODE_SYNTAX_ROOT/.tmp/cargo-target/syntax-test"
export PYTHONPYCACHEPREFIX="$XDG_CACHE_HOME/python"
export UV_CACHE_DIR="$XDG_CACHE_HOME/uv"
export UV_PROJECT_ENVIRONMENT="$RENODE_SYNTAX_ROOT/.tmp/venv/tooling"
export UV_PYTHON_DOWNLOADS=never
export NIX_CONFIG="${NIX_CONFIG:-}
warn-dirty = false"

mkdir -p "$XDG_CACHE_HOME" "$TMPDIR" "$CARGO_HOME" "$CARGO_TARGET_DIR" \
    "$RENODE_SYNTAX_ROOT/.tmp/checks"

# Cargo's cache stays disposable while its normal user configuration remains visible.
if [[ $renode_developer_cargo_home != "$CARGO_HOME" ]]; then
    for renode_cargo_config in config.toml config; do
        if [[ -f "$renode_developer_cargo_home/$renode_cargo_config" ]]; then
            ln -sfn "$renode_developer_cargo_home/$renode_cargo_config" \
                "$CARGO_HOME/$renode_cargo_config"
        elif [[ -L "$CARGO_HOME/$renode_cargo_config" ]]; then
            rm "$CARGO_HOME/$renode_cargo_config"
        fi
    done
fi
unset renode_repository_root renode_developer_cargo_home renode_cargo_config
