import 'prelude.just'

# Fetch the pinned extraction sources and complete Renode corpus (network access).
fetch:
    renode-source-fetch

# Regenerate the shared data and Sublime grammars from the pins.
generate:
    renode-source-generate

# Reject stale generated data or rendered grammars (offline).
check:
    renode-source-check
