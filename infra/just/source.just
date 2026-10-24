import 'prelude.just'

# Fetch and validate the pinned upstream source inputs (network access).
fetch:
    renode-source-fetch

# Regenerate the shared data and Sublime grammars from the pins.
generate:
    renode-source-generate

# Reject stale generated data or rendered grammars (offline).
check:
    renode-source-check
