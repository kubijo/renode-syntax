import 'prelude.just'

# Fetch the pinned extraction sources and complete Renode corpus (network access).
fetch:
    renode-source-fetch

# Generate shared data, Sublime grammars, and Zed highlights from the pins.
generate:
    renode-source-generate

# Reject stale generated data or rendered grammars (offline).
check:
    renode-source-check

# Generate the committed Tree-sitter monitor parser from grammar.js.
parser:
    renode-source-parser

# Update expected Tree-sitter fixture trees for review.
parser-tests:
    renode-source-parser-tests
