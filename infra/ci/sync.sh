#!/usr/bin/env bash
# Only bootstrap Nix here; the locked shell owns all commands and orchestration.
set -euo pipefail
source infra/nix/environment.sh
exec nix develop --no-update-lock-file --command renode-sync-ci
