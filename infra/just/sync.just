import 'prelude.just'

# Propose an upstream update under .tmp, without publishing (network access).
dry-run *arguments:
    renode-sync-dry-run {{ arguments }}

# Rehearse the complete update against the checked older-pin fixture.
replay:
    renode-sync-replay

# Publish the checked update or review issue using GITHUB_REPOSITORY and GITHUB_TOKEN.
publish:
    renode-sync-publish
