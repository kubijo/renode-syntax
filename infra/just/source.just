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

# Generate committed parsers from grammar.js and the maintained scanner.
parser grammar="all":
    renode-source-parser --grammar {{ grammar }}

# Update expected Tree-sitter fixture trees for review.
parser-tests grammar="all":
    renode-source-parser-tests --grammar {{ grammar }}
