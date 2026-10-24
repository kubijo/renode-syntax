import 'prelude.just'

# Run the migrated syntax_test files with the locked syntect runner.
syntax:
    @renode-test-syntax

# Test the tooling's diagnostics, lock parsing, and failure propagation.
tooling:
    @renode-test-tooling

# Test sentinel detection and the syntax runner's corpus input handling.
runner:
    @renode-test-runner

# Check the complete pinned Renode corpus for leaked Sublime scopes (offline).
corpus:
    @renode-test-corpus

# Run the monitor grammar's Tree-sitter corpus fixtures.
parser:
    @renode-test-parser

# Parse the pinned monitor scripts with Tree-sitter (offline).
parser-corpus:
    @renode-test-parser-corpus
