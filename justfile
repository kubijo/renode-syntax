import 'infra/just/prelude.just'

# Development environment and repository quality gates.
mod dev 'infra/just/dev.just'

# Sublime syntax assertions through syntect, bat's engine.
mod test 'infra/just/test.just'
