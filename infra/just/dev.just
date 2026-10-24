import 'prelude.just'

# Format maintained sources with the pinned nix-tools configuration.
format *paths:
    @renode-format "$@"

# Run nix-tools lint and Rust Clippy with pedantic warnings denied.
lint:
    @renode-lint

# Check formatting, lint, Clippy, and all Sublime syntax assertions.
check:
    @renode-check

# Evaluate and build the exported nix-tools flake checks.
flake-check:
    @renode-flake-check

# Create missing Nix input locks; may fetch dependencies.
lock:
    @renode-flake-lock

# Report and verify the development tool paths and versions.
doctor *args:
    @renode-doctor "$@"

# Lock the Python tooling dependencies against the Nix-provided Python 3.15.
python-lock:
    @renode-python-lock

# Sync the local Python environment from the reviewed dependency lock.
python-sync:
    @renode-python-sync
