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

# Compile and test Emacs modes, highlighting and embedded-language ranges.
emacs:
    @renode-test-emacs

# Check the complete pinned Renode corpus for leaked Sublime scopes (offline).
corpus:
    @renode-test-corpus

# Run the Tree-sitter grammar fixtures.
parser grammar="all":
    @renode-test-parser --grammar {{ grammar }}

# Parse pinned scripts, platform descriptions and embedded monitor bodies (offline).
parser-corpus grammar="all":
    @renode-test-parser-corpus --grammar {{ grammar }}
