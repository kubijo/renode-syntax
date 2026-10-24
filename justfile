import 'infra/just/prelude.just'

# Development environment and repository quality gates.
mod dev 'infra/just/dev.just'

# Syntax fixtures and pinned-corpus gates for both parser engines.
mod test 'infra/just/test.just'

# Pinned Renode inputs and generated syntax data.
mod source 'infra/just/source.just'

# Prepare the local extension for the Zed review gate.
mod zed 'infra/just/zed.just'

# Weekly upstream update proposals and local rehearsals.
mod sync 'infra/just/sync.just'
