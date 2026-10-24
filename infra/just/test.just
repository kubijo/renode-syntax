import 'prelude.just'

# Run the migrated syntax_test files with the locked syntect runner.
syntax:
    @renode-test-syntax

# Test the tooling's diagnostics, lock parsing, and failure propagation.
tooling:
    @renode-test-tooling
